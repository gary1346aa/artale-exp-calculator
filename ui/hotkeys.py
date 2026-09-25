"""Global Windows hotkey listener for F7, F8, and F9.

Complies with the Google Python Style Guide.
Uses Win32 RegisterHotKey to listen without polling or thread blockage.
"""

import ctypes
import ctypes.wintypes
import sys
import time
from PyQt6.QtCore import QThread, pyqtSignal


class HotkeyWorker(QThread):
  """Global Windows hotkey listener for F6 (Auto Start), F7 (Start/Pause), F8 (Reset), F9 (Game Mode)."""

  f6_pressed = pyqtSignal()
  f7_pressed = pyqtSignal()
  f8_pressed = pyqtSignal()
  f9_pressed = pyqtSignal()

  def __init__(self):
    super().__init__()
    self.running: bool = True
    self.tid: int = 0

  def run(self) -> None:
    """Executes the Win32 message pump for registered hotkeys."""
    if sys.platform != "win32":
      return

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    self.tid = kernel32.GetCurrentThreadId()

    mod_norepeat = 0x4000
    vk_f6 = 0x75
    vk_f7 = 0x76
    vk_f8 = 0x77
    vk_f9 = 0x78

    hotkey_id_f6 = 1006
    hotkey_id_f7 = 1007
    hotkey_id_f8 = 1008
    hotkey_id_f9 = 1009

    user32.RegisterHotKey(0, hotkey_id_f6, mod_norepeat, vk_f6)
    user32.RegisterHotKey(0, hotkey_id_f7, mod_norepeat, vk_f7)
    user32.RegisterHotKey(0, hotkey_id_f8, mod_norepeat, vk_f8)
    user32.RegisterHotKey(0, hotkey_id_f9, mod_norepeat, vk_f9)

    msg = ctypes.wintypes.MSG()
    while self.running:
      if user32.PeekMessageW(ctypes.byref(msg), 0, 0, 0, 1):  # PM_REMOVE
        if msg.message == 0x0312:  # WM_HOTKEY
          hk_id = msg.wParam
          if hk_id == hotkey_id_f6:
            self.f6_pressed.emit()
          elif hk_id == hotkey_id_f7:
            self.f7_pressed.emit()
          elif hk_id == hotkey_id_f8:
            self.f8_pressed.emit()
          elif hk_id == hotkey_id_f9:
            self.f9_pressed.emit()
        elif msg.message == 0x0012:  # WM_QUIT
          break
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))
      else:
        time.sleep(0.02)

    user32.UnregisterHotKey(0, hotkey_id_f6)
    user32.UnregisterHotKey(0, hotkey_id_f7)
    user32.UnregisterHotKey(0, hotkey_id_f8)
    user32.UnregisterHotKey(0, hotkey_id_f9)

  def stop(self) -> None:
    """Stops the hotkey message loop and notifies thread."""
    self.running = False
    if self.tid and sys.platform == "win32":
      ctypes.windll.user32.PostThreadMessageW(self.tid, 0x0012, 0, 0)
    self.wait(1000)
