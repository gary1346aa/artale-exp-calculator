"""Artale EXP Calculator - Modern Floating HUD Overlay (PyQt6).

Frameless, translucent, always-on-top, draggable gaming overlay
displaying real-time EXP acquisition metrics and level-up projections
in Traditional Chinese (繁體中文).
"""

import sys
import os
import time
import json
import ctypes
from typing import Optional

from PyQt6.QtCore import Qt, QPoint, QTimer, pyqtSignal, QThread
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QProgressBar, QGraphicsDropShadowEffect
)
from PyQt6.QtGui import QColor, QFont, QCursor

import exp_core
from metrics_engine import ExpMetricsEngine

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hud_config.json")


class CaptureWorker(QThread):
    frame_parsed = pyqtSignal(int, float, float)  # exp_val, exp_pct, latency_ms
    status_changed = pyqtSignal(str, bool)  # message, is_locked

    def __init__(self):
        super().__init__()
        self.running = True
        self.sample_interval = 1.0

    def run(self):
        # Configure desktop access on Windows for DWM capture
        if sys.platform == "win32":
            user32 = ctypes.windll.user32
            h_desk = user32.OpenDesktopW("Default", 0, False, 0x01FF)
            if h_desk:
                user32.SetThreadDesktop(h_desk)

        from windows_capture import WindowsCapture, Frame

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
                res_changed = (last_res != cur_res)
                if res_changed:
                    last_res = cur_res

                parsed = exp_core.parse_frame(bgr)
                if parsed:
                    if res_changed:
                        exp_core.save_crop_debug(bgr, parsed)

                    exp_val, pct, raw_str, dt_ms = parsed[:4]
                    self.frame_parsed.emit(exp_val, pct if pct is not None else -1.0, dt_ms)
                    self.status_changed.emit("即時監控中", True)
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
                    window_name="MapleStory Worlds-Artale"
                )
                capture.event(on_frame_arrived)
                capture.event(on_closed)
                capture.start()
            except Exception as e:
                time.sleep(2.0)

    def stop(self):
        self.running = False
        self.wait(1000)


class MetricRow(QFrame):
    """Reusable two-column key-value row for EXP metrics."""
    def __init__(self, title: str, default_val: str = "--", parent=None, is_highlight: bool = False):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 6, 2)
        layout.setSpacing(10)

        self.lbl_title = QLabel(title)
        self.lbl_title.setStyleSheet("color: #8c9ba5; font-size: 12px; font-weight: 500;")

        self.lbl_value = QLabel(default_val)
        val_color = "#4ade80" if is_highlight else "#f1f5f9"
        self.lbl_value.setStyleSheet(f"color: {val_color}; font-size: 13px; font-weight: 600; font-family: 'Consolas', 'Microsoft JhengHei UI';")
        self.lbl_value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        layout.addWidget(self.lbl_title)
        layout.addStretch()
        layout.addWidget(self.lbl_value)

    def set_value(self, val_str: str, color: Optional[str] = None):
        self.lbl_value.setText(val_str)
        if color:
            self.lbl_value.setStyleSheet(f"color: {color}; font-size: 13px; font-weight: 600; font-family: 'Consolas', 'Microsoft JhengHei UI';")


class ArtaleExpOverlay(QWidget):
    def __init__(self):
        super().__init__()
        self.engine = ExpMetricsEngine()
        self.is_compact = False
        self.drag_position = QPoint()

        self._init_window_flags()
        self._init_ui()
        self._load_config()

        # Update timer for session elapsed time (1Hz)
        self.ui_timer = QTimer(self)
        self.ui_timer.timeout.connect(self._refresh_ui)
        self.ui_timer.start(1000)

        # Background capture worker
        self.worker = CaptureWorker()
        self.worker.frame_parsed.connect(self._on_exp_sample)
        self.worker.status_changed.connect(self._on_status_changed)
        self.worker.start()

    def _init_window_flags(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def _init_ui(self):
        self.setFixedWidth(320)

        # Outer container with modern dark frosted styling
        self.outer_card = QFrame(self)
        self.outer_card.setObjectName("outerCard")
        self.outer_card.setStyleSheet("""
            QFrame#outerCard {
                background-color: rgba(18, 22, 31, 0.92);
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 12px;
            }
        """)

        # Drop shadow for depth
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setColor(QColor(0, 0, 0, 180))
        shadow.setOffset(0, 4)
        self.outer_card.setGraphicsEffect(shadow)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(self.outer_card)

        card_layout = QVBoxLayout(self.outer_card)
        card_layout.setContentsMargins(14, 12, 14, 14)
        card_layout.setSpacing(6)

        # --- Top Header ---
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 4)

        self.status_dot = QLabel("●")
        self.status_dot.setStyleSheet("color: #eab308; font-size: 12px;")

        self.lbl_title = QLabel("ARTALE 經驗計算機")
        self.lbl_title.setStyleSheet("color: #e2e8f0; font-size: 13px; font-weight: 700; letter-spacing: 0.5px;")

        self.btn_pause = QPushButton("⏸")
        self.btn_pause.setToolTip("暫停 / 繼續計時")
        self.btn_pause.setFixedSize(22, 22)
        self.btn_pause.setStyleSheet(self._button_style())
        self.btn_pause.clicked.connect(self._toggle_pause)

        self.btn_reset = QPushButton("↺")
        self.btn_reset.setToolTip("重置本次練功統計")
        self.btn_reset.setFixedSize(22, 22)
        self.btn_reset.setStyleSheet(self._button_style())
        self.btn_reset.clicked.connect(self._reset_session)

        self.btn_compact = QPushButton("▾")
        self.btn_compact.setToolTip("切換精簡 / 完整模式")
        self.btn_compact.setFixedSize(22, 22)
        self.btn_compact.setStyleSheet(self._button_style())
        self.btn_compact.clicked.connect(self._toggle_compact)

        self.btn_close = QPushButton("✕")
        self.btn_close.setToolTip("關閉程式")
        self.btn_close.setFixedSize(22, 22)
        self.btn_close.setStyleSheet(self._button_style(is_close=True))
        self.btn_close.clicked.connect(self.close)

        header_layout.addWidget(self.status_dot)
        header_layout.addWidget(self.lbl_title)
        header_layout.addStretch()
        header_layout.addWidget(self.btn_pause)
        header_layout.addWidget(self.btn_reset)
        header_layout.addWidget(self.btn_compact)
        header_layout.addWidget(self.btn_close)
        card_layout.addLayout(header_layout)

        # Status subtitle line
        self.lbl_status = QLabel("正在連線至遊戲...")
        self.lbl_status.setStyleSheet("color: #94a3b8; font-size: 11px; margin-bottom: 2px;")
        card_layout.addWidget(self.lbl_status)

        # Separator line
        sep1 = QFrame()
        sep1.setFrameShape(QFrame.Shape.HLine)
        sep1.setStyleSheet("background-color: rgba(255, 255, 255, 0.08); max-height: 1px;")
        card_layout.addWidget(sep1)

        # --- Primary Highlights (Duration & Current EXP) ---
        self.row_duration = MetricRow("練功時長", "00:00:00", self)
        self.row_current = MetricRow("當前經驗", "無資料", self)
        card_layout.addWidget(self.row_duration)
        card_layout.addWidget(self.row_current)

        # EXP Gauge Progress Bar
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
        card_layout.addWidget(self.gauge_bar)

        # Separator line
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet("background-color: rgba(255, 255, 255, 0.08); max-height: 1px; margin-top: 4px; margin-bottom: 2px;")
        card_layout.addWidget(sep2)

        # --- Detailed Metrics Body ---
        self.details_container = QWidget(self)
        details_layout = QVBoxLayout(self.details_container)
        details_layout.setContentsMargins(0, 0, 0, 0)
        details_layout.setSpacing(4)

        self.row_total = MetricRow("總獲得經驗", "+0 (+0.00%)", self, is_highlight=True)
        self.row_1m = MetricRow("1分鐘經驗", "+0 (+0.00%)", self)
        self.row_est_10m = MetricRow("預估10分", "+0 (+0.00%)", self)
        self.row_acc_10m = MetricRow("累積10分", "+0 (+0.00%)", self)
        self.row_est_60m = MetricRow("預估60分", "+0 (+0.00%)", self, is_highlight=True)
        self.row_acc_60m = MetricRow("累積60分", "+0 (+0.00%)", self)
        self.row_eta = MetricRow("升級預估時間", "尚未開始", self, is_highlight=True)

        details_layout.addWidget(self.row_total)
        details_layout.addWidget(self.row_1m)
        details_layout.addWidget(self.row_est_10m)
        details_layout.addWidget(self.row_acc_10m)
        details_layout.addWidget(self.row_est_60m)
        details_layout.addWidget(self.row_acc_60m)
        details_layout.addWidget(self.row_eta)

        card_layout.addWidget(self.details_container)

    def _button_style(self, is_close: bool = False) -> str:
        hover_bg = "rgba(239, 68, 68, 0.8)" if is_close else "rgba(255, 255, 255, 0.15)"
        return f"""
            QPushButton {{
                background-color: transparent;
                color: #94a3b8;
                border-radius: 11px;
                border: none;
                font-size: 11px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {hover_bg};
                color: #ffffff;
            }}
        """

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
        self.row_duration.set_value(m["練功時長"])
        self.row_current.set_value(m["當前經驗"])
        self.row_total.set_value(m["總獲得經驗"])
        self.row_1m.set_value(m["1分鐘經驗"])
        self.row_est_10m.set_value(m["預估10分"])
        self.row_acc_10m.set_value(m["累積10分"])
        self.row_est_60m.set_value(m["預估60分"])
        self.row_acc_60m.set_value(m["累積60分"])
        self.row_eta.set_value(m["升級預估時間"])

        # Progress bar
        if "raw_pct" in m and m["raw_pct"] is not None:
            val_100x = int(m["raw_pct"] * 100)
            self.gauge_bar.setValue(min(10000, max(0, val_100x)))

        # Pause button icon
        if m["is_paused"]:
            self.btn_pause.setText("▶")
            self.btn_pause.setStyleSheet("color: #f59e0b; background-color: rgba(245, 158, 11, 0.15); border-radius: 11px;")
        else:
            self.btn_pause.setText("⏸")
            self.btn_pause.setStyleSheet(self._button_style())

    def _toggle_pause(self):
        self.engine.toggle_pause()
        self._refresh_ui()

    def _reset_session(self):
        self.engine.reset_session()
        self.gauge_bar.setValue(0)
        self._refresh_ui()

    def _toggle_compact(self):
        self.is_compact = not self.is_compact
        if self.is_compact:
            self.details_container.hide()
            self.btn_compact.setText("▴")
        else:
            self.details_container.show()
            self.btn_compact.setText("▾")
        self.adjustSize()

    # Drag window anywhere
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
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
                    x, y = cfg.get("x", 100), cfg.get("y", 100)
                    self.move(x, y)
                    if cfg.get("is_compact", False):
                        self._toggle_compact()
            else:
                self.move(120, 120)
        except Exception:
            self.move(120, 120)

    def _save_config(self):
        try:
            cfg = {
                "x": self.pos().x(),
                "y": self.pos().y(),
                "is_compact": self.is_compact,
            }
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
        except Exception:
            pass

    def closeEvent(self, event):
        self._save_config()
        if hasattr(self, "worker") and self.worker.isRunning():
            self.worker.stop()
        event.accept()


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    app = QApplication(sys.argv)
    app.setFont(QFont("Microsoft JhengHei UI", 9))
    overlay = ArtaleExpOverlay()
    overlay.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
