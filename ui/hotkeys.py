"""Global hotkey listeners for Windows and macOS.

Complies with the Google Python Style Guide.
On Windows: Uses Win32 RegisterHotKey to listen globally without polling.
On macOS: Uses native Carbon RegisterEventHotKey to listen system-wide without requiring accessibility permissions.
Supports both standard function keys (F6~F9) and non-Fn keys (Ctrl+6~9, Ctrl+1~4).
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

    class EventHotKeyID(ctypes.Structure):
      _fields_ = [("signature", ctypes.c_uint32), ("id", ctypes.c_uint32)]

    class EventTypeSpec(ctypes.Structure):
      _fields_ = [("eventClass", ctypes.c_uint32), ("eventKind", ctypes.c_uint32)]

    EventHandlerProc = ctypes.CFUNCTYPE(
        ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p
    )

    def _event_handler(call_ref, event_ref, user_data):
      hk_id = EventHotKeyID()
      # kEventParamDirectObject = 'hkey' (0x686b6579), typeEventHotKeyID = 'hkey' (0x686b6579)
      status = self.carbon.GetEventParameter(
          event_ref,
          0x686B6579,
          0x686B6579,
          None,
          ctypes.sizeof(hk_id),
          None,
          ctypes.byref(hk_id),
      )
      if status == 0 and self.callback:
        self.callback(hk_id.id)
      return 0

    self._handler_proc = EventHandlerProc(_event_handler)
    target = self.carbon.GetApplicationEventTarget()

    event_type = EventTypeSpec()
    event_type.eventClass = 0x6B657962  # 'keyb' (kEventClassKeyboard)
    event_type.eventKind = 5  # kEventHotKeyPressed

    self.handler_ref = ctypes.c_void_p()
    res = self.carbon.InstallEventHandler(
        target,
        self._handler_proc,
        1,
        ctypes.byref(event_type),
        None,
        ctypes.byref(self.handler_ref),
    )
    if res != 0:
      logger.warning("Carbon InstallEventHandler returned status %d", res)
      return

    # Hotkey registrations: (action_id, keycode, modifiers)
    # macOS Virtual Keycodes:
    # F6: 97, F7: 98, F8: 100, F9: 101
    # 6: 22, 7: 26, 8: 28, 9: 25
    # 1: 18, 2: 19, 3: 20, 4: 21
    # Modifiers: 0 = none, 0x1000 = controlKey
    HOTKEY_REGISTRATIONS = [
        # F6 / Auto Start
        (1006, 97, 0),
        (1006, 22, 0x1000),  # Ctrl + 6
        (1006, 18, 0x1000),  # Ctrl + 1
        # F7 / Start/Pause
        (1007, 98, 0),
        (1007, 26, 0x1000),  # Ctrl + 7
        (1007, 19, 0x1000),  # Ctrl + 2
        # F8 / Reset
        (1008, 100, 0),
        (1008, 28, 0x1000),  # Ctrl + 8
        (1008, 20, 0x1000),  # Ctrl + 3
        # F9 / Game Mode
        (1009, 101, 0),
        (1009, 25, 0x1000),  # Ctrl + 9
        (1009, 21, 0x1000),  # Ctrl + 4
    ]

    for hk_action_id, keycode, mods in HOTKEY_REGISTRATIONS:
      hk_struct = EventHotKeyID(signature=0x4152544C, id=hk_action_id)
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

  def cleanup(self):
    if not self.carbon:
      return
    for ref in self.hotkey_refs:
      try:
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

    # Non-Fn: Ctrl+6..Ctrl+9
    user32.RegisterHotKey(0, 2006, mod_control | mod_norepeat, 0x36)
    user32.RegisterHotKey(0, 2007, mod_control | mod_norepeat, 0x37)
    user32.RegisterHotKey(0, 2008, mod_control | mod_norepeat, 0x38)
    user32.RegisterHotKey(0, 2009, mod_control | mod_norepeat, 0x39)

    # Non-Fn: Ctrl+1..Ctrl+4
    user32.RegisterHotKey(0, 3001, mod_control | mod_norepeat, 0x31)
    user32.RegisterHotKey(0, 3002, mod_control | mod_norepeat, 0x32)
    user32.RegisterHotKey(0, 3003, mod_control | mod_norepeat, 0x33)
    user32.RegisterHotKey(0, 3004, mod_control | mod_norepeat, 0x34)

    registered_ids = [
        1006, 1007, 1008, 1009,
        2006, 2007, 2008, 2009,
        3001, 3002, 3003, 3004,
    ]

    msg = ctypes.wintypes.MSG()
    while self.running:
      if user32.PeekMessageW(ctypes.byref(msg), 0, 0, 0, 1):  # PM_REMOVE
        if msg.message == 0x0312:  # WM_HOTKEY
          hk_id = msg.wParam
          if hk_id in (1006, 2006, 3001):
            self.f6_pressed.emit()
          elif hk_id in (1007, 2007, 3002):
            self.f7_pressed.emit()
          elif hk_id in (1008, 2008, 3003):
            self.f8_pressed.emit()
          elif hk_id in (1009, 2009, 3004):
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
