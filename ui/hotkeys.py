"""Global hotkey listeners for Windows and macOS with customizable bindings.

Complies with the Google Python Style Guide.
On Windows: Uses Win32 RegisterHotKey to listen globally without polling.
On macOS: Uses native Carbon RegisterEventHotKey to listen system-wide without
requiring accessibility permissions, supplemented by pynput for arbitrary key sequences.
"""

import ctypes
import logging
import sys
import time
from typing import Dict, Optional, Set

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QKeySequence

import config

logger = logging.getLogger(__name__)

# Action ID constants
ACTION_AUTO_START_ID: int = 1006
ACTION_START_PAUSE_ID: int = 1007
ACTION_RESET_ID: int = 1008
ACTION_SWITCH_MODE_ID: int = 1009

ACTION_NAME_TO_ID: Dict[str, int] = {
    config.HOTKEY_AUTO_START: ACTION_AUTO_START_ID,
    config.HOTKEY_START_PAUSE: ACTION_START_PAUSE_ID,
    config.HOTKEY_RESET: ACTION_RESET_ID,
    config.HOTKEY_SWITCH_MODE: ACTION_SWITCH_MODE_ID,
}

ACTION_ID_TO_NAME: Dict[int, str] = {
    v: k for k, v in ACTION_NAME_TO_ID.items()
}

# macOS Virtual Key Code Mapping (HIToolbox Events.h)
MACOS_KEY_MAP: Dict[int, int] = {
    # Function keys (F1 ~ F12)
    16777264: 122,  # Key_F1
    16777265: 120,  # Key_F2
    16777266: 99,   # Key_F3
    16777267: 118,  # Key_F4
    16777268: 96,   # Key_F5
    16777269: 97,   # Key_F6
    16777270: 98,   # Key_F7
    16777271: 100,  # Key_F8
    16777272: 101,  # Key_F9
    16777273: 109,  # Key_F10
    16777274: 103,  # Key_F11
    16777275: 111,  # Key_F12
    # Number keys (0 ~ 9)
    48: 29,  # Key_0
    49: 18,  # Key_1
    50: 19,  # Key_2
    51: 20,  # Key_3
    52: 21,  # Key_4
    53: 23,  # Key_5
    54: 22,  # Key_6
    55: 26,  # Key_7
    56: 28,  # Key_8
    57: 25,  # Key_9
    # Letters (A ~ Z)
    65: 0,   # Key_A
    66: 11,  # Key_B
    67: 8,   # Key_C
    68: 2,   # Key_D
    69: 14,  # Key_E
    70: 3,   # Key_F
    71: 5,   # Key_G
    72: 4,   # Key_H
    73: 34,  # Key_I
    74: 38,  # Key_J
    75: 40,  # Key_K
    76: 37,  # Key_L
    77: 46,  # Key_M
    78: 45,  # Key_N
    79: 31,  # Key_O
    80: 35,  # Key_P
    81: 12,  # Key_Q
    82: 15,  # Key_R
    83: 1,   # Key_S
    84: 17,  # Key_T
    85: 32,  # Key_U
    86: 9,   # Key_V
    87: 13,  # Key_W
    88: 7,   # Key_X
    89: 16,  # Key_Y
    90: 6,   # Key_Z
    # Common keys
    32: 49,        # Key_Space
    16777220: 36,  # Key_Return
    16777221: 76,  # Key_Enter
    16777217: 48,  # Key_Tab
    16777216: 53,  # Key_Escape
}

# Win32 Virtual Key Mapping
WIN32_EXTRA_KEYS: Dict[int, int] = {
    32: 0x20,        # Space
    16777220: 0x0D,  # Return
    16777221: 0x0D,  # Enter
    16777217: 0x09,  # Tab
    16777216: 0x1B,  # Escape
}


def parse_key_sequence(seq_str: str) -> Optional[dict]:
  """Parses a portable Qt sequence string into platform key codes and modifiers."""
  if not seq_str:
    return None
  seq = QKeySequence(seq_str)
  if seq.isEmpty():
    return None

  val = seq[0].toCombined() if hasattr(seq[0], "toCombined") else int(seq[0])
  qt_key = val & 0x01FFFFFF
  qt_mods = val & ~0x01FFFFFF

  # Win32 Modifiers
  win_mod = 0
  if qt_mods & Qt.KeyboardModifier.AltModifier.value:
    win_mod |= 0x0001
  if qt_mods & Qt.KeyboardModifier.ControlModifier.value:
    win_mod |= 0x0002
  if qt_mods & Qt.KeyboardModifier.ShiftModifier.value:
    win_mod |= 0x0004
  if qt_mods & Qt.KeyboardModifier.MetaModifier.value:
    win_mod |= 0x0008

  # Win32 Virtual Key Code
  win_vk = None
  if Qt.Key.Key_F1.value <= qt_key <= Qt.Key.Key_F24.value:
    win_vk = 0x70 + (qt_key - Qt.Key.Key_F1.value)
  elif Qt.Key.Key_0.value <= qt_key <= Qt.Key.Key_9.value:
    win_vk = qt_key
  elif Qt.Key.Key_A.value <= qt_key <= Qt.Key.Key_Z.value:
    win_vk = qt_key
  elif qt_key in WIN32_EXTRA_KEYS:
    win_vk = WIN32_EXTRA_KEYS[qt_key]

  # macOS Carbon Modifiers
  mac_mod = 0
  if qt_mods & Qt.KeyboardModifier.AltModifier.value:
    mac_mod |= 0x0800  # optionKey
  if qt_mods & Qt.KeyboardModifier.ControlModifier.value:
    mac_mod |= 0x1000  # controlKey
  if qt_mods & Qt.KeyboardModifier.ShiftModifier.value:
    mac_mod |= 0x0200  # shiftKey
  if qt_mods & Qt.KeyboardModifier.MetaModifier.value:
    mac_mod |= 0x0100  # cmdKey

  mac_vk = MACOS_KEY_MAP.get(qt_key, None)

  return {
      "qt_key": qt_key,
      "qt_mods": qt_mods,
      "win_vk": win_vk,
      "win_mod": win_mod,
      "mac_vk": mac_vk,
      "mac_mod": mac_mod,
      "raw": seq_str,
  }


def check_macos_accessibility(prompt: bool = False) -> bool:
  """Checks whether macOS Accessibility permissions are granted, optionally prompting."""
  if sys.platform != "darwin":
    return True
  try:
    as_lib = ctypes.cdll.LoadLibrary(
        "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
    )
    as_lib.AXIsProcessTrusted.restype = ctypes.c_bool
    as_lib.AXIsProcessTrusted.argtypes = []
    trusted = as_lib.AXIsProcessTrusted()
    logger.info("[HOTKEY] macOS AXIsProcessTrusted = %s", trusted)
    if not trusted and prompt:
      cf_lib = ctypes.cdll.LoadLibrary(
          "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
      )
      as_lib.AXIsProcessTrustedWithOptions.restype = ctypes.c_bool
      as_lib.AXIsProcessTrustedWithOptions.argtypes = [ctypes.c_void_p]

      cf_lib.CFStringCreateWithCString.restype = ctypes.c_void_p
      cf_lib.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
      k_key = cf_lib.CFStringCreateWithCString(None, b"AXTrustedCheckOptionPrompt", 0x08000100)
      k_val = ctypes.c_void_p.in_dll(cf_lib, "kCFBooleanTrue")

      cf_lib.CFDictionaryCreate.restype = ctypes.c_void_p
      cf_lib.CFDictionaryCreate.argtypes = [
          ctypes.c_void_p,
          ctypes.POINTER(ctypes.c_void_p),
          ctypes.POINTER(ctypes.c_void_p),
          ctypes.c_long,
          ctypes.c_void_p,
          ctypes.c_void_p,
      ]
      keys = (ctypes.c_void_p * 1)(k_key)
      vals = (ctypes.c_void_p * 1)(k_val.value)
      options = cf_lib.CFDictionaryCreate(None, keys, vals, 1, None, None)
      as_lib.AXIsProcessTrustedWithOptions(options)
      logger.info("[HOTKEY] Prompted user for macOS Accessibility permissions")
    return trusted
  except Exception as e:
    logger.warning("[HOTKEY] Failed checking macOS accessibility: %s", e)
    return False


class MacOSCarbonHotkeys:
  """Registers system-wide hotkeys on macOS via Carbon framework without accessibility requirements."""

  def __init__(self, callback):
    self.callback = callback
    self.carbon = None
    self._handler_proc = None
    self.handler_ref = None
    self.hotkey_refs = []
    self.action_map: Dict[int, int] = {}
    self.action_name_map: Dict[int, str] = {}
    self.EventHotKeyID = None
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
      self.EventHotKeyID = EventHotKeyID

      class EventTypeSpec(ctypes.Structure):
        _fields_ = [("eventClass", ctypes.c_uint32), ("eventKind", ctypes.c_uint32)]

      EventHandlerProc = ctypes.CFUNCTYPE(
          ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p
      )

      # Explicit 64-bit signatures
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
            action_name = self.action_name_map.get(hk_id.id, ACTION_ID_TO_NAME.get(action_id, ""))
            logger.info(
                "[CARBON] Global hotkey triggered: reg_id=%d -> action=%s (id=%d)",
                hk_id.id,
                action_name,
                action_id,
            )
            if self.callback:
              self.callback(action_name or action_id)
        except Exception as e:
          logger.exception("Error in Carbon event handler: %s", e)
        return 0

      self._handler_proc = EventHandlerProc(_event_handler)
      event_type = EventTypeSpec()
      event_type.eventClass = 0x6B657962  # 'keyb'
      event_type.eventKind = 5  # kEventHotKeyPressed

      self.handler_ref = ctypes.c_void_p()
      target = self.carbon.GetApplicationEventTarget()
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
      logger.info("[CARBON] Installed event handler: status=%d", res)

      # Initial registration with default bindings
      self.update_hotkeys(config.DEFAULT_HOTKEYS)
    except Exception as e:
      logger.warning("Error initializing Carbon hotkeys on macOS: %s", e)

  def update_hotkeys(self, hotkeys_dict: Dict[str, str]) -> None:
    """Updates registered Carbon hotkeys to match current user preferences."""
    if not self.carbon or not self.EventHotKeyID:
      return

    # Unregister existing hotkeys
    for ref in self.hotkey_refs:
      try:
        if ref and ref.value:
          self.carbon.UnregisterEventHotKey(ref)
      except Exception:
        pass
    self.hotkey_refs.clear()
    self.action_map.clear()
    self.action_name_map.clear()

    target = self.carbon.GetApplicationEventTarget()
    reg_id = 1

    for action_name, action_id in ACTION_NAME_TO_ID.items():
      seq_str = hotkeys_dict.get(action_name, config.DEFAULT_HOTKEYS.get(action_name, ""))
      spec = parse_key_sequence(seq_str)
      if not spec or spec["mac_vk"] is None:
        continue

      mac_vk = spec["mac_vk"]
      mac_mod = spec["mac_mod"]

      self.action_map[reg_id] = action_id
      self.action_name_map[reg_id] = action_name

      hk_struct = self.EventHotKeyID(signature=0x4152544C, id=reg_id)
      ref = ctypes.c_void_p()
      res = self.carbon.RegisterEventHotKey(
          mac_vk,
          mac_mod,
          hk_struct,
          target,
          0,
          ctypes.byref(ref),
      )
      if res == 0 and ref.value:
        self.hotkey_refs.append(ref)
        logger.info(
            "[CARBON] Registered hotkey: '%s' for action '%s' (reg_id=%d, vk=%d, mods=0x%04X)",
            seq_str,
            action_name,
            reg_id,
            mac_vk,
            mac_mod,
        )
      else:
        logger.warning(
            "[CARBON] RegisterEventHotKey '%s' returned status %d",
            seq_str,
            res,
        )
      reg_id += 1

  def cleanup(self) -> None:
    """Unregisters all Carbon hotkeys and removes application event handler."""
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
  """Cross-platform global hotkey listener supporting dynamic user-defined bindings."""

  # High-level action signals
  hotkey_triggered = pyqtSignal(str)

  # Backward compatibility signals for F6~F9
  f6_pressed = pyqtSignal()
  f7_pressed = pyqtSignal()
  f8_pressed = pyqtSignal()
  f9_pressed = pyqtSignal()

  def __init__(self, initial_hotkeys: Optional[Dict[str, str]] = None):
    super().__init__()
    self.running: bool = True
    self.tid: int = 0
    self.hotkeys_dict: Dict[str, str] = dict(config.DEFAULT_HOTKEYS)
    if initial_hotkeys:
      self.hotkeys_dict.update(initial_hotkeys)

    self._last_trigger_times: Dict[str, float] = {}
    self.registered_win_ids: Dict[int, str] = {}
    self.reload_requested: bool = False

    self.macos_hotkeys: Optional[MacOSCarbonHotkeys] = None
    self.pynput_listener = None
    self._current_modifiers: Set[str] = set()

    if sys.platform == "darwin":
      self.macos_hotkeys = MacOSCarbonHotkeys(self._on_hotkey_action)
      self._setup_pynput()

  def update_hotkeys(self, new_hotkeys: Dict[str, str]) -> None:
    """Dynamically applies newly configured hotkeys at runtime."""
    self.hotkeys_dict.update(new_hotkeys)
    logger.info("[HOTKEY] Updating active hotkeys: %s", self.hotkeys_dict)

    if sys.platform == "darwin":
      if self.macos_hotkeys:
        self.macos_hotkeys.update_hotkeys(self.hotkeys_dict)
    elif sys.platform == "win32":
      self.reload_requested = True
      if self.tid:
        try:
          import ctypes
          ctypes.windll.user32.PostThreadMessageW(self.tid, 0x0000, 0, 0)  # WM_NULL
        except Exception:
          pass

  def _setup_pynput(self) -> None:
    """Sets up cross-application global key listener via pynput."""
    try:
      from pynput import keyboard

      def on_press(key):
        try:
          # Track modifiers
          if key in (keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r):
            self._current_modifiers.add("alt")
            return
          elif key in (keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r):
            self._current_modifiers.add("ctrl")
            return
          elif key in (keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r):
            self._current_modifiers.add("shift")
            return
          elif key in (keyboard.Key.cmd, keyboard.Key.cmd_l, keyboard.Key.cmd_r):
            self._current_modifiers.add("cmd")
            return

          # Resolve key name
          key_name = ""
          if hasattr(key, "name") and key.name:
            key_name = key.name
          elif hasattr(key, "char") and key.char:
            key_name = key.char

          if not key_name:
            return

          # Build current sequence string
          parts = []
          if "ctrl" in self._current_modifiers:
            parts.append("Ctrl")
          if "alt" in self._current_modifiers:
            parts.append("Alt")
          if "shift" in self._current_modifiers:
            parts.append("Shift")
          if "cmd" in self._current_modifiers:
            parts.append("Meta")
          parts.append(key_name.upper() if len(key_name) == 1 else key_name.capitalize())
          pressed_seq_str = "+".join(parts)
          pressed_seq = QKeySequence(pressed_seq_str)

          # Match against configured hotkeys
          for action_name, action_seq_str in self.hotkeys_dict.items():
            if not action_seq_str:
              continue
            action_seq = QKeySequence(action_seq_str)
            if action_seq.matches(pressed_seq) == QKeySequence.SequenceMatch.ExactMatch:
              self._on_hotkey_action(action_name)
              break

        except Exception as e:
          logger.debug("[HOTKEY] Error in pynput on_press: %s", e)

      def on_release(key):
        try:
          if key in (keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r):
            self._current_modifiers.discard("alt")
          elif key in (keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r):
            self._current_modifiers.discard("ctrl")
          elif key in (keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r):
            self._current_modifiers.discard("shift")
          elif key in (keyboard.Key.cmd, keyboard.Key.cmd_l, keyboard.Key.cmd_r):
            self._current_modifiers.discard("cmd")
        except Exception:
          pass

      self.pynput_listener = keyboard.Listener(on_press=on_press, on_release=on_release)
      self.pynput_listener.daemon = True
      self.pynput_listener.start()
      logger.info("[HOTKEY] macOS global keyboard listener (pynput) started")
    except Exception as e:
      logger.warning("[HOTKEY] Could not initialize pynput keyboard listener on macOS: %s", e)

  def _on_hotkey_action(self, action: str) -> None:
    """Dispatches action with a 150ms debounce window."""
    now = time.time()
    if now - self._last_trigger_times.get(action, 0) < 0.15:
      return
    self._last_trigger_times[action] = now
    logger.info("[HOTKEY] Triggered action: %s", action)
    self.hotkey_triggered.emit(action)

    if action == config.HOTKEY_AUTO_START or action == ACTION_AUTO_START_ID:
      self.f6_pressed.emit()
    elif action == config.HOTKEY_START_PAUSE or action == ACTION_START_PAUSE_ID:
      self.f7_pressed.emit()
    elif action == config.HOTKEY_RESET or action == ACTION_RESET_ID:
      self.f8_pressed.emit()
    elif action == config.HOTKEY_SWITCH_MODE or action == ACTION_SWITCH_MODE_ID:
      self.f9_pressed.emit()

  def run(self) -> None:
    """Executes the Win32 message pump for registered hotkeys (on Windows)."""
    if sys.platform != "win32":
      while self.running:
        time.sleep(0.1)
      return

    import ctypes.wintypes
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    self.tid = kernel32.GetCurrentThreadId()

    mod_norepeat = 0x4000
    self._register_win32_hotkeys()

    msg = ctypes.wintypes.MSG()
    while self.running:
      if self.reload_requested:
        self.reload_requested = False
        self._unregister_win32_hotkeys()
        self._register_win32_hotkeys()

      if user32.PeekMessageW(ctypes.byref(msg), 0, 0, 0, 1):  # PM_REMOVE
        if msg.message == 0x0312:  # WM_HOTKEY
          hk_id = msg.wParam
          action_name = self.registered_win_ids.get(hk_id, "")
          if action_name:
            self._on_hotkey_action(action_name)
        elif msg.message == 0x0012:  # WM_QUIT
          break
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))
      else:
        time.sleep(0.02)

    self._unregister_win32_hotkeys()

  def _register_win32_hotkeys(self) -> None:
    if sys.platform != "win32":
      return
    import ctypes
    user32 = ctypes.windll.user32
    mod_norepeat = 0x4000

    self.registered_win_ids.clear()
    reg_id = 1000

    for action_name in [
        config.HOTKEY_AUTO_START,
        config.HOTKEY_START_PAUSE,
        config.HOTKEY_RESET,
        config.HOTKEY_SWITCH_MODE,
    ]:
      seq_str = self.hotkeys_dict.get(action_name, "")
      spec = parse_key_sequence(seq_str)
      if spec and spec["win_vk"] is not None:
        reg_id += 1
        res = user32.RegisterHotKey(
            0, reg_id, mod_norepeat | spec["win_mod"], spec["win_vk"]
        )
        if res:
          self.registered_win_ids[reg_id] = action_name
          logger.info(
              "[HOTKEY] Registered Win32 hotkey '%s' for '%s' (id=%d)",
              seq_str,
              action_name,
              reg_id,
          )
        else:
          logger.warning(
              "[HOTKEY] Win32 RegisterHotKey '%s' failed for '%s'",
              seq_str,
              action_name,
          )

  def _unregister_win32_hotkeys(self) -> None:
    if sys.platform != "win32":
      return
    import ctypes
    user32 = ctypes.windll.user32
    for reg_id in list(self.registered_win_ids.keys()):
      try:
        user32.UnregisterHotKey(0, reg_id)
      except Exception:
        pass
    self.registered_win_ids.clear()

  def stop(self) -> None:
    """Stops the hotkey message loop and cleans up active hooks."""
    self.running = False
    if self.pynput_listener:
      try:
        self.pynput_listener.stop()
      except Exception:
        pass
      self.pynput_listener = None

    if self.macos_hotkeys:
      self.macos_hotkeys.cleanup()
      self.macos_hotkeys = None

    if self.tid and sys.platform == "win32":
      try:
        ctypes.windll.user32.PostThreadMessageW(self.tid, 0x0012, 0, 0)  # WM_QUIT
      except Exception:
        pass
    self.wait(1000)
