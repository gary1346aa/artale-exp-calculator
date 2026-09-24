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
    get_accum_exp_color,
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

  def test_eta_displays_dash_when_not_measuring(self):
    """Verify that 升級預估時間 shows '-' instead of '待機中' when not measuring."""
    m = self.overlay.engine.get_metrics()
    self.assertEqual(m["升級預估時間"], "-")
    self.overlay._refresh_ui()
    self.assertEqual(self.overlay.row_eta.lbl_value.text(), "-")

  def test_full_mode_honors_custom_order(self):
    """Verify that changing metric order also affects Full Mode layout."""
    custom_order = [
        "當前經驗",
        "EXP 進度條",
        "累計經驗",
        "升級預估時間",
        "練功時長",
        "1分鐘經驗",
        "預估10分",
        "累積10分",
        "預估60分",
        "累積60分",
    ]
    self.overlay.is_game_mode = False
    self.overlay.game_mode_order = list(custom_order)
    self.overlay._apply_game_mode()

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

  def test_focus_sliders_and_collapse(self):
    """Verify size scale & opacity sliders show/hide and window collapses without residual space."""
    # Initially hidden and compact
    self.assertFalse(self.overlay.slider_panel.isVisible())
    h_collapsed = self.overlay.height()

    # When window gains focus / sliders shown
    self.overlay._set_sliders_visible(True)
    self.assertTrue(self.overlay.slider_panel.isVisible())
    h_expanded = self.overlay.height()
    self.assertGreater(h_expanded, h_collapsed)

    # When focus is lost, area collapses back cleanly
    self.overlay._set_sliders_visible(False)
    self.assertFalse(self.overlay.slider_panel.isVisible())
    self.assertEqual(self.overlay.height(), h_collapsed)

    # Same collapse behavior in Game Mode
    self.overlay.on_f9()  # switch to Game Mode
    h_gm_collapsed = self.overlay.height()
    self.overlay._set_sliders_visible(True)
    self.assertGreater(self.overlay.height(), h_gm_collapsed)
    self.overlay._set_sliders_visible(False)
    self.assertEqual(self.overlay.height(), h_gm_collapsed)

    # Test scale slider functionality (50% to 200%)
    self.assertEqual(self.overlay.slider_scale.minimum(), 50)
    self.assertEqual(self.overlay.slider_scale.maximum(), 200)
    self.overlay.slider_scale.setValue(50)
    self.assertAlmostEqual(self.overlay.ui_scale, 0.5)
    self.assertEqual(self.overlay.lbl_scale_val.text(), "50%")
    self.overlay.slider_scale.setValue(200)
    self.assertAlmostEqual(self.overlay.ui_scale, 2.0)
    self.assertEqual(self.overlay.lbl_scale_val.text(), "200%")

    # Test transparency slider functionality (0% to 80%, reversed to window opacity)
    self.assertEqual(self.overlay.slider_opacity.minimum(), 0)
    self.assertEqual(self.overlay.slider_opacity.maximum(), 80)
    self.overlay.slider_opacity.setValue(20)
    self.assertAlmostEqual(self.overlay.opacity_val, 0.8)
    self.assertEqual(self.overlay.lbl_opacity_val.text(), "20%")
    self.assertAlmostEqual(self.overlay.windowOpacity(), 0.8)
    self.overlay.slider_opacity.setValue(0)
    self.assertAlmostEqual(self.overlay.opacity_val, 1.0)
    self.assertEqual(self.overlay.lbl_opacity_val.text(), "0%")
    self.assertAlmostEqual(self.overlay.windowOpacity(), 1.0)

  def test_game_mode_focus_header_footer_hidden(self):
    """Verify that in game mode, header bar and footer hotkey hint hide when not focused."""
    self.overlay.on_f9()  # Enter Game Mode
    self.assertTrue(self.overlay.is_game_mode)

    # When unfocused: header, footer, and sliders must be hidden
    self.overlay._update_focus_visibility()
    if not self.overlay.isActiveWindow():
      self.assertFalse(self.overlay.header_widget.isVisible())
      self.assertFalse(self.overlay.lbl_hotkey_hint.isVisible())
      self.assertFalse(self.overlay.slider_panel.isVisible())

    # In Full Mode, header and footer are always visible even when unfocused
    self.overlay.on_f9()  # Switch back to Full Mode
    self.assertFalse(self.overlay.is_game_mode)
    self.assertTrue(self.overlay.header_widget.isVisible())
    self.assertTrue(self.overlay.lbl_hotkey_hint.isVisible())

  def test_accum_exp_color_tiers_and_other_metrics_uncolored(self):
    """Verify that only 累計經驗 has dynamic colors across 7 tiers, and other metrics are uncolored."""
    # 7 Tiers check for get_accum_exp_color
    self.assertEqual(get_accum_exp_color(0), "#FFFFFF")
    self.assertEqual(get_accum_exp_color(19_999_999), "#FFFFFF")
    self.assertEqual(get_accum_exp_color(20_000_000), "#FFCC00")
    self.assertEqual(get_accum_exp_color(39_999_999), "#FFCC00")
    self.assertEqual(get_accum_exp_color(40_000_000), "#66CCFF")
    self.assertEqual(get_accum_exp_color(59_999_999), "#66CCFF")
    self.assertEqual(get_accum_exp_color(60_000_000), "#FF80FF")
    self.assertEqual(get_accum_exp_color(79_999_999), "#FF80FF")
    self.assertEqual(get_accum_exp_color(80_000_000), "#FFFF66")
    self.assertEqual(get_accum_exp_color(99_999_999), "#FFFF66")
    self.assertEqual(get_accum_exp_color(100_000_000), "#66FF00")
    self.assertEqual(get_accum_exp_color(119_999_999), "#66FF00")
    self.assertEqual(get_accum_exp_color(120_000_000), "#FF66CC")
    self.assertEqual(get_accum_exp_color(250_000_000), "#FF66CC")

    # Verify that only row_accum is highlighted, while others are is_highlight=False
    self.assertTrue(self.overlay.row_accum.is_highlight)
    self.assertFalse(self.overlay.row_est_60m.is_highlight)
    self.assertFalse(self.overlay.row_eta.is_highlight)
    self.assertFalse(self.overlay.row_duration.is_highlight)
    self.assertFalse(self.overlay.row_current.is_highlight)
    self.assertFalse(self.overlay.row_1m.is_highlight)
    self.assertFalse(self.overlay.row_est_10m.is_highlight)
    self.assertFalse(self.overlay.row_acc_10m.is_highlight)
    self.assertFalse(self.overlay.row_acc_60m.is_highlight)

    # Simulate gained EXP in engine and verify UI refresh applies color to row_accum only
    self.overlay.engine.total_gained_exp = 55_000_000
    self.overlay._refresh_ui()
    self.assertEqual(self.overlay.row_accum.current_color, "#66CCFF")
    self.assertIn("#66CCFF", self.overlay.row_accum.lbl_value.styleSheet())

    # Check uncolored row_est_60m uses neutral color
    self.assertIsNone(self.overlay.row_est_60m.current_color)
    self.assertIn("#f1f5f9", self.overlay.row_est_60m.lbl_value.styleSheet())


if __name__ == "__main__":
  unittest.main()
