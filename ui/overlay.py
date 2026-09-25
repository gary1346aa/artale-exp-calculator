"""Modern Floating HUD Overlay for Artale EXP Calculator (PyQt6).

Complies with the Google Python Style Guide.
Modularized UI layer interfacing with core.metrics and core.capture.
"""

import json
import os
import sys
import time
from typing import List, Optional, Tuple

from PyQt6.QtCore import (
    QEvent,
    QPoint,
    QRectF,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QCursor,
    QFont,
    QIcon,
    QPainter,
    QPen,
)
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

import config
from config import (
    ALL_METRIC_KEYS,
    CONFIG_FILE,
    DEFAULT_GAME_MODE_KEYS,
    DEFAULT_SIMPLE_MODE_KEYS,
    FONT_FAMILY,
    SIMPLE_METRIC_CONFIG,
    format_chinese_exp,
    get_accum_exp_color,
)
from core.capture import CaptureWorker, find_window_by_title_safe
from core.metrics import ExpMetricsEngine, MeasurementState
from ui.components import (
    MetricRow,
    SimpleMetricItem,
    SimpleProgressBarItem,
    SmoothButton,
    SmoothCard,
)
from ui.dialogs import GameModeSettingsDialog
from ui.hotkeys import HotkeyWorker

VideoSimulationWorker = None



class ArtaleExpOverlay(QWidget):
  """Main floating HUD overlay widget supporting Full, Game, and Simple Modes."""

  @property
  def is_game_mode(self) -> bool:
    return self.current_mode == "game"

  @is_game_mode.setter
  def is_game_mode(self, val: bool):
    self.current_mode = "game" if val else "full"

  def __init__(self):
    super().__init__()
    self.engine = ExpMetricsEngine()
    self.current_mode = "full"  # "full", "game", "simple"
    self.game_mode_order = list(ALL_METRIC_KEYS)
    self.game_mode_items = list(DEFAULT_GAME_MODE_KEYS)
    self.ui_scale = 1.0
    self.opacity_val = 0.95
    self.drag_position = QPoint()
    self.target_window_name: str = "MapleStory Worlds-Artale"
    self.target_hwnd: Optional[int] = None
    self.video_worker: Optional[VideoSimulationWorker] = None
    self.is_simulating: bool = False
    self.sim_speed: float = 1.0
    self.sim_video_path: Optional[str] = None

    self._init_window_flags()
    self._init_ui()
    self._load_config()

    qapp = QApplication.instance()
    if qapp:
      qapp.setQuitOnLastWindowClosed(False)

    self.setWindowTitle("Artale EXP Calculator")
    icon_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "assets", "app_icon.png"
    )
    if os.path.isfile(icon_path):
      app_icon = QIcon(icon_path)
      self.setWindowIcon(app_icon)
      if qapp:
        qapp.setWindowIcon(app_icon)

    # Refresh timer (1 Hz)
    self.ui_timer = QTimer(self)
    self.ui_timer.timeout.connect(self._refresh_ui)
    self.ui_timer.start(1000)

    # Global hotkey listener (F7, F8, F9)
    self.hotkey_worker = HotkeyWorker()
    self.hotkey_worker.f7_pressed.connect(self.on_f7)
    self.hotkey_worker.f8_pressed.connect(self.on_f8)
    self.hotkey_worker.f9_pressed.connect(self.on_f9)
    self.hotkey_worker.start()

    # Capture worker
    self.capture_worker = CaptureWorker(self.target_window_name, self.target_hwnd)
    self.capture_worker.frame_parsed.connect(self._on_exp_sample)
    self.capture_worker.status_changed.connect(self._on_status_changed)
    self.capture_worker.start()

  def _init_window_flags(self):
    self.setWindowFlags(
        Qt.WindowType.FramelessWindowHint
        | Qt.WindowType.WindowStaysOnTopHint
        | Qt.WindowType.Tool
    )
    self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

  def _init_ui(self):
    self.setFixedWidth(int(340 * self.ui_scale))

    # Outer container with modern vector-smoothed dark glass styling
    # (Note: Avoid QGraphicsDropShadowEffect here because on Windows layered translucent
    # windows, external shadow bounding boxes trigger negative/out-of-bounds dirty rects
    # resulting in 'UpdateLayeredWindowIndirect failed: The parameter is incorrect.')
    self.outer_card = SmoothCard(self)
    self.outer_card.setObjectName("outerCard")

    main_layout = QVBoxLayout(self)
    main_layout.setContentsMargins(0, 0, 0, 0)
    main_layout.addWidget(self.outer_card)

    self.card_layout = QVBoxLayout(self.outer_card)
    self.card_layout.setContentsMargins(14, 12, 14, 12)
    self.card_layout.setSpacing(6)

    # 1. Top Header Bar: Title, State Badge, Window Controls
    self.header_widget = QWidget(self.outer_card)
    header_layout = QHBoxLayout(self.header_widget)
    header_layout.setContentsMargins(0, 0, 0, 2)
    header_layout.setSpacing(5)

    self.lbl_title = QLabel("ARTALE EXP")
    self.lbl_title.setStyleSheet(f"""
            QLabel {{
                color: #e2e8f0;
                font-size: 14px;
                font-weight: 700;
                letter-spacing: 0.5px;
                font-family: {FONT_FAMILY};
                background: transparent;
            }}
        """)

    # State Badge: [計時中] / [已暫停] / [待機中]
    self.lbl_state_badge = QLabel("待機中")
    self.lbl_state_badge.setStyleSheet(f"""
            QLabel {{
                color: #94a3b8;
                background-color: rgba(255, 255, 255, 0.08);
                padding: 2px 7px;
                border-radius: 4px;
                font-size: 11px;
                font-weight: 600;
                font-family: {FONT_FAMILY};
            }}
        """)

    # Vector-smoothed Control buttons (F7, F8, F9, Settings, Close)
    self.btn_f7 = SmoothButton("▶", self)
    self.btn_f7.setToolTip("開始 / 暫停 [F7]")
    self.btn_f7.setFixedSize(24, 24)
    self.btn_f7.clicked.connect(self.on_f7)

    self.btn_f8 = SmoothButton("↺", self)
    self.btn_f8.setToolTip("重置本次計時 (不重置啟動初始經驗) [F8]")
    self.btn_f8.setFixedSize(24, 24)
    self.btn_f8.clicked.connect(self.on_f8)

    self.btn_f9 = SmoothButton("◫", self)
    self.btn_f9.setToolTip("切換遊戲模式 [F9]")
    self.btn_f9.setFixedSize(24, 24)
    self.btn_f9.clicked.connect(self.on_f9)

    self.btn_settings = SmoothButton("⚙", self)
    self.btn_settings.setToolTip("指標顯示與排列設定")
    self.btn_settings.setFixedSize(24, 24)
    self.btn_settings.clicked.connect(self._open_game_mode_settings)

    self.btn_close = SmoothButton("✕", self, is_close=True)
    self.btn_close.setToolTip("關閉程式")
    self.btn_close.setFixedSize(24, 24)
    self.btn_close.clicked.connect(self.close)

    header_layout.addWidget(self.lbl_title)
    header_layout.addWidget(self.lbl_state_badge)
    header_layout.addStretch()
    header_layout.addWidget(self.btn_f7)
    header_layout.addWidget(self.btn_f8)
    header_layout.addWidget(self.btn_f9)
    header_layout.addWidget(self.btn_settings)
    header_layout.addWidget(self.btn_close)
    self.card_layout.addWidget(self.header_widget)

    # 2. Sub-header Bar: Status indicator dot + Status text on left, Auto-Start Toggle on right
    self.sub_widget = QWidget(self.outer_card)
    sub_layout = QHBoxLayout(self.sub_widget)
    sub_layout.setContentsMargins(0, 0, 0, 2)
    sub_layout.setSpacing(6)

    self.status_dot = QLabel("●")
    self.status_dot.setToolTip("遊戲視窗與經驗條鎖定狀態指示燈")
    self.status_dot.setStyleSheet(
        "color: #eab308; font-size: 13px; background: transparent;"
    )

    self.lbl_status = QLabel("正在連線至遊戲視窗...")
    self.lbl_status.setStyleSheet(f"""
            QLabel {{
                color: #64748b;
                font-size: 11px;
                font-family: {FONT_FAMILY};
                background: transparent;
            }}
        """)

    self.btn_auto_start = SmoothButton("⚡ 自動開始 [OFF]", self)
    self.btn_auto_start.setToolTip(
        "自動開始：開啟時，偵測到經驗值增加即自動開始計時 (F7暫停或F8重置時自動關閉一次)"
    )
    self.btn_auto_start.setFixedHeight(24)
    self._update_auto_start_button_style(False)
    self.btn_auto_start.clicked.connect(self._toggle_auto_start)

    sub_layout.addWidget(self.status_dot)
    sub_layout.addWidget(self.lbl_status)
    sub_layout.addStretch()
    sub_layout.addWidget(self.btn_auto_start)
    self.card_layout.addWidget(self.sub_widget)

    # Separator
    self.sep1 = self._create_separator()
    self.card_layout.addWidget(self.sep1)

    # 3. Detailed Metrics Body
    self.details_container = QWidget(self)
    self.details_layout = QVBoxLayout(self.details_container)
    self.details_layout.setContentsMargins(0, 0, 0, 0)
    self.details_layout.setSpacing(3)

    self.row_duration = MetricRow("練功時長", "00:00:00", self)
    self.row_1m = MetricRow("1分鐘經驗", "0", self)
    self.row_est_10m = MetricRow("預估10分", "0", self)
    self.row_acc_10m = MetricRow("累積10分", "0", self)
    self.row_est_60m = MetricRow("預估60分", "0", self, is_highlight=False)
    self.row_acc_60m = MetricRow("累積60分", "0", self)

    self.sep_summary = self._create_separator()

    self.row_accum = MetricRow("累計經驗", "0", self, is_highlight=True)
    self.row_current = MetricRow("當前經驗", "無資料", self)
    self.row_eta = MetricRow("升級預估時間", "-", self, is_highlight=False)

    # 4. EXP Progress Bar (managed dynamically with metrics)
    self.gauge_bar = QProgressBar(self)
    self.gauge_bar.setFixedHeight(8)
    self.gauge_bar.setTextVisible(False)
    self.gauge_bar.setRange(0, 10000)
    self.gauge_bar.setValue(0)
    self.gauge_bar.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
    self.gauge_bar.setStyleSheet("""
            QProgressBar {
                background-color: rgba(255, 255, 255, 0.08);
                border-radius: 4px;
                border: none;
                margin-top: 3px;
                margin-bottom: 3px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #10b981, stop:1 #38bdf8);
                border-radius: 4px;
            }
        """)

    self.card_layout.addWidget(self.details_container)

    # 5. Sliders Panel (Size & Opacity, only shown on mouse hover)
    self.slider_panel = QFrame(self.outer_card)
    self.slider_panel.setStyleSheet(f"""
        QFrame {{
            background: transparent;
            border: none;
            padding-top: 2px;
        }}
        QLabel {{
            color: #94a3b8;
            font-size: 11px;
            font-family: {FONT_FAMILY};
        }}
        QSlider::groove:horizontal {{
            height: 4px;
            background: rgba(255, 255, 255, 0.15);
            border-radius: 2px;
        }}
        QSlider::sub-page:horizontal {{
            background: #10b981;
            border-radius: 2px;
        }}
        QSlider::handle:horizontal {{
            background: #34d399;
            border: 1px solid #ffffff;
            width: 12px;
            height: 12px;
            margin-top: -4px;
            margin-bottom: -4px;
            border-radius: 6px;
        }}
        QSlider::handle:horizontal:hover {{
            background: #6ee7b7;
        }}
    """)
    sl_layout = QVBoxLayout(self.slider_panel)
    sl_layout.setContentsMargins(2, 2, 2, 2)
    sl_layout.setSpacing(4)

    sl_layout.addWidget(self._create_separator())

    row_scale = QHBoxLayout()
    row_scale.setSpacing(6)
    lbl_scale_title = QLabel("縮放")
    self.lbl_scale_val = QLabel(f"{int(self.ui_scale * 100)}%")
    self.lbl_scale_val.setFixedWidth(36)
    self.lbl_scale_val.setAlignment(
        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
    )
    self.slider_scale = QSlider(Qt.Orientation.Horizontal)
    self.slider_scale.setRange(50, 200)
    self.slider_scale.setValue(int(round(self.ui_scale * 100)))
    self.slider_scale.valueChanged.connect(self._on_scale_changed)
    self.slider_scale.sliderReleased.connect(self._on_slider_released)

    row_scale.addWidget(lbl_scale_title)
    row_scale.addWidget(self.slider_scale)
    row_scale.addWidget(self.lbl_scale_val)
    sl_layout.addLayout(row_scale)

    row_opacity = QHBoxLayout()
    row_opacity.setSpacing(6)
    lbl_opacity_title = QLabel("透明")
    transparency_pct = int(round((1.0 - self.opacity_val) * 100))
    self.lbl_opacity_val = QLabel(f"{transparency_pct}%")
    self.lbl_opacity_val.setFixedWidth(36)
    self.lbl_opacity_val.setAlignment(
        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
    )
    self.slider_opacity = QSlider(Qt.Orientation.Horizontal)
    self.slider_opacity.setRange(0, 80)
    self.slider_opacity.setValue(transparency_pct)
    self.slider_opacity.valueChanged.connect(self._on_opacity_changed)
    self.slider_opacity.sliderReleased.connect(self._on_slider_released)

    row_opacity.addWidget(lbl_opacity_title)
    row_opacity.addWidget(self.slider_opacity)
    row_opacity.addWidget(self.lbl_opacity_val)
    sl_layout.addLayout(row_opacity)

    self.card_layout.addWidget(self.slider_panel)
    self.slider_panel.hide()

    # 6. Hotkey Guidance Footer
    self.lbl_hotkey_hint = QLabel("[F7] 開始/暫停  [F8] 重置  [F9] 遊戲模式")
    self.lbl_hotkey_hint.setStyleSheet(f"""
            QLabel {{
                color: #64748b;
                font-size: 11px;
                font-family: {FONT_FAMILY};
                padding-top: 4px;
                background: transparent;
            }}
        """)
    self.lbl_hotkey_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
    self.card_layout.addWidget(self.lbl_hotkey_hint)

    # Metric key to widget mapping for Game Mode customization
    self.metric_widgets = {
        "練功時長": self.row_duration,
        "1分鐘經驗": self.row_1m,
        "預估10分": self.row_est_10m,
        "累積10分": self.row_acc_10m,
        "預估60分": self.row_est_60m,
        "累積60分": self.row_acc_60m,
        "累計經驗": self.row_accum,
        "當前經驗": self.row_current,
        "升級預估時間": self.row_eta,
        "EXP 進度條": self.gauge_bar,
    }

    # 7. Simple Mode Horizontal Capsule Widget
    self.simple_widget = QWidget(self.outer_card)
    self.simple_layout = QHBoxLayout(self.simple_widget)
    self.simple_layout.setContentsMargins(0, 0, 0, 0)
    self.simple_layout.setSpacing(0)

    self.simple_status_dot = QLabel("●", self.simple_widget)
    self.simple_status_dot.setAttribute(
        Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
    )
    self.simple_status_dot.setFixedSize(12, 12)
    self.simple_status_dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
    self.simple_status_dot.setStyleSheet(
        "color: #eab308; font-size: 10px; background: transparent;"
    )

    self.simple_metric_widgets = {}
    for key, cfg in SIMPLE_METRIC_CONFIG.items():
      w = SimpleMetricItem(
          key, cfg["label"], cfg["color"], self.simple_widget
      )
      w.hide()
      self.simple_metric_widgets[key] = w
    prog_w = SimpleProgressBarItem(self.simple_widget)
    prog_w.hide()
    self.simple_metric_widgets["EXP 進度條"] = prog_w

    self.card_layout.addWidget(self.simple_widget)
    self.simple_widget.hide()

    self._apply_game_mode()

  def _create_separator(self) -> QFrame:
    sep = QFrame()
    sep.setFrameShape(QFrame.Shape.HLine)
    sep.setStyleSheet(
        "background-color: rgba(255, 255, 255, 0.08); max-height: 1px;"
    )
    return sep

  def _update_auto_start_button_style(self, enabled: bool):
    if enabled:
      self.btn_auto_start.setText("⚡ 自動開始 [ON]")
      self.btn_auto_start.set_custom_style(
          bg=QColor(16, 185, 129, 45),
          border=QColor(52, 211, 153, 100),
          text_color=QColor("#34d399"),
      )
    else:
      self.btn_auto_start.setText("⚡ 自動開始 [OFF]")
      self.btn_auto_start.set_custom_style(
          bg=QColor(255, 255, 255, 15),
          border=QColor(255, 255, 255, 30),
          text_color=QColor("#94a3b8"),
      )

  def _toggle_auto_start(self):
    enabled = self.engine.toggle_auto_start()
    self._update_auto_start_button_style(enabled)
    self._refresh_ui()

  def on_f7(self):
    """F7 Hotkey handler: Start / Stop (pause) toggle."""
    self.engine.toggle_start_stop()
    self._refresh_ui()

  def on_f8(self):
    """F8 Hotkey handler: Reset measurement (preserves initial EXP, disables auto-start once)."""
    self.engine.reset_measurement(disable_auto_start=True)
    self._refresh_ui()

  def on_f9(self):
    """F9 Hotkey handler: Circulate between Full -> Game -> Simple modes."""
    if self.current_mode == "full":
      self.current_mode = "game"
    elif self.current_mode == "game":
      self.current_mode = "simple"
    else:
      self.current_mode = "full"
    self._apply_game_mode()

  def _set_mode(self, mode: str):
    """Directly switch to specified mode ('full', 'game', 'simple')."""
    self.current_mode = mode
    self._apply_game_mode()

  def _open_game_mode_settings(self):
    """Opens dialog to configure which metric items to show and their order in Game Mode."""
    dialog = GameModeSettingsDialog(
        self.game_mode_order, self.game_mode_items, self
    )
    if dialog.exec() == QDialog.DialogCode.Accepted:
      self.game_mode_order = dialog.get_full_order()
      self.game_mode_items = dialog.get_ordered_items()
      self._save_config()
      self._apply_game_mode()

  def mouseDoubleClickEvent(self, event):
    if event.button() == Qt.MouseButton.LeftButton:
      self.on_f9()
      event.accept()
    else:
      super().mouseDoubleClickEvent(event)

  def contextMenuEvent(self, event):
    """Right-click menu on the HUD overlay."""
    menu = QMenu(self)
    menu.setStyleSheet(f"""
            QMenu {{
                background-color: #181d28;
                color: #e2e8f0;
                border: 1px solid rgba(255, 255, 255, 0.15);
                border-radius: 8px;
                padding: 4px;
                font-family: {FONT_FAMILY};
                font-size: 12px;
            }}
            QMenu::item {{
                padding: 6px 18px;
                border-radius: 4px;
            }}
            QMenu::item:selected {{
                background-color: rgba(255, 255, 255, 0.12);
            }}
        """)
    if self.current_mode == "simple":
      act_mode = menu.addAction("◫ 切換至完整模式 [F9]")
      act_mode.triggered.connect(self.on_f9)
      act_game = menu.addAction("⊟ 切換至遊戲模式")
      act_game.triggered.connect(lambda: self._set_mode("game"))
    elif self.current_mode == "game":
      act_mode = menu.addAction("▬ 切換至極簡模式 [F9]")
      act_mode.triggered.connect(self.on_f9)
      act_full = menu.addAction("◫ 切換至完整模式")
      act_full.triggered.connect(lambda: self._set_mode("full"))
    else:
      act_mode = menu.addAction("⊟ 切換至遊戲模式 [F9]")
      act_mode.triggered.connect(self.on_f9)
      act_simple = menu.addAction("▬ 切換至極簡模式")
      act_simple.triggered.connect(lambda: self._set_mode("simple"))

    action_settings = menu.addAction("⚙ 指標顯示與排列設定...")
    action_settings.triggered.connect(
        lambda: QTimer.singleShot(0, self._open_game_mode_settings)
    )
    menu.addSeparator()

    # UI Scale submenu
    cur_scale_pct = int(round(self.ui_scale * 100))
    scale_menu = menu.addMenu(f"🔍 縮放大小 ({cur_scale_pct}%)")
    for sc in [0.75, 0.85, 1.0, 1.15, 1.30, 1.50, 1.75]:
      sc_pct = int(round(sc * 100))
      label = f"{sc_pct}% (預設)" if sc == 1.0 else f"{sc_pct}%"
      act_sc = scale_menu.addAction(label)
      act_sc.setCheckable(True)
      act_sc.setChecked(abs(self.ui_scale - sc) < 0.03)
      act_sc.triggered.connect(lambda checked, s=sc: self.set_ui_scale(s))

    # Opacity submenu
    cur_opacity_pct = int(round(self.opacity_val * 100))
    opacity_menu = menu.addMenu(f"👁 透明度 ({cur_opacity_pct}%)")
    for op in [1.0, 0.95, 0.85, 0.70, 0.55, 0.40]:
      op_pct = int(round(op * 100))
      label = (
          f"{op_pct}% (預設)"
          if op == 0.95
          else (f"{op_pct}% (不透明)" if op == 1.0 else f"{op_pct}%")
      )
      act_op = opacity_menu.addAction(label)
      act_op.setCheckable(True)
      act_op.setChecked(abs(self.opacity_val - op) < 0.03)
      act_op.triggered.connect(lambda checked, o=op: self.set_ui_opacity(o))

    if config.IS_DEV:
      menu.addSeparator()
      dev_menu = menu.addMenu("🛠️ 開發者選項")
      win_label = (
          self.target_window_name
          if len(self.target_window_name) <= 20
          else self.target_window_name[:18] + "..."
      )
      act_select_win = dev_menu.addAction(f"🎯 選擇擷取視窗... ({win_label})")
      act_select_win.triggered.connect(
          lambda: QTimer.singleShot(0, self._open_select_window_dialog)
      )

      if self.is_simulating:
        is_paused = self.video_worker.is_paused if self.video_worker else False
        pause_text = "▶ 繼續影片模擬" if is_paused else "⏸ 暫停影片模擬"
        act_sim_pause = dev_menu.addAction(pause_text)
        act_sim_pause.triggered.connect(self.toggle_simulation_pause)

        speed_menu = dev_menu.addMenu(f"⚡ 模擬速度 ({self.sim_speed:g}x)")
        for sp in [1.0, 2.0, 5.0, 10.0]:
          label = f"{sp:g}x (正常速度)" if sp == 1.0 else f"{sp:g}x"
          act_sp = speed_menu.addAction(label)
          act_sp.setCheckable(True)
          act_sp.setChecked(abs(self.sim_speed - sp) < 0.01)
          act_sp.triggered.connect(
              lambda checked, s=sp: self.set_simulation_speed(s)
          )

        act_stop_sim = dev_menu.addAction("⏹ 停止影片模擬 (切回視窗擷取)")
        act_stop_sim.triggered.connect(self.stop_video_simulation)

        act_load_other = dev_menu.addAction("📁 載入其他模擬影片...")
        act_load_other.triggered.connect(
            lambda: QTimer.singleShot(0, self._open_video_file_dialog)
        )
      else:
        default_clip = self.sim_video_path
        if not default_clip or not os.path.isfile(default_clip):
          sample = os.path.expanduser(
              r"~\Videos\Discord Clips\MapleStory_Worlds_0d11c233-b226-4d1d-952b-0c741acf61c2.mp4"
          )
          if os.path.isfile(sample):
            default_clip = sample

        if default_clip and os.path.isfile(default_clip):
          base_name = os.path.basename(default_clip)
          label = (
              f"▶ 快速模擬影片 ({base_name[:18]}...)"
              if len(base_name) > 21
              else f"▶ 快速模擬影片 ({base_name})"
          )
          act_quick_sim = dev_menu.addAction(label)
          act_quick_sim.triggered.connect(
              lambda checked, p=default_clip: self.start_video_simulation(
                  p, self.sim_speed
              )
          )

        act_load_sim = dev_menu.addAction("📁 載入模擬影片 (Simulate from Video)...")
        act_load_sim.triggered.connect(
            lambda: QTimer.singleShot(0, self._open_video_file_dialog)
        )

    menu.addSeparator()
    action_close = menu.addAction("✕ 關閉程式")
    action_close.triggered.connect(self.close)

    menu.exec(event.globalPos())

  def set_target_window(self, title: str, hwnd: Optional[int] = None):
    """Switches the capture target window."""
    if self.is_simulating:
      self.stop_video_simulation()
    self.target_window_name = title
    self.target_hwnd = hwnd
    if hasattr(self, "capture_worker") and self.capture_worker.isRunning():
      self.capture_worker.stop()
    self.capture_worker = CaptureWorker(self.target_window_name, self.target_hwnd)
    self.capture_worker.frame_parsed.connect(self._on_exp_sample)
    self.capture_worker.status_changed.connect(self._on_status_changed)
    self.capture_worker.start()
    self._save_config()

  def _open_select_window_dialog(self):
    """Opens dialog to choose any open window for live capture."""
    from dev.window_picker import SelectWindowDialog
    dlg = SelectWindowDialog(self.target_window_name, self.target_hwnd, None)
    if dlg.exec() == QDialog.DialogCode.Accepted:
      title, hwnd = dlg.get_selected()
      self.set_target_window(title, hwnd)

  def start_video_simulation(self, video_path: str, speed: float = 1.0) -> bool:
    """Switches capture mode from live window to video simulation."""
    if not os.path.isfile(video_path):
      return False
    if hasattr(self, "capture_worker") and self.capture_worker.isRunning():
      self.capture_worker.stop()
    if self.video_worker and self.video_worker.isRunning():
      self.video_worker.stop()

    from dev.video_simulation import VideoSimulationWorker

    self.is_simulating = True
    self.sim_speed = max(0.1, speed)
    self.sim_video_path = video_path

    self.video_worker = VideoSimulationWorker(
        video_path,
        playback_speed=self.sim_speed,
        loop=True,
        continuous_exp=True,
    )
    self.video_worker.frame_parsed.connect(self._on_exp_sample)
    self.video_worker.status_changed.connect(self._on_status_changed)
    self.video_worker.start()
    self._save_config()
    return True

  def stop_video_simulation(self):
    """Stops video simulation and returns to live window capture."""
    if self.video_worker and self.video_worker.isRunning():
      self.video_worker.stop()
    self.video_worker = None
    self.is_simulating = False
    self.sim_video_path = None

    if hasattr(self, "capture_worker") and not self.capture_worker.isRunning():
      self.capture_worker = CaptureWorker(
          self.target_window_name, self.target_hwnd
      )
      self.capture_worker.frame_parsed.connect(self._on_exp_sample)
      self.capture_worker.status_changed.connect(self._on_status_changed)
      self.capture_worker.start()
    self._save_config()

  def toggle_simulation_pause(self) -> bool:
    if self.video_worker and self.video_worker.isRunning():
      return self.video_worker.toggle_pause()
    return False

  def set_simulation_speed(self, speed: float):
    self.sim_speed = max(0.1, speed)
    if self.video_worker and self.video_worker.isRunning():
      self.video_worker.set_playback_speed(self.sim_speed)

  def _open_video_file_dialog(self):
    """Opens file picker to load a simulation video."""
    initial_dir = ""
    if self.sim_video_path and os.path.exists(
        os.path.dirname(self.sim_video_path)
    ):
      initial_dir = os.path.dirname(self.sim_video_path)
    else:
      videos_dir = os.path.expanduser(r"~\Videos")
      discord_clips = os.path.join(videos_dir, "Discord Clips")
      if os.path.isdir(discord_clips):
        initial_dir = discord_clips
      elif os.path.isdir(videos_dir):
        initial_dir = videos_dir

    file_path, _ = QFileDialog.getOpenFileName(
        None,
        "選擇 MapleStory / Artale 遊戲錄影影片",
        initial_dir,
        "影片檔案 (*.mp4 *.mkv *.avi *.mov);;所有檔案 (*.*)",
        options=QFileDialog.Option.DontUseNativeDialog,
    )
    if file_path:
      self.start_video_simulation(file_path, self.sim_speed)

  def _apply_game_mode(self):
    """Applies Full, Game, or Simple mode with custom ordering."""
    h_delta = self.header_widget.sizeHint().height() + self.card_layout.spacing()
    if self.current_mode != "game" and getattr(self, "_is_shifted_up", False):
      self.move(self.x(), self.y() + h_delta)
      self._is_shifted_up = False

    if self.current_mode == "simple":
      self.outer_card.is_pill = True

      # Hide all vertical components
      self.header_widget.hide()
      self.sub_widget.hide()
      self.sep1.hide()
      self.details_container.hide()
      self.slider_panel.hide()
      self.lbl_hotkey_hint.hide()

      # Set pill card padding: compact padding so the dot and content sit nicely inside the capsule curve
      pad_h = max(8, int(12 * self.ui_scale))
      pad_v = max(4, int(6 * self.ui_scale))
      self.card_layout.setContentsMargins(pad_h, pad_v, pad_h, pad_v)
      self.card_layout.setSpacing(0)

      # Hide all simple metric widgets first to avoid unmanaged widgets lingering at (0, 0)
      for w in self.simple_metric_widgets.values():
        w.hide()

      while self.simple_layout.count() > 0:
        item = self.simple_layout.takeAt(0)
        w = item.widget()
        if w:
          w.hide()

      self.simple_layout.setSpacing(0)

      # Status dot with compact, centered sizing
      dot_s = max(8, int(10 * self.ui_scale))
      dot_box = max(10, int(12 * self.ui_scale))
      self.simple_status_dot.setFixedSize(dot_box, dot_box)
      self.simple_status_dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
      dot_char = "●" if getattr(self, "_is_locked", False) else "○"
      dot_color = "#4ade80" if getattr(self, "_is_locked", False) else "#eab308"
      self.simple_status_dot.setText(dot_char)
      self.simple_status_dot.setStyleSheet(
          f"color: {dot_color}; font-size: {dot_s}px; background: transparent;"
      )
      self.simple_layout.addWidget(self.simple_status_dot)
      self.simple_status_dot.show()

      # Compact spacing between dot and the first metric (dot does not need excessive space)
      dot_space = max(3, int(6 * self.ui_scale))
      self.simple_layout.addSpacing(dot_space)

      active_keys = [
          k for k in DEFAULT_SIMPLE_MODE_KEYS if k in self.simple_metric_widgets
      ]
      inter_space = max(8, int(16 * self.ui_scale))
      for idx, key in enumerate(active_keys):
        w = self.simple_metric_widgets[key]
        self.simple_layout.addWidget(w)
        w.show()
        if idx < len(active_keys) - 1:
          self.simple_layout.addSpacing(inter_space)

      self.simple_widget.show()

      # Unlock fixed width and adjust to pill sizeHint
      self.setMinimumSize(0, 0)
      self.setMaximumSize(16777215, 16777215)
      self.card_layout.activate()
      self.layout().activate()
      self.adjustSize()
      self.setFixedSize(self.sizeHint())
      self.update()

    else:
      self.outer_card.is_pill = False
      self.simple_widget.hide()
      self.sub_widget.show()
      self.sep1.show()
      self.details_container.show()

      pad_h = max(8, int(14 * self.ui_scale))
      pad_v = max(6, int(12 * self.ui_scale))
      self.card_layout.setContentsMargins(pad_h, pad_v, pad_h, pad_v)
      self.card_layout.setSpacing(max(3, int(6 * self.ui_scale)))

      # Re-insert header and sub at standard positions 0 and 1
      self.card_layout.removeWidget(self.header_widget)
      self.card_layout.removeWidget(self.sub_widget)
      self.card_layout.insertWidget(0, self.header_widget)
      self.card_layout.insertWidget(1, self.sub_widget)

      # Detach details widgets
      for widget in self.metric_widgets.values():
        self.details_layout.removeWidget(widget)
        widget.hide()
      self.details_layout.removeWidget(self.sep_summary)
      self.sep_summary.hide()

      if self.current_mode == "game":
        self.setMinimumSize(0, 0)
        self.setMaximumSize(16777215, 16777215)
        self.setFixedWidth(int(290 * self.ui_scale))
        self.lbl_title.hide()
        self.btn_f9.setText("⊟")
        self.btn_f9.setToolTip("切換至極簡模式 [F9]")
        self.lbl_hotkey_hint.setText("[F7] 暫停  [F8] 重置  [F9] 極簡模式")

        for key in self.game_mode_items:
          if key in self.metric_widgets:
            widget = self.metric_widgets[key]
            self.details_layout.addWidget(widget)
            widget.show()
      else:
        self.setMinimumSize(0, 0)
        self.setMaximumSize(16777215, 16777215)
        self.setFixedWidth(int(340 * self.ui_scale))
        self.lbl_title.show()
        self.btn_f9.setText("◫")
        self.btn_f9.setToolTip("切換遊戲模式 [F9]")
        self.lbl_hotkey_hint.setText(
            "[F7] 開始/暫停  [F8] 重置  [F9] 遊戲模式"
        )

        for key in self.game_mode_order:
          if key in self.metric_widgets:
            widget = self.metric_widgets[key]
            self.details_layout.addWidget(widget)
            widget.show()

      self._update_focus_visibility()

    self._save_config()

  def _update_focus_visibility(self):
    """Updates visibility of focus-dependent components (sliders, and in game mode: header & hotkey footer)."""
    if self.current_mode == "simple":
      self.slider_panel.hide()
      self.header_widget.hide()
      self.lbl_hotkey_hint.hide()
      return

    is_active = self.isActiveWindow()

    # 1. Sliders: visible only when window is active (or dragging slider)
    if is_active:
      self.slider_panel.show()
    else:
      if not (self.slider_scale.isSliderDown() or self.slider_opacity.isSliderDown()):
        self.slider_panel.hide()

    # 2. In Game Mode: Header bar (badge + buttons) and Footer hotkey hint
    # are hidden when window loses focus, and shown when window has focus.
    # When expanding/collapsing at top, anchor window position so Auto Start and metrics never jump on screen.
    h_delta = self.header_widget.sizeHint().height() + self.card_layout.spacing()
    if self.current_mode == "game":
      if is_active:
        was_hidden = not self.header_widget.isVisible()
        self.header_widget.show()
        self.lbl_hotkey_hint.show()
        if was_hidden and not getattr(self, "_is_shifted_up", False):
          self.move(self.x(), self.y() - h_delta)
          self._is_shifted_up = True
      else:
        was_visible = self.header_widget.isVisible()
        self.header_widget.hide()
        self.lbl_hotkey_hint.hide()
        if was_visible and getattr(self, "_is_shifted_up", False):
          self.move(self.x(), self.y() + h_delta)
          self._is_shifted_up = False
    else:
      if getattr(self, "_is_shifted_up", False):
        self.move(self.x(), self.y() + h_delta)
        self._is_shifted_up = False
      self.header_widget.show()
      self.lbl_hotkey_hint.show()

    self.card_layout.activate()
    self.layout().activate()
    self.resize(self.width(), self.sizeHint().height())

  def _set_sliders_visible(self, visible: bool):
    """Explicitly show/hide sliders and update layout."""
    if visible:
      self.slider_panel.show()
    else:
      self.slider_panel.hide()
    self.card_layout.activate()
    self.layout().activate()
    self.resize(self.width(), self.sizeHint().height())

  def changeEvent(self, event):
    """Show/hide controls and sliders when window gains or loses focus."""
    if event.type() == QEvent.Type.ActivationChange:
      QTimer.singleShot(0, self._update_focus_visibility)
    super().changeEvent(event)

  def _on_slider_released(self):
    self._save_config()
    self._update_focus_visibility()

  def set_ui_scale(self, scale: float):
    """Sets UI scale safely and updates sliders, metrics, and window geometry."""
    self.ui_scale = max(0.50, min(2.00, round(scale, 2)))
    val_int = int(round(self.ui_scale * 100))
    if hasattr(self, "slider_scale"):
      self.slider_scale.blockSignals(True)
      self.slider_scale.setValue(val_int)
      self.slider_scale.blockSignals(False)
    if hasattr(self, "lbl_scale_val"):
      self.lbl_scale_val.setText(f"{val_int}%")
    self._apply_scaling()
    self._save_config()

  def set_ui_opacity(self, opacity: float):
    """Sets window opacity safely and updates sliders and window opacity."""
    self.opacity_val = max(0.20, min(1.00, round(opacity, 2)))
    self.setWindowOpacity(self.opacity_val)
    transparency_pct = int(round((1.0 - self.opacity_val) * 100))
    if hasattr(self, "slider_opacity"):
      self.slider_opacity.blockSignals(True)
      self.slider_opacity.setValue(transparency_pct)
      self.slider_opacity.blockSignals(False)
    if hasattr(self, "lbl_opacity_val"):
      self.lbl_opacity_val.setText(f"{transparency_pct}%")
    self._save_config()

  def _on_scale_changed(self, val: int):
    self.set_ui_scale(val / 100.0)

  def _on_opacity_changed(self, val: int):
    self.set_ui_opacity((100 - val) / 100.0)

  def wheelEvent(self, event):
    """Mouse wheel shortcuts: Ctrl+Wheel to scale, Shift/Alt+Wheel for opacity."""
    modifiers = event.modifiers()
    delta = event.angleDelta().y()
    if delta != 0:
      step = 0.05 if delta > 0 else -0.05
      if modifiers & Qt.KeyboardModifier.ControlModifier:
        self.set_ui_scale(self.ui_scale + step)
        event.accept()
        return
      elif modifiers & (Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.AltModifier):
        self.set_ui_opacity(self.opacity_val + step)
        event.accept()
        return
    super().wheelEvent(event)

  def _update_state_badge_style(self):
    s = self.ui_scale
    badge_size = max(8, int(11 * s))
    pad_v = max(1, int(2 * s))
    pad_h = max(4, int(7 * s))

    if self.engine.is_running:
      self.lbl_state_badge.setText("計時中")
      self.lbl_state_badge.setStyleSheet(f"""
          QLabel {{
              color: #34d399;
              background-color: rgba(16, 185, 129, 0.18);
              border: 1px solid rgba(52, 211, 153, 0.3);
              padding: {pad_v}px {pad_h}px;
              border-radius: 4px;
              font-size: {badge_size}px;
              font-weight: 700;
              font-family: {FONT_FAMILY};
          }}
      """)
    elif self.engine.is_paused:
      self.lbl_state_badge.setText("已暫停")
      self.lbl_state_badge.setStyleSheet(f"""
          QLabel {{
              color: #fbbf24;
              background-color: rgba(245, 158, 11, 0.18);
              border: 1px solid rgba(251, 191, 36, 0.3);
              padding: {pad_v}px {pad_h}px;
              border-radius: 4px;
              font-size: {badge_size}px;
              font-weight: 700;
              font-family: {FONT_FAMILY};
          }}
      """)
    else:
      self.lbl_state_badge.setText("待機中")
      self.lbl_state_badge.setStyleSheet(f"""
          QLabel {{
              color: #94a3b8;
              background-color: rgba(255, 255, 255, 0.08);
              padding: {pad_v}px {pad_h}px;
              border-radius: 4px;
              font-size: {badge_size}px;
              font-weight: 600;
              font-family: {FONT_FAMILY};
          }}
      """)

  def _apply_scaling(self):
    s = self.ui_scale
    if self.current_mode == "simple":
      pad_h = max(10, int(16 * s))
      pad_v = max(4, int(6 * s))
      self.card_layout.setContentsMargins(pad_h, pad_v, pad_h, pad_v)
      self.card_layout.setSpacing(0)
    else:
      base_w = 290 if self.current_mode == "game" else 340
      self.setFixedWidth(int(base_w * s))
      self.card_layout.setContentsMargins(
          max(6, int(14 * s)),
          max(6, int(12 * s)),
          max(6, int(14 * s)),
          max(6, int(12 * s)),
      )
      self.card_layout.setSpacing(max(3, int(6 * s)))
      self.details_layout.setSpacing(max(2, int(3 * s)))

    # 2. Metric rows
    for row in self.metric_widgets.values():
      if isinstance(row, MetricRow):
        row.update_scale(s)

    # 3. EXP Progress Bar height & style
    bar_h = max(6, int(8 * s))
    self.gauge_bar.setFixedHeight(bar_h)
    self.gauge_bar.setStyleSheet(f"""
        QProgressBar {{
            background-color: rgba(255, 255, 255, 0.08);
            border-radius: {max(2, int(4 * s))}px;
            border: none;
            margin-top: {max(1, int(3 * s))}px;
            margin-bottom: {max(1, int(3 * s))}px;
        }}
        QProgressBar::chunk {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #10b981, stop:1 #38bdf8);
            border-radius: {max(2, int(4 * s))}px;
        }}
    """)

    # 4. Title & State badge
    title_size = max(10, int(14 * s))
    self.lbl_title.setStyleSheet(f"""
        QLabel {{
            color: #e2e8f0;
            font-size: {title_size}px;
            font-weight: 700;
            letter-spacing: 0.5px;
            font-family: {FONT_FAMILY};
            background: transparent;
        }}
    """)
    self._update_state_badge_style()

    # 5. Header control buttons
    btn_size = max(18, int(24 * s))
    btn_font_size = max(9, int(12 * s))
    btn_font = QFont(self.btn_f7.font())
    btn_font.setPixelSize(btn_font_size)
    for btn in [
        self.btn_f7,
        self.btn_f8,
        self.btn_f9,
        self.btn_settings,
        self.btn_close,
    ]:
      btn.setFixedSize(btn_size, btn_size)
      btn.setFont(btn_font)

    # 6. Sub-header (status_dot, lbl_status, btn_auto_start)
    dot_size = max(10, int(13 * s))
    self.status_dot.setStyleSheet(
        f"color: {'#4ade80' if getattr(self, '_is_locked', False) else '#eab308'};"
        f" font-size: {dot_size}px; background: transparent;"
    )

    status_size = max(9, int(11 * s))
    self.lbl_status.setStyleSheet(f"""
        QLabel {{
            color: #64748b;
            font-size: {status_size}px;
            font-family: {FONT_FAMILY};
            background: transparent;
        }}
    """)

    auto_start_h = max(20, int(24 * s))
    auto_start_font_size = max(9, int(11 * s))
    self.btn_auto_start.setFixedHeight(auto_start_h)
    auto_font = QFont(self.btn_auto_start.font())
    auto_font.setPixelSize(auto_start_font_size)
    self.btn_auto_start.setFont(auto_font)

    # 7. Hotkey guidance footer
    hint_size = max(9, int(11 * s))
    self.lbl_hotkey_hint.setStyleSheet(f"""
        QLabel {{
            color: #64748b;
            font-size: {hint_size}px;
            font-family: {FONT_FAMILY};
            padding-top: {max(2, int(4 * s))}px;
            background: transparent;
        }}
    """)

    # 8. Sliders panel labels & handles
    slider_lbl_size = max(9, int(11 * s))
    val_w = max(28, int(36 * s))
    self.lbl_scale_val.setFixedWidth(val_w)
    self.lbl_opacity_val.setFixedWidth(val_w)
    self.slider_panel.setStyleSheet(f"""
        QFrame {{
            background: transparent;
            border: none;
            padding-top: 2px;
        }}
        QLabel {{
            color: #94a3b8;
            font-size: {slider_lbl_size}px;
            font-family: {FONT_FAMILY};
        }}
        QSlider::groove:horizontal {{
            height: {max(3, int(4 * s))}px;
            background: rgba(255, 255, 255, 0.15);
            border-radius: 2px;
        }}
        QSlider::sub-page:horizontal {{
            background: #10b981;
            border-radius: 2px;
        }}
        QSlider::handle:horizontal {{
            background: #34d399;
            border: 1px solid #ffffff;
            width: {max(10, int(12 * s))}px;
            height: {max(10, int(12 * s))}px;
            margin-top: -{max(3, int(4 * s))}px;
            margin-bottom: -{max(3, int(4 * s))}px;
            border-radius: {max(5, int(6 * s))}px;
        }}
        QSlider::handle:horizontal:hover {{
            background: #6ee7b7;
        }}
    """)

    # 9. Simple Mode items & dot
    if hasattr(self, "simple_metric_widgets"):
      for w in self.simple_metric_widgets.values():
        if isinstance(w, (SimpleMetricItem, SimpleProgressBarItem)):
          w.update_scale(s)
    if hasattr(self, "simple_status_dot"):
      dot_s = max(8, int(10 * s))
      dot_box = max(10, int(12 * s))
      self.simple_status_dot.setFixedSize(dot_box, dot_box)
      dot_char = "●" if getattr(self, "_is_locked", False) else "○"
      dot_color = "#4ade80" if getattr(self, "_is_locked", False) else "#eab308"
      self.simple_status_dot.setText(dot_char)
      self.simple_status_dot.setStyleSheet(
          f"color: {dot_color}; font-size: {dot_s}px; background: transparent;"
      )

    if self.current_mode == "simple":
      self._apply_game_mode()
    else:
      self.card_layout.activate()
      self.layout().activate()
      self.resize(self.width(), self.sizeHint().height())
    self._save_config()

  def keyPressEvent(self, event):
    if event.key() == Qt.Key.Key_F7:
      self.on_f7()
      event.accept()
    elif event.key() == Qt.Key.Key_F8:
      self.on_f8()
      event.accept()
    elif event.key() == Qt.Key.Key_F9:
      self.on_f9()
      event.accept()
    else:
      super().keyPressEvent(event)

  def _on_exp_sample(self, exp_val: int, exp_pct: float, dt_ms: float):
    pct_val = exp_pct if exp_pct >= 0 else None
    self.engine.add_sample(exp_val, pct_val)
    self._refresh_ui()

  def _on_status_changed(self, msg: str, is_locked: bool):
    self._is_locked = is_locked
    self.lbl_status.setText(msg)
    dot_size = max(10, int(13 * self.ui_scale))
    if is_locked:
      self.status_dot.setText("●")
      self.status_dot.setStyleSheet(
          f"color: #4ade80; font-size: {dot_size}px; background: transparent;"
      )
    else:
      self.status_dot.setText("○")
      self.status_dot.setStyleSheet(
          f"color: #eab308; font-size: {dot_size}px; background: transparent;"
      )
    if hasattr(self, "simple_status_dot"):
      dot_s = max(8, int(10 * self.ui_scale))
      dot_box = max(10, int(12 * self.ui_scale))
      self.simple_status_dot.setFixedSize(dot_box, dot_box)
      dot_char = "●" if is_locked else "○"
      dot_color = "#4ade80" if is_locked else "#eab308"
      self.simple_status_dot.setText(dot_char)
      self.simple_status_dot.setStyleSheet(
          f"color: {dot_color}; font-size: {dot_s}px; background: transparent;"
      )
      self.simple_status_dot.setToolTip(msg)

  def _refresh_ui(self):
    m = self.engine.get_metrics()

    # Update auto-start button appearance with engine state
    self._update_auto_start_button_style(self.engine.auto_start_enabled)

    # State Badge (scaled) & F7 button text
    self._update_state_badge_style()
    if self.engine.is_running:
      self.btn_f7.setText("⏸")
      self.btn_f7.set_custom_style(
          bg=QColor(239, 68, 68, 38),
          border=QColor(239, 68, 68, 80),
          text_color=QColor("#f87171"),
      )
    elif self.engine.is_paused:
      self.btn_f7.setText("▶")
      self.btn_f7.set_custom_style(
          bg=QColor(16, 185, 129, 38),
          border=QColor(52, 211, 153, 80),
          text_color=QColor("#34d399"),
      )
    else:
      self.btn_f7.setText("▶")
      self.btn_f7.set_custom_style(None, None, None)

    # Values in detailed mode (same rows are reused in game mode!)
    self.row_duration.set_value(m["練功時長"])
    self.row_current.set_value(m["當前經驗"])
    accum_val = m.get("total_gained_exp", 0)
    accum_color = get_accum_exp_color(accum_val)
    self.row_accum.set_value(m["累計經驗"], color=accum_color)
    self.row_1m.set_value(m["1分鐘經驗"])
    self.row_est_10m.set_value(m["預估10分"])
    self.row_acc_10m.set_value(m["累積10分"])
    self.row_est_60m.set_value(m["預估60分"])
    self.row_acc_60m.set_value(m["累積60分"])
    self.row_eta.set_value(m["升級預估時間"])

    # Gauge Progress Bar
    if "raw_pct" in m and m["raw_pct"] is not None:
      val_100x = int(m["raw_pct"] * 100)
      self.gauge_bar.setValue(min(10000, max(0, val_100x)))

    # Simple Mode metrics
    if hasattr(self, "simple_metric_widgets"):
      if "練功時長" in self.simple_metric_widgets:
        self.simple_metric_widgets["練功時長"].set_value(m.get("練功時長", "00:00:00"))
      if "預估10分" in self.simple_metric_widgets:
        val_10m = m.get("proj_10m_exp", 0)
        self.simple_metric_widgets["預估10分"].set_value(format_chinese_exp(val_10m))
      if "累計經驗" in self.simple_metric_widgets:
        val_accum = m.get("total_gained_exp", 0)
        self.simple_metric_widgets["累計經驗"].set_value(
            format_chinese_exp(val_accum), color=accum_color
        )
      for k, w in self.simple_metric_widgets.items():
        if k in ("練功時長", "預估10分", "累計經驗"):
          continue
        if isinstance(w, SimpleMetricItem):
          if k in m:
            w.set_value(m[k])
        elif isinstance(w, SimpleProgressBarItem):
          if "raw_pct" in m and m["raw_pct"] is not None:
            w.set_value(int(m["raw_pct"] * 100))

  # Mouse dragging
  def mousePressEvent(self, event):
    if not self.isActiveWindow():
      self.activateWindow()
    self._update_focus_visibility()
    if event.button() == Qt.MouseButton.LeftButton:
      self.drag_position = (
          event.globalPosition().toPoint() - self.frameGeometry().topLeft()
      )
      event.accept()

  def mouseMoveEvent(self, event):
    if event.buttons() == Qt.MouseButton.LeftButton:
      self.move(event.globalPosition().toPoint() - self.drag_position)
      event.accept()

  def mouseReleaseEvent(self, event):
    self._save_config()

  def _load_config(self):
    try:
      if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
          cfg = json.load(f)
          x, y = cfg.get("x", 120), cfg.get("y", 120)
          self.move(x, y)
          if "ui_mode" in cfg:
            self.current_mode = cfg["ui_mode"]
          elif cfg.get("is_game_mode", False):
            self.current_mode = "game"
          else:
            self.current_mode = "full"
          self.game_mode_order = cfg.get(
              "game_mode_order", list(ALL_METRIC_KEYS)
          )
          for k in ALL_METRIC_KEYS:
            if k not in self.game_mode_order:
              self.game_mode_order.append(k)
          self.game_mode_items = cfg.get(
              "game_mode_items", list(DEFAULT_GAME_MODE_KEYS)
          )
          self.ui_scale = cfg.get("ui_scale", 1.0)
          self.opacity_val = cfg.get("opacity", 0.95)
          self.target_window_name = cfg.get(
              "target_window_name", "MapleStory Worlds-Artale"
          )
          self.target_hwnd = cfg.get("target_hwnd", None)
          self.sim_video_path = cfg.get("sim_video_path", None)
          self.sim_speed = cfg.get("sim_speed", 1.0)
          self.setWindowOpacity(self.opacity_val)
          self.slider_scale.setValue(int(round(self.ui_scale * 100)))
          transparency_pct = int(round((1.0 - self.opacity_val) * 100))
          self.slider_opacity.setValue(transparency_pct)
          self.lbl_scale_val.setText(f"{int(round(self.ui_scale * 100))}%")
          self.lbl_opacity_val.setText(f"{transparency_pct}%")
          self._apply_scaling()
          self._apply_game_mode()
      else:
        self.move(120, 120)
        self._apply_game_mode()
    except Exception:
      self.move(120, 120)
      self._apply_game_mode()

  def _save_config(self):
    try:
      pos_y = self.pos().y()
      if getattr(self, "_is_shifted_up", False):
        h_delta = self.header_widget.sizeHint().height() + self.card_layout.spacing()
        pos_y += h_delta
      cfg = {
          "x": self.pos().x(),
          "y": pos_y,
          "ui_mode": self.current_mode,
          "is_game_mode": self.is_game_mode,
          "game_mode_order": self.game_mode_order,
          "game_mode_items": self.game_mode_items,
          "ui_scale": getattr(self, "ui_scale", 1.0),
          "opacity": getattr(self, "opacity_val", 0.95),
          "target_window_name": getattr(
              self, "target_window_name", "MapleStory Worlds-Artale"
          ),
          "target_hwnd": getattr(self, "target_hwnd", None),
          "sim_video_path": getattr(self, "sim_video_path", None),
          "sim_speed": getattr(self, "sim_speed", 1.0),
      }
      with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    except Exception:
      pass

  def closeEvent(self, event):
    self._save_config()
    if hasattr(self, "hotkey_worker") and self.hotkey_worker.isRunning():
      self.hotkey_worker.stop()
    if hasattr(self, "capture_worker") and self.capture_worker.isRunning():
      self.capture_worker.stop()
    if (
        hasattr(self, "video_worker")
        and self.video_worker
        and self.video_worker.isRunning()
    ):
      self.video_worker.stop()
    event.accept()
    qapp = QApplication.instance()
    if qapp:
      qapp.quit()


def main(
    video_path: Optional[str] = None,
    speed: float = 1.0,
    window_name: Optional[str] = None,
):
  try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
  except Exception:
    pass

  app = QApplication(sys.argv)
  app.setQuitOnLastWindowClosed(False)

  # Configure font with anti-aliasing preference
  font = QFont()
  font.setFamilies([
      "Google Sans",
      "PingFang TC",
      "PingFang HK",
      "Microsoft JhengHei UI",
      "Segoe UI",
      "sans-serif",
  ])
  font.setPointSize(10)
  font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
  font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
  app.setFont(font)

  overlay = ArtaleExpOverlay()
  if window_name:
    overlay.set_target_window(window_name)

  if video_path:
    if video_path == "prompt":
      QTimer.singleShot(100, overlay._open_video_file_dialog)
    else:
      overlay.start_video_simulation(video_path, speed=speed)

  overlay.show()
  sys.exit(app.exec())


if __name__ == "__main__":
  main()

