"""Global hotkey listeners for Windows and macOS.

Complies with the Google Python Style Guide.
On Windows: Uses Win32 RegisterHotKey to listen globally without polling.
On macOS: Uses native Carbon RegisterEventHotKey to listen system-wide without requiring accessibility permissions.
Supports standard function keys (F6~F9 on Windows, Fn+F6~F9 on macOS).
"""

import ctypes
import logging
import sys
import time
from typing import Optional
from PyQt6.QtCore import QThread, pyqtSignal

logger = logging.getLogger(__name__)


class MacOSCarbonHotkeys:
  """Registers system-wide hotkeys on macOS via Carbon framework."""

  def __init__(self, callback):
    self.callback = callback
    self.carbon = None
    self._handler_proc = None
    self.handler_ref = None
    self.hotkey_refs = []
    self.action_map = {}
    self._setup()

  def _setup(self):
    if sys.platform != "darwin":
      return
    try:
      self.carbon = ctypes.cdll.LoadLibrary(
          "/System/Library/Frameworks/Carbon.framework/Carbon"
      )
    except Exception as e:
      logger.warning("Could not load Carbon framework: %s", e)
      return

    try:
      class EventHotKeyID(ctypes.Structure):
        _fields_ = [("signature", ctypes.c_uint32), ("id", ctypes.c_uint32)]

      class EventTypeSpec(ctypes.Structure):
        _fields_ = [("eventClass", ctypes.c_uint32), ("eventKind", ctypes.c_uint32)]

      EventHandlerProc = ctypes.CFUNCTYPE(
          ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p
      )

      # Explicit 64-bit signatures to prevent pointer truncation and SIGSEGV on Apple Silicon / macOS
      self.carbon.GetApplicationEventTarget.restype = ctypes.c_void_p
      self.carbon.GetApplicationEventTarget.argtypes = []

      if hasattr(self.carbon, "InstallApplicationEventHandler"):
        self.carbon.InstallApplicationEventHandler.restype = ctypes.c_int32
        self.carbon.InstallApplicationEventHandler.argtypes = [
            EventHandlerProc,
            ctypes.c_uint32,
            ctypes.POINTER(EventTypeSpec),
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
        ]

      self.carbon.InstallEventHandler.restype = ctypes.c_int32
      self.carbon.InstallEventHandler.argtypes = [
          ctypes.c_void_p,
          EventHandlerProc,
          ctypes.c_uint32,
          ctypes.POINTER(EventTypeSpec),
          ctypes.c_void_p,
          ctypes.POINTER(ctypes.c_void_p),
      ]

      self.carbon.GetEventParameter.restype = ctypes.c_int32
      self.carbon.GetEventParameter.argtypes = [
          ctypes.c_void_p,
          ctypes.c_uint32,
          ctypes.c_uint32,
          ctypes.c_void_p,
          ctypes.c_size_t,
          ctypes.c_void_p,
          ctypes.c_void_p,
      ]

      self.carbon.RegisterEventHotKey.restype = ctypes.c_int32
      self.carbon.RegisterEventHotKey.argtypes = [
          ctypes.c_uint32,
          ctypes.c_uint32,
          EventHotKeyID,
          ctypes.c_void_p,
          ctypes.c_uint32,
          ctypes.POINTER(ctypes.c_void_p),
      ]

      self.carbon.UnregisterEventHotKey.restype = ctypes.c_int32
      self.carbon.UnregisterEventHotKey.argtypes = [ctypes.c_void_p]

      self.carbon.RemoveEventHandler.restype = ctypes.c_int32
      self.carbon.RemoveEventHandler.argtypes = [ctypes.c_void_p]

      def _event_handler(call_ref, event_ref, user_data):
        try:
          hk_id = EventHotKeyID()
          # Carbon Event Manager:
          # kEventParamDirectObject = '----' (0x2D2D2D2D)
          # typeEventHotKeyID = 'hkey' (0x686B6579)
          status = self.carbon.GetEventParameter(
              event_ref,
              0x2D2D2D2D,  # kEventParamDirectObject
              0x686B6579,  # typeEventHotKeyID
              None,
              ctypes.sizeof(hk_id),
              None,
              ctypes.byref(hk_id),
          )
          if status == 0:
            action_id = self.action_map.get(hk_id.id, hk_id.id)
            logger.info(
                "Carbon global hotkey triggered: reg_id=%d -> action=%d",
                hk_id.id,
                action_id,
            )
            if self.callback:
              self.callback(action_id)
          else:
            logger.debug("Carbon GetEventParameter status=%d", status)
        except Exception as e:
          logger.exception("Error in Carbon event handler: %s", e)
        return 0

      self._handler_proc = EventHandlerProc(_event_handler)
      target = self.carbon.GetApplicationEventTarget()
      if not target:
        logger.warning("Carbon GetApplicationEventTarget returned NULL")
        return

      event_type = EventTypeSpec()
      event_type.eventClass = 0x6B657962  # 'keyb' (kEventClassKeyboard)
      event_type.eventKind = 5  # kEventHotKeyPressed

      self.handler_ref = ctypes.c_void_p()
      if hasattr(self.carbon, "InstallApplicationEventHandler"):
        res = self.carbon.InstallApplicationEventHandler(
            self._handler_proc,
            1,
            ctypes.byref(event_type),
            None,
            ctypes.byref(self.handler_ref),
        )
      else:
        res = self.carbon.InstallEventHandler(
            target,
            self._handler_proc,
            1,
            ctypes.byref(event_type),
            None,
            ctypes.byref(self.handler_ref),
        )

      if res != 0:
        logger.warning("Carbon InstallApplicationEventHandler returned status %d", res)
        return

      # Keycodes: F6: 97, F7: 98, F8: 100, F9: 101
      HOTKEY_SPECS = [
          (1006, 97, 0, "F6 / Fn+F6"),
          (1007, 98, 0, "F7 / Fn+F7"),
          (1008, 100, 0, "F8 / Fn+F8"),
          (1009, 101, 0, "F9 / Fn+F9"),
      ]

      self.action_map.clear()
      reg_id = 1
      for action_id, keycode, mods, desc in HOTKEY_SPECS:
        self.action_map[reg_id] = action_id
        hk_struct = EventHotKeyID(signature=0x4152544C, id=reg_id)
        ref = ctypes.c_void_p()
        res = self.carbon.RegisterEventHotKey(
            keycode,
            mods,
            hk_struct,
            target,
            0,
            ctypes.byref(ref),
        )
        if res == 0 and ref.value:
          self.hotkey_refs.append(ref)
          logger.info("Registered macOS global hotkey: %s (id=%d)", desc, reg_id)
        else:
          logger.debug("Carbon RegisterEventHotKey %s returned status %d", desc, res)
        reg_id += 1
    except Exception as e:
      logger.warning("Error initializing Carbon hotkeys on macOS: %s", e)

  def cleanup(self):
    if not self.carbon:
      return
    for ref in self.hotkey_refs:
      try:
        if ref and ref.value:
          self.carbon.UnregisterEventHotKey(ref)
      except Exception:
        pass
    self.hotkey_refs.clear()
    if self.handler_ref and self.handler_ref.value:
      try:
        self.carbon.RemoveEventHandler(self.handler_ref)
      except Exception:
        pass


class HotkeyWorker(QThread):
  """Global hotkey listener for F6 (Auto Start), F7 (Start/Pause), F8 (Reset), F9 (Game Mode)."""

  f6_pressed = pyqtSignal()
  f7_pressed = pyqtSignal()
  f8_pressed = pyqtSignal()
  f9_pressed = pyqtSignal()

  def __init__(self):
    super().__init__()
    self.running: bool = True
    self.tid: int = 0
    self.macos_hotkeys: Optional[MacOSCarbonHotkeys] = None
    if sys.platform == "darwin":
      self.macos_hotkeys = MacOSCarbonHotkeys(self._on_macos_hotkey)

  def _on_macos_hotkey(self, action_id: int) -> None:
    if action_id == 1006:
      self.f6_pressed.emit()
    elif action_id == 1007:
      self.f7_pressed.emit()
    elif action_id == 1008:
      self.f8_pressed.emit()
    elif action_id == 1009:
      self.f9_pressed.emit()

  def run(self) -> None:
    """Executes the Win32 message pump for registered hotkeys (on Windows)."""
    if sys.platform != "win32":
      # On macOS, events are pumped by main runloop via Carbon
      while self.running:
        time.sleep(0.1)
      return

    import ctypes.wintypes
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    self.tid = kernel32.GetCurrentThreadId()

    mod_norepeat = 0x4000
    mod_control = 0x0002

    # Standard F6-F9
    user32.RegisterHotKey(0, 1006, mod_norepeat, 0x75)
    user32.RegisterHotKey(0, 1007, mod_norepeat, 0x76)
    user32.RegisterHotKey(0, 1008, mod_norepeat, 0x77)
    user32.RegisterHotKey(0, 1009, mod_norepeat, 0x78)

    registered_ids = [1006, 1007, 1008, 1009]

    msg = ctypes.wintypes.MSG()
    while self.running:
      if user32.PeekMessageW(ctypes.byref(msg), 0, 0, 0, 1):  # PM_REMOVE
        if msg.message == 0x0312:  # WM_HOTKEY
          hk_id = msg.wParam
          if hk_id == 1006:
            self.f6_pressed.emit()
          elif hk_id == 1007:
            self.f7_pressed.emit()
          elif hk_id == 1008:
            self.f8_pressed.emit()
          elif hk_id == 1009:
            self.f9_pressed.emit()
        elif msg.message == 0x0012:  # WM_QUIT
          break
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))
      else:
        time.sleep(0.02)

    for hk_id in registered_ids:
      user32.UnregisterHotKey(0, hk_id)

  def stop(self) -> None:
    """Stops the hotkey message loop and notifies thread."""
    self.running = False
    if self.macos_hotkeys:
      self.macos_hotkeys.cleanup()
      self.macos_hotkeys = None
    if self.tid and sys.platform == "win32":
      ctypes.windll.user32.PostThreadMessageW(self.tid, 0x0012, 0, 0)
    self.wait(1000)
