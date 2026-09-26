"""Live screen and window capture worker utilizing Windows Graphics Capture.

Complies with the Google Python Style Guide.
Handles window resolution, frame arrival callbacks, and recognition dispatch.
"""

import ctypes
import ctypes.wintypes
import logging
import os
import sys
import time
from typing import Optional
import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal

import config
from core.engine import parse_frame
from dev.debug_dumper import save_crop_debug

logger = logging.getLogger(__name__)


def find_window_by_title_safe(target_title: str) -> Optional[int]:
  """Safely finds a window HWND matching target_title without message deadlocks.

  Args:
    target_title: Substring or full title of the target window.

  Returns:
    HWND integer if found and valid, otherwise None.
  """
  if not target_title or sys.platform != "win32":
    return None

  user32 = ctypes.windll.user32

  # 1. Exact match via FindWindowW (non-blocking kernel table read)
  hwnd = user32.FindWindowW(None, target_title)
  if hwnd and user32.IsWindow(hwnd) and user32.IsWindowVisible(hwnd):
    return hwnd

  # 2. Case-insensitive substring match via InternalGetWindowText
  curr_pid = os.getpid()
  found_hwnd: Optional[int] = None
  target_lower = target_title.lower()

  def enum_cb(h, _):
    nonlocal found_hwnd
    if not user32.IsWindowVisible(h):
      return True
    lp_pid = ctypes.wintypes.DWORD()
    user32.GetWindowThreadProcessId(h, ctypes.byref(lp_pid))
    if lp_pid.value == curr_pid:
      return True  # Avoid inspecting own application windows
    buf = ctypes.create_unicode_buffer(512)
    n = user32.InternalGetWindowText(h, buf, 512)
    if n > 0 and target_lower in buf.value.lower():
      found_hwnd = h
      return False
    return True

  wnd_enum_proc = ctypes.WINFUNCTYPE(
      ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM
  )
  user32.EnumWindows(wnd_enum_proc(enum_cb), 0)
  return found_hwnd


class CaptureWorker(QThread):
  """Background screen capture worker sampling via Windows Graphics Capture with GDI fallback."""

  frame_parsed = pyqtSignal(int, float, float)
  status_changed = pyqtSignal(str, bool)

  def __init__(
      self,
      target_window: str = config.DEFAULT_TARGET_WINDOW,
      target_hwnd: Optional[int] = None,
  ):
    super().__init__()
    self.running: bool = True
    self.sample_interval: float = 1.0
    self.target_window: str = target_window
    self.target_hwnd: Optional[int] = target_hwnd
    self.capture_control = None

  def _run_win32_gdi_capture(self, target_h: int) -> None:
    """Fallback capture loop using Win32 GDI (PrintWindow / BitBlt).

    Provides 100% universal capture compatibility across all Windows builds,
    VMs, or environments where Windows Graphics Capture API is unavailable
    or restricted.
    """
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32

    class BITMAPINFOHEADER(ctypes.Structure):
      _fields_ = [
          ("biSize", ctypes.c_uint32),
          ("biWidth", ctypes.c_int32),
          ("biHeight", ctypes.c_int32),
          ("biPlanes", ctypes.c_uint16),
          ("biBitCount", ctypes.c_uint16),
          ("biCompression", ctypes.c_uint32),
          ("biSizeImage", ctypes.c_uint32),
          ("biXPelsPerMeter", ctypes.c_int32),
          ("biYPelsPerMeter", ctypes.c_int32),
          ("biClrUsed", ctypes.c_uint32),
          ("biClrImportant", ctypes.c_uint32),
      ]

    last_sample_time = 0.0
    last_res = None
    logger.info("Engaging Win32 GDI window capture fallback for HWND %d", target_h)

    while self.running and user32.IsWindow(target_h):
      now = time.time()
      if now - last_sample_time < self.sample_interval:
        time.sleep(0.05)
        continue
      last_sample_time = now

      rect = ctypes.wintypes.RECT()
      user32.GetClientRect(target_h, ctypes.byref(rect))
      w = rect.right - rect.left
      h = rect.bottom - rect.top
      if w <= 0 or h <= 0:
        time.sleep(0.1)
        continue

      hwnd_dc = user32.GetDC(target_h)
      if not hwnd_dc:
        time.sleep(0.1)
        continue

      mem_dc = gdi32.CreateCompatibleDC(hwnd_dc)
      bmp = gdi32.CreateCompatibleBitmap(hwnd_dc, w, h)
      old_bmp = gdi32.SelectObject(mem_dc, bmp)

      # Try PW_RENDERFULLCONTENT (flag 2), fallback to standard (0), then BitBlt
      res = user32.PrintWindow(target_h, mem_dc, 2)
      if not res:
        res = user32.PrintWindow(target_h, mem_dc, 0)
      if not res:
        pt = ctypes.wintypes.POINT(0, 0)
        user32.ClientToScreen(target_h, ctypes.byref(pt))
        screen_dc = user32.GetDC(0)
        gdi32.BitBlt(mem_dc, 0, 0, w, h, screen_dc, pt.x, pt.y, 0x00CC0020)
        user32.ReleaseDC(0, screen_dc)

      header = BITMAPINFOHEADER()
      header.biSize = ctypes.sizeof(BITMAPINFOHEADER)
      header.biWidth = w
      header.biHeight = -h  # Top-down DIB
      header.biPlanes = 1
      header.biBitCount = 32
      header.biCompression = 0

      buf = (ctypes.c_char * (w * h * 4))()
      gdi32.GetDIBits(mem_dc, bmp, 0, h, buf, ctypes.byref(header), 0)

      # Cleanup GDI handles immediately
      gdi32.SelectObject(mem_dc, old_bmp)
      gdi32.DeleteObject(bmp)
      gdi32.DeleteDC(mem_dc)
      user32.ReleaseDC(target_h, hwnd_dc)

      arr = np.frombuffer(buf, dtype=np.uint8).reshape((h, w, 4))
      bgr = np.ascontiguousarray(arr[:, :, :3])

      cur_res = (bgr.shape[1], bgr.shape[0])
      res_changed = last_res != cur_res
      if res_changed:
        last_res = cur_res

      try:
        parsed = parse_frame(bgr)
        if parsed:
          if res_changed and config.IS_DEV:
            save_crop_debug(bgr, parsed)

          exp_val, pct, raw_str, dt_ms = parsed[:4]
          self.frame_parsed.emit(
              exp_val, pct if pct is not None else -1.0, dt_ms
          )
          self.status_changed.emit("即時辨識鎖定中", True)
        else:
          self.status_changed.emit("搜尋經驗條中...", False)
      except Exception as e:
        self.status_changed.emit(f"捕捉異常: {e}", False)

  def run(self) -> None:
    """Executes the capture event loop."""
    if sys.platform == "darwin":
      self._run_macos_capture()
      return

    has_windows_capture = True
    try:
      from windows_capture import Frame, WindowsCapture
    except ImportError:
      has_windows_capture = False
      logger.warning("windows_capture not available; using GDI capture fallback")

    last_sample_time = 0.0
    last_res = None

    def on_frame_arrived(frame, capture_control):
      nonlocal last_sample_time, last_res
      if not self.running:
        capture_control.stop()
        return

      now = time.time()
      if now - last_sample_time < self.sample_interval:
        return
      last_sample_time = now

      try:
        bgr = frame.convert_to_bgr().frame_buffer
        cur_res = (bgr.shape[1], bgr.shape[0])
        res_changed = last_res != cur_res
        if res_changed:
          last_res = cur_res

        parsed = parse_frame(bgr)
        if parsed:
          if res_changed and config.IS_DEV:
            save_crop_debug(bgr, parsed)

          exp_val, pct, raw_str, dt_ms = parsed[:4]
          self.frame_parsed.emit(
              exp_val, pct if pct is not None else -1.0, dt_ms
          )
          self.status_changed.emit("即時辨識鎖定中", True)
        else:
          self.status_changed.emit("搜尋經驗條中...", False)
      except Exception as e:
        self.status_changed.emit(f"捕捉異常: {e}", False)

    def on_closed():
      pass

    user32 = ctypes.windll.user32 if sys.platform == "win32" else None

    while self.running:
      win_desc = (
          self.target_window
          if self.target_window
          else f"HWND {self.target_hwnd}"
      )

      # 1. Resolve target HWND
      target_h = self.target_hwnd
      if not target_h and self.target_window:
        target_h = find_window_by_title_safe(self.target_window)

      if not target_h or (user32 and not user32.IsWindow(target_h)):
        self.status_changed.emit(f"尋找視窗 [{win_desc}]...", False)
        for _ in range(10):
          if not self.running:
            break
          time.sleep(0.1)
        continue

      # If windows_capture is not available, jump directly to GDI fallback
      if not has_windows_capture:
        self.status_changed.emit(f"連線至視窗 [{win_desc}]...", False)
        self._run_win32_gdi_capture(target_h)
        continue

      # 2. Window verified: attach via Windows Graphics Capture
      self.status_changed.emit(f"連線至視窗 [{win_desc}]...", False)
      try:
        # Tier 1: Optimal settings (no border, no cursor)
        try:
          capture = WindowsCapture(
              cursor_capture=False,
              draw_border=False,
              window_hwnd=target_h,
          )
          capture.event(on_frame_arrived)
          capture.event(on_closed)
          self.capture_control = capture.start_free_threaded()
        except Exception as e_opt:
          logger.warning(
              "WindowsCapture with border/cursor disabled failed (%s). Retrying with compatibility settings...",
              e_opt,
          )
          # Tier 2: Compatibility settings (pass None to avoid invoking unsupported APIs on older Windows 10 builds)
          capture = WindowsCapture(
              cursor_capture=None,
              draw_border=None,
              window_hwnd=target_h,
          )
          capture.event(on_frame_arrived)
          capture.event(on_closed)
          self.capture_control = capture.start_free_threaded()

        while self.running and not self.capture_control.is_finished():
          if user32 and not user32.IsWindow(target_h):
            break
          time.sleep(0.2)

        if self.capture_control and not self.capture_control.is_finished():
          self.capture_control.stop()

      except Exception as e:
        logger.warning(
            "Windows Graphics Capture failed (%s). Engaging Win32 GDI fallback...",
            e,
        )
        if self.running and user32 and user32.IsWindow(target_h):
          self._run_win32_gdi_capture(target_h)
        else:
          self.status_changed.emit(f"捕捉異常: {e}", False)
          for _ in range(10):
            if not self.running:
              break
            time.sleep(0.1)

  def _run_macos_capture(self) -> None:
    """Executes the macOS CoreGraphics window capture loop."""
    try:
      from core.capture_macos import (
          capture_macos_window,
          check_and_request_macos_screen_recording_permission,
          find_macos_window_by_title,
      )
    except Exception as e:
      self.status_changed.emit(f"macOS 捕獲模組初始化失敗: {e}", False)
      while self.running:
        time.sleep(0.5)
      return

    check_and_request_macos_screen_recording_permission()

    last_sample_time = 0.0
    last_res = None

    while self.running:
      win_to_find = (
          self.target_window
          if self.target_window
          else config.DEFAULT_TARGET_WINDOW
      )
      win_desc = (
          win_to_find
          if not self.target_hwnd
          else f"Window ID {self.target_hwnd}"
      )

      target_id = self.target_hwnd
      if not target_id:
        target_id = find_macos_window_by_title(win_to_find)
        if not target_id and win_to_find != "MapleStory Worlds":
          target_id = find_macos_window_by_title("MapleStory Worlds")

      if not target_id:
        self.status_changed.emit(
            f"尋找視窗 [{win_desc}]... (或使用 -v 模擬)", False
        )
        for _ in range(10):
          if not self.running:
            break
          time.sleep(0.1)
        continue

      self.status_changed.emit(f"連線至視窗 [{win_desc}]...", False)
      while self.running:
        now = time.time()
        if now - last_sample_time >= self.sample_interval:
          last_sample_time = now
          bgr = capture_macos_window(target_id)
          if bgr is None:
            # Window was closed or permission revoked
            break

          cur_res = (bgr.shape[1], bgr.shape[0])
          res_changed = last_res != cur_res
          if res_changed:
            last_res = cur_res

          parsed = parse_frame(bgr)
          if parsed:
            if res_changed and config.IS_DEV:
              save_crop_debug(bgr, parsed)

            exp_val, pct, raw_str, dt_ms = parsed[:4]
            self.frame_parsed.emit(
                exp_val, pct if pct is not None else -1.0, dt_ms
            )
            self.status_changed.emit("即時辨識鎖定中", True)
          else:
            self.status_changed.emit("搜尋經驗條中...", False)

        time.sleep(0.05)

  def stop(self) -> None:
    """Stops the capture worker and releases underlying handles."""
    self.running = False
    if self.capture_control and not self.capture_control.is_finished():
      try:
        self.capture_control.stop()
      except Exception:
        pass
    self.wait(1000)
