"""Tests for ArtaleExpOverlay and GameModeSettingsDialog."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QLabel

from config import (
    ALL_METRIC_KEYS,
    DEFAULT_GAME_MODE_KEYS,
    get_accum_exp_color,
    get_status_indicator_dot,
)
from core.metrics import MeasurementState
from dev.window_picker import SelectWindowDialog
from ui.dialogs import AboutDialog, GameModeSettingsDialog
from ui.overlay import ArtaleExpOverlay

# Shared QApplication for testing
app = QApplication.instance()
if app is None:
  app = QApplication(sys.argv)


class TestOverlayHud(unittest.TestCase):

  def setUp(self):
    self.overlay = ArtaleExpOverlay(load_config=False)
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
    self.overlay._set_sliders_visible(False)
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

    # Toggle to Simple Mode (2nd F9 press)
    self.overlay.on_f9()
    self.assertEqual(self.overlay.current_mode, "simple")
    self.assertTrue(self.overlay.simple_widget.isVisible())
    self.assertFalse(self.overlay.details_container.isVisible())
    self.assertFalse(self.overlay.header_widget.isVisible())
    self.assertTrue(self.overlay.outer_card.is_pill)

    # Toggle back to Full Mode (3rd F9 press)
    self.overlay.on_f9()
    self.assertEqual(self.overlay.current_mode, "full")
    self.assertFalse(self.overlay.is_game_mode)
    self.assertTrue(self.overlay.lbl_title.isVisible())
    self.assertEqual(self.overlay.width(), 340)
    self.overlay._set_sliders_visible(False)
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

  def test_game_mode_focus_header_hidden(self):
    """Verify that in game mode, header bar hides when not focused."""
    self.overlay.on_f9()  # Enter Game Mode
    self.assertTrue(self.overlay.is_game_mode)

    # When unfocused: header and sliders must be hidden
    self.overlay._update_focus_visibility()
    if not self.overlay.isActiveWindow():
      self.assertFalse(self.overlay.header_widget.isVisible())
      self.assertFalse(self.overlay.slider_panel.isVisible())

    # In Full Mode, header is always visible even when unfocused
    self.overlay.on_f9()  # To Simple Mode
    self.overlay.on_f9()  # To Full Mode
    self.assertEqual(self.overlay.current_mode, "full")
    self.assertFalse(self.overlay.is_game_mode)
    self.assertTrue(self.overlay.header_widget.isVisible())

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

  def test_simple_mode_metrics_and_circulation(self):
    """Verify Simple Mode pill appearance, 3-mode circulation, and metrics sync."""
    # 1. Start in Full Mode
    self.assertEqual(self.overlay.current_mode, "full")
    self.assertTrue(self.overlay.lbl_title.isVisible())
    self.assertFalse(self.overlay.simple_widget.isVisible())
    self.assertFalse(self.overlay.outer_card.is_pill)

    # 2. F9 -> Game Mode
    self.overlay.on_f9()
    self.assertEqual(self.overlay.current_mode, "game")
    self.assertFalse(self.overlay.lbl_title.isVisible())
    self.assertFalse(self.overlay.simple_widget.isVisible())
    self.assertFalse(self.overlay.outer_card.is_pill)

    # 3. F9 -> Simple Mode
    self.overlay.on_f9()
    self.assertEqual(self.overlay.current_mode, "simple")
    self.assertTrue(self.overlay.simple_widget.isVisible())
    self.assertFalse(self.overlay.header_widget.isVisible())
    self.assertFalse(self.overlay.sub_widget.isVisible())
    self.assertFalse(self.overlay.details_container.isVisible())
    self.assertFalse(self.overlay.slider_panel.isVisible())
    self.assertTrue(self.overlay.outer_card.is_pill)

    # Verify Simple Mode shows the three requested items, status dot, and auto-start button
    simple_widgets = [
        self.overlay.simple_layout.itemAt(i).widget()
        for i in range(self.overlay.simple_layout.count())
    ]
    # Filter out None if any
    simple_widgets = [w for w in simple_widgets if w is not None]
    self.assertEqual(len(simple_widgets), 5)  # dot + 3 metrics + actions widget
    self.assertIs(simple_widgets[0], self.overlay.simple_status_dot)
    self.assertIs(simple_widgets[1], self.overlay.simple_metric_widgets["練功時長"])
    self.assertIs(simple_widgets[2], self.overlay.simple_metric_widgets["預估10分"])
    self.assertIs(simple_widgets[3], self.overlay.simple_metric_widgets["累計經驗"])
    self.assertIs(simple_widgets[4], self.overlay.simple_actions_widget)

    action_buttons = [
        self.overlay.simple_actions_layout.itemAt(i).widget()
        for i in range(self.overlay.simple_actions_layout.count())
    ]
    self.assertEqual(len(action_buttons), 3)
    self.assertIs(action_buttons[0], self.overlay.simple_btn_f7)
    self.assertIs(action_buttons[1], self.overlay.simple_btn_f8)
    self.assertIs(action_buttons[2], self.overlay.simple_btn_auto_start)

    # Verify label texts: 練功時長 -> 時長, 預估10分 -> 10分, 累計經驗 -> 累積
    self.assertEqual(self.overlay.simple_metric_widgets["練功時長"].lbl_label.text(), "時長")
    self.assertEqual(self.overlay.simple_metric_widgets["預估10分"].lbl_label.text(), "10分")
    self.assertEqual(self.overlay.simple_metric_widgets["累計經驗"].lbl_label.text(), "累積")

    # 4. Verify Simple Mode numbers simplify to 萬 and 億 with 7-tier EXP color and reserved space
    self.assertGreaterEqual(self.overlay.simple_metric_widgets["預估10分"].lbl_value.minimumWidth(), 70)
    self.assertGreaterEqual(self.overlay.simple_metric_widgets["累計經驗"].lbl_value.minimumWidth(), 70)
    self.assertLessEqual(self.overlay.simple_status_dot.width(), 16)

    self.overlay.engine.total_gained_exp = 1_234_000
    self.overlay._refresh_ui()
    accum_simple = self.overlay.simple_metric_widgets["累計經驗"]
    self.assertEqual(accum_simple.lbl_value.text(), "123.4 萬")

    self.overlay.engine.total_gained_exp = 123_456_789  # 1.23 億, Tier 7 (#FF66CC)
    self.overlay._refresh_ui()
    self.assertEqual(accum_simple.lbl_value.text(), "1.23 億")
    self.assertEqual(accum_simple.current_val_color, "#FF66CC")
    self.assertIn("#FF66CC", accum_simple.lbl_value.styleSheet())

    # 5. F9 -> Circulate back to Full Mode
    self.overlay.on_f9()
    self.assertEqual(self.overlay.current_mode, "full")
    self.assertTrue(self.overlay.lbl_title.isVisible())
    self.assertFalse(self.overlay.simple_widget.isVisible())
    self.assertFalse(self.overlay.outer_card.is_pill)

  def test_select_window_dialog_and_targeting(self):
    """Verify SelectWindowDialog and window targeting behavior."""
    dlg = SelectWindowDialog("MapleStory Worlds-Artale", None)
    title, hwnd = dlg.get_selected()
    self.assertEqual(title, "MapleStory Worlds-Artale")
    self.assertIsNone(hwnd)

    # Test filtering
    dlg._filter_list("artale")
    self.assertFalse(dlg.list_widget.item(0).isHidden())

    # Test setting target window on overlay
    self.overlay.set_target_window("VLC media player")
    self.assertEqual(self.overlay.target_window_name, "VLC media player")
    self.assertEqual(self.overlay.capture_worker.target_window, "VLC media player")

  def test_video_simulation_lifecycle(self):
    """Verify video simulation worker startup, speed changes, and shutdown."""
    # Invalid file returns False
    self.assertFalse(self.overlay.start_video_simulation("non_existent_file.mp4"))

    # Test with sample video if present
    sample_clip = r"C:\Users\gary1\Videos\Discord Clips\MapleStory_Worlds_0d11c233-b226-4d1d-952b-0c741acf61c2.mp4"
    if os.path.isfile(sample_clip):
      ok = self.overlay.start_video_simulation(sample_clip, speed=2.0)
      self.assertTrue(ok)
      self.assertTrue(self.overlay.is_simulating)
      self.assertIsNotNone(self.overlay.video_worker)
      self.assertEqual(self.overlay.sim_speed, 2.0)

      # Test pause toggle
      is_paused = self.overlay.toggle_simulation_pause()
      self.assertTrue(is_paused)
      is_paused = self.overlay.toggle_simulation_pause()
      self.assertFalse(is_paused)

      # Test speed change
      self.overlay.set_simulation_speed(5.0)
      self.assertEqual(self.overlay.sim_speed, 5.0)
      self.assertEqual(self.overlay.video_worker.playback_speed, 5.0)

      # Stop simulation
      self.overlay.stop_video_simulation()
      self.assertFalse(self.overlay.is_simulating)
      self.assertIsNone(self.overlay.video_worker)

  def test_dialog_closure_does_not_quit_app(self):
    """Verify that closing dialogs does not shut down the application due to quitOnLastWindowClosed."""
    qapp = QApplication.instance()
    self.assertIsNotNone(qapp)
    self.assertFalse(qapp.quitOnLastWindowClosed())

  def test_scale_and_opacity_controls_in_simple_mode(self):
    """Verify that size (scale) and transparency (opacity) can be changed dynamically in Simple Mode."""
    self.overlay._set_mode("simple")
    self.assertEqual(self.overlay.current_mode, "simple")

    # Change scale to 1.25x
    self.overlay.set_ui_scale(1.25)
    self.assertAlmostEqual(self.overlay.ui_scale, 1.25, places=2)
    self.assertEqual(self.overlay.lbl_scale_val.text(), "125%")
    self.assertEqual(self.overlay.slider_scale.value(), 125)

    # Change opacity to 0.70 (30% transparency)
    self.overlay.set_ui_opacity(0.70)
    self.assertAlmostEqual(self.overlay.opacity_val, 0.70, places=2)
    self.assertAlmostEqual(self.overlay.windowOpacity(), 0.70, places=2)
    self.assertEqual(self.overlay.lbl_opacity_val.text(), "30%")
    self.assertEqual(self.overlay.slider_opacity.value(), 30)

    # Reset back to default
    self.overlay.set_ui_scale(1.0)
    self.overlay.set_ui_opacity(0.95)
    self.assertAlmostEqual(self.overlay.ui_scale, 1.0, places=2)
    self.assertAlmostEqual(self.overlay.opacity_val, 0.95, places=2)

  def test_open_game_mode_settings_dialog(self):
    """Verify that _open_game_mode_settings can be invoked without NameError."""
    from unittest.mock import patch
    from PyQt6.QtWidgets import QDialog
    with patch.object(GameModeSettingsDialog, "exec", return_value=QDialog.DialogCode.Accepted):
      self.overlay._open_game_mode_settings()

  def test_open_select_window_dialog(self):
    """Verify that _open_select_window_dialog can be invoked without NameError."""
    from unittest.mock import patch
    from PyQt6.QtWidgets import QDialog
    with patch.object(SelectWindowDialog, "exec", return_value=QDialog.DialogCode.Accepted):
      self.overlay._open_select_window_dialog()

  def test_f6_auto_start_toggle(self):
    """Verify that F6 toggles auto start and updates button style and simple mode button."""
    self.assertFalse(self.overlay.engine.auto_start_enabled)
    self.assertIn("OFF", self.overlay.btn_auto_start.text())

    # Press F6 -> ON
    self.overlay.on_f6()
    self.assertTrue(self.overlay.engine.auto_start_enabled)
    self.assertIn("ON", self.overlay.btn_auto_start.text())

    # Press F6 again -> OFF
    self.overlay.on_f6()
    self.assertFalse(self.overlay.engine.auto_start_enabled)
    self.assertIn("OFF", self.overlay.btn_auto_start.text())

    # In Simple Mode: F6 toggles auto start; actions widget hides when unfocused and reveals on focus
    self.overlay._set_mode("simple")
    self.assertFalse(self.overlay.simple_actions_widget.isVisible())

    # Toggling F6 while unfocused changes state without revealing button or moving window
    self.overlay.on_f6()
    self.assertTrue(self.overlay.engine.auto_start_enabled)
    self.assertFalse(self.overlay.simple_actions_widget.isVisible())

    # When focused/hovered, button reveals on right round with status color
    self.overlay.simple_actions_widget.show()
    self.assertTrue(self.overlay.simple_actions_widget.isVisible())
    self.assertEqual(
        self.overlay.simple_btn_auto_start.custom_color.name(), "#34d399"
    )

    self.overlay.on_f6()
    self.assertFalse(self.overlay.engine.auto_start_enabled)
    self.assertIsNone(self.overlay.simple_btn_auto_start.custom_color)

    # When unfocused, button hides even when auto start is ON
    self.overlay.engine.auto_start_enabled = True
    self.overlay._update_simple_mode_focus_state()
    self.assertFalse(self.overlay.simple_actions_widget.isVisible())

    # Verify Auto Start icon scaling in full & game mode
    self.overlay._set_mode("full")
    self.overlay.set_ui_scale(1.0)
    ic_sz_1x = self.overlay.btn_auto_start.custom_icon_size
    self.overlay.set_ui_scale(1.5)
    ic_sz_15x = self.overlay.btn_auto_start.custom_icon_size
    self.assertGreater(ic_sz_15x, ic_sz_1x)

  def test_status_indicator_dot_states(self):
    """Verify 4 indicator dot states:

    1. red solid: measuring (like camera recording REC dot)
    2. yellow solid: pause
    3. green solid: not measuring (reset or just launched), window and exp number captured
    4. green hollow: exp number not captured correctly (searching, minimized, or not found)
    """
    # 1. Helper function checks
    # Green hollow (unlocked / searching)
    c, col, _ = get_status_indicator_dot(False, MeasurementState.IDLE)
    self.assertEqual((c, col), ("○", "#4ade80"))
    c, col, _ = get_status_indicator_dot(False, MeasurementState.RUNNING)
    self.assertEqual((c, col), ("○", "#4ade80"))
    c, col, _ = get_status_indicator_dot(False, MeasurementState.PAUSED)
    self.assertEqual((c, col), ("○", "#4ade80"))

    # Green solid (locked & idle / ready)
    c, col, _ = get_status_indicator_dot(True, MeasurementState.IDLE)
    self.assertEqual((c, col), ("●", "#4ade80"))

    # Red solid (measuring / recording)
    c, col, _ = get_status_indicator_dot(True, MeasurementState.RUNNING)
    self.assertEqual((c, col), ("●", "#ef4444"))

    # Yellow solid (pause)
    c, col, _ = get_status_indicator_dot(True, MeasurementState.PAUSED)
    self.assertEqual((c, col), ("●", "#eab308"))

    # 2. Live UI widget transitions
    # Initially: unlocked -> green hollow
    self.overlay._on_status_changed("尋找視窗中...", False)
    self.assertEqual(self.overlay.status_dot.text(), "○")
    self.assertIn("#4ade80", self.overlay.status_dot.styleSheet())

    # Window locked, idle -> green solid
    self.overlay._on_status_changed("即時辨識鎖定中", True)
    self.assertEqual(self.overlay.status_dot.text(), "●")
    self.assertIn("#4ade80", self.overlay.status_dot.styleSheet())

    # Start measuring (F7) -> red solid + breathing active
    self.overlay.on_f7()
    self.assertEqual(self.overlay.status_dot.text(), "●")
    self.assertIn("#ef4444", self.overlay.status_dot.styleSheet())
    self.assertTrue(self.overlay.status_dot._is_breathing)
    self.assertTrue(self.overlay.status_dot._breath_timer.isActive())

    # Pause (F7) -> yellow solid + breathing stopped
    self.overlay.on_f7()
    self.assertEqual(self.overlay.status_dot.text(), "●")
    self.assertIn("#eab308", self.overlay.status_dot.styleSheet())
    self.assertFalse(self.overlay.status_dot._is_breathing)
    self.assertFalse(self.overlay.status_dot._breath_timer.isActive())

    # Reset (F8) -> green solid (still locked & idle) + breathing stopped
    self.overlay.on_f8()
    self.assertEqual(self.overlay.status_dot.text(), "●")
    self.assertIn("#4ade80", self.overlay.status_dot.styleSheet())
    self.assertFalse(self.overlay.status_dot._is_breathing)
    self.assertFalse(self.overlay.status_dot._breath_timer.isActive())

    # Window lost -> green hollow + breathing stopped
    self.overlay._on_status_changed("視窗已最小化", False)
    self.assertEqual(self.overlay.status_dot.text(), "○")
    self.assertIn("#4ade80", self.overlay.status_dot.styleSheet())
    self.assertFalse(self.overlay.status_dot._is_breathing)

    # Also test Simple Mode simple_status_dot updates in sync
    self.overlay._set_mode("simple")
    self.assertEqual(self.overlay.simple_status_dot.text(), "○")
    self.assertIn("#4ade80", self.overlay.simple_status_dot.styleSheet())
    self.assertFalse(self.overlay.simple_status_dot._is_breathing)

    self.overlay._on_status_changed("即時辨識鎖定中", True)
    self.assertEqual(self.overlay.simple_status_dot.text(), "●")
    self.assertIn("#4ade80", self.overlay.simple_status_dot.styleSheet())
    self.assertFalse(self.overlay.simple_status_dot._is_breathing)

    self.overlay.on_f7()
    self.assertEqual(self.overlay.simple_status_dot.text(), "●")
    self.assertIn("#ef4444", self.overlay.simple_status_dot.styleSheet())
    self.assertTrue(self.overlay.simple_status_dot._is_breathing)
    self.assertTrue(self.overlay.simple_status_dot._breath_timer.isActive())

    self.overlay.on_f7()
    self.assertEqual(self.overlay.simple_status_dot.text(), "●")
    self.assertIn("#eab308", self.overlay.simple_status_dot.styleSheet())
    self.assertFalse(self.overlay.simple_status_dot._is_breathing)
    self.assertFalse(self.overlay.simple_status_dot._breath_timer.isActive())

  def test_copyright_visibility_modes(self):
    """Verify that copyright is visible only in Full Mode, centered, and hidden when unfocused."""
    # 1. Full Mode: Centered alignment
    self.overlay._set_mode("full")
    self.assertEqual(self.overlay.lbl_copyright.alignment(), Qt.AlignmentFlag.AlignCenter)
    self.assertIn("© 2026 By", self.overlay.lbl_copyright.text())
    self.assertIn("G8G", self.overlay.lbl_copyright.text())

    # Focus behavior: visible when active, hidden when inactive
    from unittest.mock import patch
    with patch.object(self.overlay, "isActiveWindow", return_value=True):
      self.overlay._update_focus_visibility()
      self.assertTrue(self.overlay.lbl_copyright.isVisible())

    with patch.object(self.overlay, "isActiveWindow", return_value=False):
      self.overlay._update_focus_visibility()
      self.assertFalse(self.overlay.lbl_copyright.isVisible())

    # 2. Game Mode: Always hidden
    self.overlay._set_mode("game")
    self.assertFalse(self.overlay.lbl_copyright.isVisible())

    # 3. Simple Mode: Always hidden
    self.overlay._set_mode("simple")
    self.assertFalse(self.overlay.lbl_copyright.isVisible())

  def test_about_dialog_content(self):
    """Verify AboutDialog contains Author, Version, Discord ID, and Check Update button."""
    import config
    dlg = AboutDialog(parent=self.overlay)
    self.assertEqual(dlg.windowTitle(), "關於 (About)")
    # Collect all label texts in dialog
    labels = [lbl.text() for lbl in dlg.findChildren(QLabel)]
    full_text = " ".join(labels)
    self.assertIn("G8G", full_text)
    self.assertIn("1.0.0", full_text)
    self.assertIn(config.get_isa_display_name(), full_text)
    self.assertIn("Discord ID", full_text)
    self.assertIn("garyhuang", full_text)
    self.assertIn("© 2026 By", full_text)
    self.assertIsNotNone(dlg.btn_check_update)
    self.assertEqual(dlg.btn_check_update.text(), "檢查更新")
    dlg.close()

  def test_context_menu_has_about(self):
    """Verify context menu contains 關於... action."""
    from unittest.mock import patch
    from PyQt6.QtCore import QPoint
    from PyQt6.QtGui import QContextMenuEvent

    actions_seen = []
    def fake_exec(menu_self, pos=None):
      for act in menu_self.actions():
        actions_seen.append(act.text())
      return None

    with patch("PyQt6.QtWidgets.QMenu.exec", new=fake_exec):
      event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(10, 10))
      self.overlay.contextMenuEvent(event)

    self.assertIn("快捷鍵", actions_seen)
    self.assertIn("關於...", actions_seen)
    self.assertIn("關閉程式", actions_seen)

  def test_context_menu_shortcuts_section(self):
    """Verifies that 快捷鍵 submenu displays platform-specific keys and triggers callbacks."""
    from unittest.mock import patch
    from PyQt6.QtCore import QPoint
    from PyQt6.QtGui import QContextMenuEvent
    import config

    # Test macOS submenu structure
    sub_actions_mac = []
    def fake_exec_mac(menu_self, pos=None):
      for act in menu_self.actions():
        if act.text() == "快捷鍵" and act.menu():
          for sub_act in act.menu().actions():
            sub_actions_mac.append(sub_act.text())
      return None

    with patch("PyQt6.QtWidgets.QMenu.exec", new=fake_exec_mac), \
         patch.object(config, "HOTKEY_LABEL_AUTO_START", "⌘6"), \
         patch.object(config, "HOTKEY_LABEL_START_PAUSE", "⌘7"), \
         patch.object(config, "HOTKEY_LABEL_RESET", "⌘8"), \
         patch.object(config, "HOTKEY_LABEL_SWITCH_MODE", "⌘9"):
      event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(10, 10))
      self.overlay.contextMenuEvent(event)

    self.assertTrue(any("⌘6" in text for text in sub_actions_mac))
    self.assertTrue(any("⌘7" in text for text in sub_actions_mac))
    self.assertTrue(any("⌘8" in text for text in sub_actions_mac))
    self.assertTrue(any("⌘9" in text for text in sub_actions_mac))
    self.assertEqual(len(sub_actions_mac), 4)

    # Test Windows submenu structure
    sub_actions_win = []
    def fake_exec_win(menu_self, pos=None):
      for act in menu_self.actions():
        if act.text() == "快捷鍵" and act.menu():
          for sub_act in act.menu().actions():
            sub_actions_win.append(sub_act.text())
      return None

    with patch("PyQt6.QtWidgets.QMenu.exec", new=fake_exec_win), \
         patch.object(config, "HOTKEY_LABEL_AUTO_START", "F6"), \
         patch.object(config, "HOTKEY_LABEL_START_PAUSE", "F7"), \
         patch.object(config, "HOTKEY_LABEL_RESET", "F8"), \
         patch.object(config, "HOTKEY_LABEL_SWITCH_MODE", "F9"):
      event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(10, 10))
      self.overlay.contextMenuEvent(event)

    self.assertTrue(any("F6" in text for text in sub_actions_win))
    self.assertTrue(any("F7" in text for text in sub_actions_win))
    self.assertTrue(any("F8" in text for text in sub_actions_win))
    self.assertTrue(any("F9" in text for text in sub_actions_win))
    self.assertEqual(len(sub_actions_win), 4)

  def test_keypress_event_shortcuts(self):
    """Verifies that keyPressEvent triggers correct handlers for F-keys and ⌘-keys."""
    from unittest.mock import MagicMock
    from PyQt6.QtCore import QEvent, Qt
    from PyQt6.QtGui import QKeyEvent

    self.overlay.on_f6 = MagicMock()
    self.overlay.on_f7 = MagicMock()
    self.overlay.on_f8 = MagicMock()
    self.overlay.on_f9 = MagicMock()

    # F6
    ev_f6 = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_F6, Qt.KeyboardModifier.NoModifier)
    self.overlay.keyPressEvent(ev_f6)
    self.assertEqual(self.overlay.on_f6.call_count, 1)

    # F7
    ev_f7 = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_F7, Qt.KeyboardModifier.NoModifier)
    self.overlay.keyPressEvent(ev_f7)
    self.assertEqual(self.overlay.on_f7.call_count, 1)

    # F8
    ev_f8 = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_F8, Qt.KeyboardModifier.NoModifier)
    self.overlay.keyPressEvent(ev_f8)
    self.assertEqual(self.overlay.on_f8.call_count, 1)

    # F9
    ev_f9 = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_F9, Qt.KeyboardModifier.NoModifier)
    self.overlay.keyPressEvent(ev_f9)
    self.assertEqual(self.overlay.on_f9.call_count, 1)

    # ⌘6 (Command + 6 / ControlModifier on macOS)
    ev_cmd6 = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_6, Qt.KeyboardModifier.ControlModifier)
    self.overlay.keyPressEvent(ev_cmd6)
    self.assertEqual(self.overlay.on_f6.call_count, 2)

    # ⌘7
    ev_cmd7 = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_7, Qt.KeyboardModifier.ControlModifier)
    self.overlay.keyPressEvent(ev_cmd7)
    self.assertEqual(self.overlay.on_f7.call_count, 2)

    # ⌘8
    ev_cmd8 = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_8, Qt.KeyboardModifier.ControlModifier)
    self.overlay.keyPressEvent(ev_cmd8)
    self.assertEqual(self.overlay.on_f8.call_count, 2)

    # ⌘9
    ev_cmd9 = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_9, Qt.KeyboardModifier.ControlModifier)
    self.overlay.keyPressEvent(ev_cmd9)
    self.assertEqual(self.overlay.on_f9.call_count, 2)


class TestSettingsPersistence(unittest.TestCase):
  """Validates that settings (size, transparency, order, game mode items, position) persist across sessions."""

  def setUp(self):
    import tempfile
    self.test_dir = tempfile.TemporaryDirectory()
    self.config_path = os.path.join(self.test_dir.name, "hud_config.json")

  def tearDown(self):
    self.test_dir.cleanup()

  def test_settings_loaded_on_startup(self):
    """Verify settings are preserved and not wiped out when overlay initializes."""
    import json
    from unittest.mock import patch

    custom_cfg = {
        "x": 240,
        "y": 160,
        "ui_mode": "game",
        "is_game_mode": True,
        "game_mode_order": [
            "當前經驗",
            "EXP 進度條",
            "練功時長",
            "1分鐘經驗",
            "預估10分",
            "累積10分",
            "預估60分",
            "累積60分",
            "累計經驗",
            "升級預估時間",
        ],
        "game_mode_items": ["當前經驗", "EXP 進度條"],
        "ui_scale": 1.25,
        "opacity": 0.70,
        "auto_start": False,
        "target_window_name": "MapleStory Worlds-Artale",
    }
    with open(self.config_path, "w", encoding="utf-8") as f:
      json.dump(custom_cfg, f, indent=2)

    with patch("ui.overlay.CONFIG_FILE", self.config_path):
      overlay = ArtaleExpOverlay(load_config=True)
      overlay.show()

      # Verify restored state
      self.assertEqual(overlay.current_mode, "game")
      self.assertTrue(overlay.is_game_mode)
      self.assertAlmostEqual(overlay.ui_scale, 1.25, places=2)
      self.assertAlmostEqual(overlay.opacity_val, 0.70, places=2)
      self.assertEqual(overlay.game_mode_items, ["當前經驗", "EXP 進度條"])
      self.assertEqual(overlay.game_mode_order[0], "當前經驗")
      self.assertFalse(overlay.engine.auto_start_enabled)
      self.assertEqual(overlay.slider_scale.value(), 125)
      self.assertEqual(overlay.slider_opacity.value(), 30)

      # Verify config file was NOT overwritten with default values during init
      with open(self.config_path, "r", encoding="utf-8") as f:
        saved_after_init = json.load(f)
      self.assertEqual(saved_after_init["ui_mode"], "game")
      self.assertAlmostEqual(saved_after_init["ui_scale"], 1.25, places=2)
      self.assertAlmostEqual(saved_after_init["opacity"], 0.70, places=2)
      self.assertEqual(saved_after_init["game_mode_items"], ["當前經驗", "EXP 進度條"])

      overlay.close()

  def test_settings_saved_when_modified(self):
    """Verify modifying scale, opacity, order, and items updates config file."""
    import json
    from unittest.mock import patch

    with patch("ui.overlay.CONFIG_FILE", self.config_path):
      overlay = ArtaleExpOverlay(load_config=False)
      overlay.show()

      # Modify scale and opacity
      overlay.set_ui_scale(1.50)
      overlay.set_ui_opacity(0.80)
      overlay.game_mode_items = ["練功時長", "預估60分"]
      overlay.game_mode_order = [
          "升級預估時間",
          "當前經驗",
          "練功時長",
          "1分鐘經驗",
          "預估10分",
          "累積10分",
          "預估60分",
          "累積60分",
          "累計經驗",
          "EXP 進度條",
      ]
      overlay.on_f9()  # Switch to game mode
      overlay._save_config()

      with open(self.config_path, "r", encoding="utf-8") as f:
        saved = json.load(f)

      self.assertAlmostEqual(saved["ui_scale"], 1.50, places=2)
      self.assertAlmostEqual(saved["opacity"], 0.80, places=2)
      self.assertEqual(saved["ui_mode"], "game")
      self.assertEqual(saved["game_mode_items"], ["練功時長", "預估60分"])
      self.assertEqual(saved["game_mode_order"][0], "升級預估時間")

      overlay.close()


if __name__ == "__main__":
  unittest.main()


