"""Artale EXP Calculator - Modern Floating HUD Overlay (PyQt6).

Frameless, translucent, always-on-top, draggable gaming overlay
displaying real-time EXP acquisition metrics, measurement baselines,
session initial EXP, auto-start toggle, and F7/F8/F9 global hotkeys
in Google Sans and Traditional Chinese (繁體中文).
"""

import ctypes
import ctypes.wintypes
import json
import os
import sys
import time
from typing import Optional

from PyQt6.QtCore import QPoint, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QCursor, QFont, QFontDatabase
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

import exp_core
from metrics_engine import ExpMetricsEngine, MeasurementState

CONFIG_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "hud_config.json"
)

FONT_FAMILY = (
    "'Google Sans', 'Google Sans Medium', 'Segoe UI', 'Microsoft JhengHei UI',"
    " sans-serif"
)


class HotkeyWorker(QThread):
  """Global Windows hotkey listener for F7 (Start/Pause), F8 (Reset), F9 (Game Mode)."""

  f7_pressed = pyqtSignal()
  f8_pressed = pyqtSignal()
  f9_pressed = pyqtSignal()

  def __init__(self):
    super().__init__()
    self.running = True
    self.tid = 0

  def run(self):
    if sys.platform != "win32":
      return

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    self.tid = kernel32.GetCurrentThreadId()

    MOD_NOREPEAT = 0x4000
    VK_F7 = 0x76
    VK_F8 = 0x77
    VK_F9 = 0x78

    HOTKEY_ID_F7 = 1007
    HOTKEY_ID_F8 = 1008
    HOTKEY_ID_F9 = 1009

    user32.RegisterHotKey(0, HOTKEY_ID_F7, MOD_NOREPEAT, VK_F7)
    user32.RegisterHotKey(0, HOTKEY_ID_F8, MOD_NOREPEAT, VK_F8)
    user32.RegisterHotKey(0, HOTKEY_ID_F9, MOD_NOREPEAT, VK_F9)

    msg = ctypes.wintypes.MSG()
    while self.running:
      if user32.PeekMessageW(ctypes.byref(msg), 0, 0, 0, 1):  # PM_REMOVE
        if msg.message == 0x0312:  # WM_HOTKEY
          hk_id = msg.wParam
          if hk_id == HOTKEY_ID_F7:
            self.f7_pressed.emit()
          elif hk_id == HOTKEY_ID_F8:
            self.f8_pressed.emit()
          elif hk_id == HOTKEY_ID_F9:
            self.f9_pressed.emit()
        elif msg.message == 0x0012:  # WM_QUIT
          break
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))
      else:
        time.sleep(0.02)

    user32.UnregisterHotKey(0, HOTKEY_ID_F7)
    user32.UnregisterHotKey(0, HOTKEY_ID_F8)
    user32.UnregisterHotKey(0, HOTKEY_ID_F9)

  def stop(self):
    self.running = False
    if self.tid and sys.platform == "win32":
      ctypes.windll.user32.PostThreadMessageW(self.tid, 0x0012, 0, 0)
    self.wait(1000)


class CaptureWorker(QThread):
  """Background screen capture worker sampling at 1 FPS via Windows Graphics Capture."""

  frame_parsed = pyqtSignal(int, float, float)
  status_changed = pyqtSignal(str, bool)

  def __init__(self):
    super().__init__()
    self.running = True
    self.sample_interval = 1.0

  def run(self):
    if sys.platform == "win32":
      user32 = ctypes.windll.user32
      h_desk = user32.OpenDesktopW("Default", 0, False, 0x01FF)
      if h_desk:
        user32.SetThreadDesktop(h_desk)

    from windows_capture import Frame, WindowsCapture

    last_sample_time = 0.0
    last_res = None

    def on_frame_arrived(frame: Frame, capture_control):
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

        parsed = exp_core.parse_frame(bgr)
        if parsed:
          if res_changed:
            exp_core.save_crop_debug(bgr, parsed)

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

    while self.running:
      try:
        self.status_changed.emit("尋找 Artale 遊戲視窗...", False)
        capture = WindowsCapture(
            cursor_capture=False,
            draw_border=False,
            window_name="MapleStory Worlds-Artale",
        )
        capture.event(on_frame_arrived)
        capture.event(on_closed)
        capture.start()
      except Exception:
        time.sleep(2.0)

  def stop(self):
    self.running = False
    self.wait(1000)


class MetricRow(QFrame):
  """Reusable two-column key-value row for EXP metrics in Google Sans."""

  def __init__(
      self,
      title: str,
      default_val: str = "--",
      parent=None,
      is_highlight: bool = False,
  ):
    super().__init__(parent)
    layout = QHBoxLayout(self)
    layout.setContentsMargins(6, 2, 6, 2)
    layout.setSpacing(10)

    self.lbl_title = QLabel(title)
    self.lbl_title.setStyleSheet(f"""
            QLabel {{
                color: #94a3b8;
                font-size: 12px;
                font-weight: 500;
                font-family: {FONT_FAMILY};
            }}
        """)

    self.lbl_value = QLabel(default_val)
    val_color = "#4ade80" if is_highlight else "#f1f5f9"
    self.lbl_value.setStyleSheet(f"""
            QLabel {{
                color: {val_color};
                font-size: 13px;
                font-weight: 600;
                font-family: {FONT_FAMILY};
            }}
        """)
    self.lbl_value.setAlignment(
        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
    )

    layout.addWidget(self.lbl_title)
    layout.addStretch()
    layout.addWidget(self.lbl_value)

  def set_value(self, val_str: str, color: Optional[str] = None):
    self.lbl_value.setText(val_str)
    if color:
      self.lbl_value.setStyleSheet(f"""
                QLabel {{
                    color: {color};
                    font-size: 13px;
                    font-weight: 600;
                    font-family: {FONT_FAMILY};
                }}
            """)


class ArtaleExpOverlay(QWidget):
  """Main floating HUD overlay widget supporting Normal and Game Mode."""

  def __init__(self):
    super().__init__()
    self.engine = ExpMetricsEngine()
    self.is_game_mode = False
    self.drag_position = QPoint()

    self._init_window_flags()
    self._init_ui()
    self._load_config()

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
    self.capture_worker = CaptureWorker()
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
    self.setFixedWidth(320)

    # Outer container with modern dark frosted glass styling
    self.outer_card = QFrame(self)
    self.outer_card.setObjectName("outerCard")
    self.outer_card.setStyleSheet(f"""
            QFrame#outerCard {{
                background-color: rgba(18, 22, 31, 0.94);
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 12px;
                font-family: {FONT_FAMILY};
            }}
        """)

    shadow = QGraphicsDropShadowEffect(self)
    shadow.setBlurRadius(20)
    shadow.setColor(QColor(0, 0, 0, 180))
    shadow.setOffset(0, 4)
    self.outer_card.setGraphicsEffect(shadow)

    main_layout = QVBoxLayout(self)
    main_layout.setContentsMargins(0, 0, 0, 0)
    main_layout.addWidget(self.outer_card)

    self.card_layout = QVBoxLayout(self.outer_card)
    self.card_layout.setContentsMargins(14, 12, 14, 12)
    self.card_layout.setSpacing(6)

    # 1. Top Header Bar
    header_layout = QHBoxLayout()
    header_layout.setContentsMargins(0, 0, 0, 2)
    header_layout.setSpacing(6)

    self.status_dot = QLabel("●")
    self.status_dot.setStyleSheet("color: #eab308; font-size: 12px;")

    self.lbl_title = QLabel("ARTALE EXP")
    self.lbl_title.setStyleSheet(f"""
            QLabel {{
                color: #e2e8f0;
                font-size: 13px;
                font-weight: 700;
                letter-spacing: 0.5px;
                font-family: {FONT_FAMILY};
            }}
        """)

    # State Badge: [計時中] / [暫停] / [待機]
    self.lbl_state_badge = QLabel("待機中")
    self.lbl_state_badge.setStyleSheet(f"""
            QLabel {{
                color: #94a3b8;
                background-color: rgba(255, 255, 255, 0.08);
                padding: 2px 6px;
                border-radius: 4px;
                font-size: 10px;
                font-weight: 600;
                font-family: {FONT_FAMILY};
            }}
        """)

    # Auto Start Toggle Button
    self.btn_auto_start = QPushButton("⚡ 自動開始")
    self.btn_auto_start.setToolTip(
        "自動開始：開啟時，偵測到經驗值增加即自動開始計時 (F7暫停或F8重置時自動關閉一次)"
    )
    self.btn_auto_start.setFixedHeight(22)
    self.btn_auto_start.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
    self._update_auto_start_button_style(False)
    self.btn_auto_start.clicked.connect(self._toggle_auto_start)

    # Hotkey action buttons
    self.btn_f7 = QPushButton("▶")
    self.btn_f7.setToolTip("開始 / 暫停 [F7]")
    self.btn_f7.setFixedSize(22, 22)
    self.btn_f7.setStyleSheet(self._button_style())
    self.btn_f7.clicked.connect(self.on_f7)

    self.btn_f8 = QPushButton("↺")
    self.btn_f8.setToolTip("重置本次計時 (不重置啟動初始經驗) [F8]")
    self.btn_f8.setFixedSize(22, 22)
    self.btn_f8.setStyleSheet(self._button_style())
    self.btn_f8.clicked.connect(self.on_f8)

    self.btn_f9 = QPushButton("◫")
    self.btn_f9.setToolTip("切換遊戲簡約模式 [F9]")
    self.btn_f9.setFixedSize(22, 22)
    self.btn_f9.setStyleSheet(self._button_style())
    self.btn_f9.clicked.connect(self.on_f9)

    self.btn_close = QPushButton("✕")
    self.btn_close.setToolTip("關閉程式")
    self.btn_close.setFixedSize(22, 22)
    self.btn_close.setStyleSheet(self._button_style(is_close=True))
    self.btn_close.clicked.connect(self.close)

    header_layout.addWidget(self.status_dot)
    header_layout.addWidget(self.lbl_title)
    header_layout.addWidget(self.lbl_state_badge)
    header_layout.addStretch()
    header_layout.addWidget(self.btn_auto_start)
    header_layout.addWidget(self.btn_f7)
    header_layout.addWidget(self.btn_f8)
    header_layout.addWidget(self.btn_f9)
    header_layout.addWidget(self.btn_close)
    self.card_layout.addLayout(header_layout)

    # Subtitle / Status Message
    self.lbl_status = QLabel("正在連線至遊戲視窗...")
    self.lbl_status.setStyleSheet(f"""
            QLabel {{
                color: #64748b;
                font-size: 11px;
                font-family: {FONT_FAMILY};
                margin-bottom: 2px;
            }}
        """)
    self.card_layout.addWidget(self.lbl_status)

    # Separator
    self.sep1 = self._create_separator()
    self.card_layout.addWidget(self.sep1)

    # 2. Primary Highlights (Duration, Current, Baseline, Initial)
    self.row_duration = MetricRow("練功時長", "00:00:00", self)
    self.row_current = MetricRow("當前經驗", "無資料", self)
    self.row_baseline = MetricRow("本次基準", "無資料", self)
    self.row_initial = MetricRow("啟動初始", "無資料", self)

    self.card_layout.addWidget(self.row_duration)
    self.card_layout.addWidget(self.row_current)
    self.card_layout.addWidget(self.row_baseline)
    self.card_layout.addWidget(self.row_initial)

    # EXP Progress Bar
    self.gauge_bar = QProgressBar(self)
    self.gauge_bar.setFixedHeight(8)
    self.gauge_bar.setTextVisible(False)
    self.gauge_bar.setRange(0, 10000)
    self.gauge_bar.setValue(0)
    self.gauge_bar.setStyleSheet("""
            QProgressBar {
                background-color: rgba(255, 255, 255, 0.08);
                border-radius: 4px;
                border: none;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #10b981, stop:1 #38bdf8);
                border-radius: 4px;
            }
        """)
    self.card_layout.addWidget(self.gauge_bar)

    # 3. Game Mode Mini Summary Container (visible only in game mode)
    self.game_mode_container = QWidget(self)
    gm_layout = QVBoxLayout(self.game_mode_container)
    gm_layout.setContentsMargins(0, 4, 0, 0)
    gm_layout.setSpacing(2)

    self.lbl_gm_gained = QLabel("+0 (+0.00%)")
    self.lbl_gm_gained.setStyleSheet(f"""
            QLabel {{
                color: #4ade80;
                font-size: 14px;
                font-weight: 700;
                font-family: {FONT_FAMILY};
            }}
        """)
    self.lbl_gm_gained.setAlignment(Qt.AlignmentFlag.AlignCenter)

    self.lbl_gm_rate = QLabel("時薪預估: +0/h | 升級: 待機中")
    self.lbl_gm_rate.setStyleSheet(f"""
            QLabel {{
                color: #94a3b8;
                font-size: 11px;
                font-family: {FONT_FAMILY};
            }}
        """)
    self.lbl_gm_rate.setAlignment(Qt.AlignmentFlag.AlignCenter)

    gm_layout.addWidget(self.lbl_gm_gained)
    gm_layout.addWidget(self.lbl_gm_rate)
    self.card_layout.addWidget(self.game_mode_container)
    self.game_mode_container.hide()

    # Separator
    self.sep2 = self._create_separator()
    self.card_layout.addWidget(self.sep2)

    # 4. Detailed Metrics Body (hidden in game mode)
    self.details_container = QWidget(self)
    details_layout = QVBoxLayout(self.details_container)
    details_layout.setContentsMargins(0, 0, 0, 0)
    details_layout.setSpacing(3)

    self.row_total = MetricRow(
        "總獲得經驗", "+0 (+0.00%)", self, is_highlight=True
    )
    self.row_1m = MetricRow("1分鐘經驗", "+0 (+0.00%)", self)
    self.row_est_10m = MetricRow("預估10分", "+0 (+0.00%)", self)
    self.row_acc_10m = MetricRow("累積10分", "+0 (+0.00%)", self)
    self.row_est_60m = MetricRow(
        "預估60分", "+0 (+0.00%)", self, is_highlight=True
    )
    self.row_acc_60m = MetricRow("累積60分", "+0 (+0.00%)", self)
    self.row_eta = MetricRow("升級預估時間", "待機中", self, is_highlight=True)

    details_layout.addWidget(self.row_total)
    details_layout.addWidget(self.row_1m)
    details_layout.addWidget(self.row_est_10m)
    details_layout.addWidget(self.row_acc_10m)
    details_layout.addWidget(self.row_est_60m)
    details_layout.addWidget(self.row_acc_60m)
    details_layout.addWidget(self.row_eta)
    self.card_layout.addWidget(self.details_container)

    # 5. Hotkey Guidance Footer
    self.lbl_hotkey_hint = QLabel("[F7] 開始/暫停  [F8] 重置  [F9] 遊戲簡約")
    self.lbl_hotkey_hint.setStyleSheet(f"""
            QLabel {{
                color: #64748b;
                font-size: 10px;
                font-family: {FONT_FAMILY};
                padding-top: 4px;
            }}
        """)
    self.lbl_hotkey_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
    self.card_layout.addWidget(self.lbl_hotkey_hint)

  def _create_separator(self) -> QFrame:
    sep = QFrame()
    sep.setFrameShape(QFrame.Shape.HLine)
    sep.setStyleSheet(
        "background-color: rgba(255, 255, 255, 0.08); max-height: 1px;"
    )
    return sep

  def _button_style(self, is_close: bool = False) -> str:
    hover_bg = (
        "rgba(239, 68, 68, 0.8)" if is_close else "rgba(255, 255, 255, 0.15)"
    )
    return f"""
            QPushButton {{
                background-color: transparent;
                color: #94a3b8;
                border-radius: 11px;
                border: none;
                font-size: 11px;
                font-weight: bold;
                font-family: {FONT_FAMILY};
            }}
            QPushButton:hover {{
                background-color: {hover_bg};
                color: #ffffff;
            }}
        """

  def _update_auto_start_button_style(self, enabled: bool):
    if enabled:
      self.btn_auto_start.setText("⚡ 自動開始 [ON]")
      self.btn_auto_start.setStyleSheet(f"""
                QPushButton {{
                    background-color: rgba(16, 185, 129, 0.20);
                    color: #34d399;
                    border: 1px solid rgba(52, 211, 153, 0.40);
                    border-radius: 11px;
                    padding: 0 8px;
                    font-size: 10px;
                    font-weight: 700;
                    font-family: {FONT_FAMILY};
                }}
                QPushButton:hover {{
                    background-color: rgba(16, 185, 129, 0.35);
                    color: #ffffff;
                }}
            """)
    else:
      self.btn_auto_start.setText("⚡ 自動開始 [OFF]")
      self.btn_auto_start.setStyleSheet(f"""
                QPushButton {{
                    background-color: rgba(255, 255, 255, 0.06);
                    color: #64748b;
                    border: 1px solid rgba(255, 255, 255, 0.08);
                    border-radius: 11px;
                    padding: 0 8px;
                    font-size: 10px;
                    font-weight: 600;
                    font-family: {FONT_FAMILY};
                }}
                QPushButton:hover {{
                    background-color: rgba(255, 255, 255, 0.12);
                    color: #e2e8f0;
                }}
            """)

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
    """F9 Hotkey handler: Toggle Game Mode (simple HUD)."""
    self.is_game_mode = not self.is_game_mode
    self._apply_game_mode()

  def _apply_game_mode(self):
    if self.is_game_mode:
      self.setFixedWidth(280)
      self.row_baseline.hide()
      self.row_initial.hide()
      self.sep2.hide()
      self.details_container.hide()
      self.game_mode_container.show()
      self.btn_f9.setText("⊟")
      self.btn_f9.setToolTip("切換至完整面板模式 [F9]")
      self.lbl_hotkey_hint.setText("[F7]暫停 [F8]重置 [F9]完整模式")
    else:
      self.setFixedWidth(320)
      self.row_baseline.show()
      self.row_initial.show()
      self.sep2.show()
      self.details_container.show()
      self.game_mode_container.hide()
      self.btn_f9.setText("◫")
      self.btn_f9.setToolTip("切換遊戲簡約模式 [F9]")
      self.lbl_hotkey_hint.setText(
          "[F7] 開始/暫停  [F8] 重置  [F9] 遊戲簡約"
      )
    self.adjustSize()
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
    self.lbl_status.setText(msg)
    if is_locked:
      self.status_dot.setText("●")
      self.status_dot.setStyleSheet("color: #4ade80; font-size: 12px;")
    else:
      self.status_dot.setText("○")
      self.status_dot.setStyleSheet("color: #eab308; font-size: 12px;")

  def _refresh_ui(self):
    m = self.engine.get_metrics()

    # Update auto-start button appearance with engine state
    self._update_auto_start_button_style(self.engine.auto_start_enabled)

    # State Badge & F7 button text
    if self.engine.is_running:
      self.lbl_state_badge.setText("計時中")
      self.lbl_state_badge.setStyleSheet(f"""
                QLabel {{
                    color: #34d399;
                    background-color: rgba(16, 185, 129, 0.18);
                    border: 1px solid rgba(52, 211, 153, 0.3);
                    padding: 2px 6px;
                    border-radius: 4px;
                    font-size: 10px;
                    font-weight: 700;
                    font-family: {FONT_FAMILY};
                }}
            """)
      self.btn_f7.setText("⏸")
      self.btn_f7.setStyleSheet("""
                QPushButton {
                    background-color: rgba(239, 68, 68, 0.15);
                    color: #f87171;
                    border-radius: 11px;
                    border: none;
                    font-size: 11px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: rgba(239, 68, 68, 0.35);
                    color: #ffffff;
                }
            """)
    elif self.engine.is_paused:
      self.lbl_state_badge.setText("已暫停")
      self.lbl_state_badge.setStyleSheet(f"""
                QLabel {{
                    color: #fbbf24;
                    background-color: rgba(245, 158, 11, 0.18);
                    border: 1px solid rgba(251, 191, 36, 0.3);
                    padding: 2px 6px;
                    border-radius: 4px;
                    font-size: 10px;
                    font-weight: 700;
                    font-family: {FONT_FAMILY};
                }}
            """)
      self.btn_f7.setText("▶")
      self.btn_f7.setStyleSheet("""
                QPushButton {
                    background-color: rgba(16, 185, 129, 0.15);
                    color: #34d399;
                    border-radius: 11px;
                    border: none;
                    font-size: 11px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: rgba(16, 185, 129, 0.35);
                    color: #ffffff;
                }
            """)
    else:
      self.lbl_state_badge.setText("待機中")
      self.lbl_state_badge.setStyleSheet(f"""
                QLabel {{
                    color: #94a3b8;
                    background-color: rgba(255, 255, 255, 0.08);
                    padding: 2px 6px;
                    border-radius: 4px;
                    font-size: 10px;
                    font-weight: 600;
                    font-family: {FONT_FAMILY};
                }}
            """)
      self.btn_f7.setText("▶")
      self.btn_f7.setStyleSheet(self._button_style())

    # Values in detailed mode
    self.row_duration.set_value(m["練功時長"])
    self.row_current.set_value(m["當前經驗"])
    self.row_baseline.set_value(m["本次基準"])
    self.row_initial.set_value(m["啟動初始"])
    self.row_total.set_value(m["總獲得經驗"])
    self.row_1m.set_value(m["1分鐘經驗"])
    self.row_est_10m.set_value(m["預估10分"])
    self.row_acc_10m.set_value(m["累積10分"])
    self.row_est_60m.set_value(m["預估60分"])
    self.row_acc_60m.set_value(m["累積60分"])
    self.row_eta.set_value(m["升級預估時間"])

    # Values in game mode
    self.lbl_gm_gained.setText(f"獲得: {m['總獲得經驗']}")
    self.lbl_gm_rate.setText(
        f"時薪預估: {m['預估60分']} | 升級: {m['升級預估時間']}"
    )

    # Gauge Progress Bar
    if "raw_pct" in m and m["raw_pct"] is not None:
      val_100x = int(m["raw_pct"] * 100)
      self.gauge_bar.setValue(min(10000, max(0, val_100x)))

  # Mouse dragging
  def mousePressEvent(self, event):
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
          self.is_game_mode = cfg.get("is_game_mode", False)
          self._apply_game_mode()
      else:
        self.move(120, 120)
    except Exception:
      self.move(120, 120)

  def _save_config(self):
    try:
      cfg = {
          "x": self.pos().x(),
          "y": self.pos().y(),
          "is_game_mode": self.is_game_mode,
      }
      with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    except Exception:
      pass

  def closeEvent(self, event):
    self._save_config()
    if hasattr(self, "hotkey_worker") and self.hotkey_worker.isRunning():
      self.hotkey_worker.stop()
    if hasattr(self, "capture_worker") and self.capture_worker.isRunning():
      self.capture_worker.stop()
    event.accept()


def main():
  try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
  except Exception:
    pass

  app = QApplication(sys.argv)

  # Configure Google Sans font
  app.setFont(QFont("Google Sans", 9))

  overlay = ArtaleExpOverlay()
  overlay.show()
  sys.exit(app.exec())


if __name__ == "__main__":
  main()
