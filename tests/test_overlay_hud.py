"""Tests for ArtaleExpOverlay and GameModeSettingsDialog."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtWidgets import QApplication

from overlay_hud import (
    ALL_METRIC_KEYS,
    DEFAULT_GAME_MODE_KEYS,
    ArtaleExpOverlay,
    GameModeSettingsDialog,
)

# Shared QApplication for testing
app = QApplication.instance()
if app is None:
  app = QApplication(sys.argv)


class TestOverlayHud(unittest.TestCase):

  def setUp(self):
    self.overlay = ArtaleExpOverlay()
    self.overlay.show()

  def tearDown(self):
    self.overlay.close()

  def test_initial_full_mode(self):
    """Verify that full mode displays all 10 metrics with title visible."""
    self.assertFalse(self.overlay.is_game_mode)
    self.assertTrue(self.overlay.lbl_title.isVisible())
    self.assertEqual(self.overlay.width(), 340)

    # Check all 10 metric widgets are present and visible
    for key in ALL_METRIC_KEYS:
      self.assertTrue(
          self.overlay.metric_widgets[key].isVisible(),
          f"Expected {key} to be visible in full mode",
      )

  def test_game_mode_toggle_and_height_shrinkage(self):
    """Verify switching to game mode hides title and shrinks window height tightly."""
    full_height = self.overlay.size().height()

    # Toggle to Game Mode
    self.overlay.on_f9()
    self.assertTrue(self.overlay.is_game_mode)
    self.assertFalse(self.overlay.lbl_title.isVisible())
    self.assertEqual(self.overlay.width(), 290)

    game_height = self.overlay.size().height()
    self.assertLess(
        game_height,
        full_height,
        "Game mode height must be smaller than full mode height (zero empty slots)",
    )

    # Verify visible widgets match default game mode items
    for key in ALL_METRIC_KEYS:
      is_expected = key in DEFAULT_GAME_MODE_KEYS
      self.assertEqual(
          self.overlay.metric_widgets[key].isVisible(),
          is_expected,
          f"Visibility mismatch for {key} in game mode",
      )

    # Toggle back to Full Mode
    self.overlay.on_f9()
    self.assertFalse(self.overlay.is_game_mode)
    self.assertTrue(self.overlay.lbl_title.isVisible())
    self.assertEqual(self.overlay.width(), 340)
    self.assertEqual(self.overlay.size().height(), full_height)

  def test_custom_metric_ordering(self):
    """Verify user custom drag/order puts widgets in exact requested order."""
    custom_order = ["當前經驗", "EXP 進度條", "累計經驗", "練功時長"]
    self.overlay.is_game_mode = True
    self.overlay.game_mode_items = list(custom_order)
    self.overlay._apply_game_mode()

    # Check widgets in details_layout are exactly in custom_order
    layout_widgets = [
        self.overlay.details_layout.itemAt(i).widget()
        for i in range(self.overlay.details_layout.count())
    ]
    actual_order = []
    for w in layout_widgets:
      for k, v in self.overlay.metric_widgets.items():
        if v is w:
          actual_order.append(k)
          break

    self.assertEqual(actual_order, custom_order)

  def test_settings_dialog_reordering_and_defaults(self):
    """Verify GameModeSettingsDialog allows reordering and resetting defaults."""
    custom_order = ["當前經驗", "EXP 進度條", "累計經驗", "練功時長"]
    full_order = custom_order + [
        k for k in ALL_METRIC_KEYS if k not in custom_order
    ]

    dlg = GameModeSettingsDialog(full_order, custom_order)
    self.assertEqual(dlg.get_full_order(), full_order)
    self.assertEqual(dlg.get_ordered_items(), custom_order)

    # Move item 1 (EXP 進度條) up by 1 position
    dlg.list_widget.setCurrentRow(1)
    dlg._move_item(-1)
    self.assertEqual(
        dlg.get_ordered_items(),
        ["EXP 進度條", "當前經驗", "累計經驗", "練功時長"],
    )

    # Move item 0 down by 1 position
    dlg.list_widget.setCurrentRow(0)
    dlg._move_item(1)
    self.assertEqual(dlg.get_ordered_items(), custom_order)

    # Reset to defaults
    dlg._reset_defaults()
    self.assertEqual(dlg.get_full_order(), ALL_METRIC_KEYS)
    self.assertEqual(dlg.get_ordered_items(), DEFAULT_GAME_MODE_KEYS)


if __name__ == "__main__":
  unittest.main()
