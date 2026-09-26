"""Unit tests for HotkeySettingsDialog and dynamic custom hotkeys.

Complies with the Google Python Style Guide.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import QApplication, QDialog

import config
from ui.dialogs import HotkeySettingsDialog
from ui.hotkeys import HotkeyWorker, parse_key_sequence

# Ensure single QApplication
_app = QApplication.instance() or QApplication(sys.argv)


class TestHotkeySettings(unittest.TestCase):
  """Tests for custom hotkey configuration dialog and parsing."""

  def test_parse_key_sequence(self):
    """Verifies parsing of standard, modifier-based, and empty key sequences."""
    # Empty
    self.assertIsNone(parse_key_sequence(""))

    # F6
    f6_spec = parse_key_sequence("F6")
    self.assertIsNotNone(f6_spec)
    self.assertEqual(f6_spec["win_vk"], 0x75)
    self.assertEqual(f6_spec["mac_vk"], 97)
    self.assertEqual(f6_spec["win_mod"], 0)
    self.assertEqual(f6_spec["mac_mod"], 0)

    # Alt+F6 (Option+F6)
    alt_f6 = parse_key_sequence("Alt+F6")
    self.assertIsNotNone(alt_f6)
    self.assertEqual(alt_f6["win_vk"], 0x75)
    self.assertEqual(alt_f6["mac_vk"], 97)
    self.assertEqual(alt_f6["win_mod"], 0x0001)  # MOD_ALT
    self.assertEqual(alt_f6["mac_mod"], 0x0800)  # optionKey

    # Ctrl+1
    ctrl_1 = parse_key_sequence("Ctrl+1")
    self.assertIsNotNone(ctrl_1)
    self.assertEqual(ctrl_1["win_vk"], 0x31)
    self.assertEqual(ctrl_1["mac_vk"], 18)
    self.assertEqual(ctrl_1["win_mod"], 0x0002)  # MOD_CONTROL
    self.assertEqual(ctrl_1["mac_mod"], 0x1000)  # controlKey

  def test_hotkey_settings_dialog_init_and_get(self):
    """Verifies that HotkeySettingsDialog initializes with active settings and returns updated values."""
    custom = {
        config.HOTKEY_AUTO_START: "Ctrl+1",
        config.HOTKEY_START_PAUSE: "Ctrl+2",
        config.HOTKEY_RESET: "Ctrl+3",
        config.HOTKEY_SWITCH_MODE: "Ctrl+4",
    }
    dlg = HotkeySettingsDialog(custom)
    self.assertEqual(dlg.edits[config.HOTKEY_AUTO_START].keySequence().toString(), "Ctrl+1")
    self.assertEqual(dlg.edits[config.HOTKEY_START_PAUSE].keySequence().toString(), "Ctrl+2")

    # Clear one action
    dlg.edits[config.HOTKEY_RESET].clear()
    res = dlg.get_hotkeys()
    self.assertEqual(res[config.HOTKEY_AUTO_START], "Ctrl+1")
    self.assertEqual(res[config.HOTKEY_RESET], "")

    # Reset all defaults
    dlg._reset_all_defaults()
    defaults = dlg.get_hotkeys()
    self.assertEqual(defaults[config.HOTKEY_AUTO_START], config.DEFAULT_HOTKEYS[config.HOTKEY_AUTO_START])

  def test_hotkey_worker_dynamic_update(self):
    """Verifies that HotkeyWorker accepts dynamic updates."""
    worker = HotkeyWorker()
    worker.update_hotkeys({config.HOTKEY_AUTO_START: "Ctrl+F6"})
    self.assertEqual(worker.hotkeys_dict[config.HOTKEY_AUTO_START], "Ctrl+F6")


if __name__ == "__main__":
  unittest.main()
