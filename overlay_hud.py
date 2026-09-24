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
from typing import List, Optional

from PyQt6.QtCore import (
    QEvent,
    QPoint,
    QRectF,
    Qt,
    QThread,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QCursor,
    QFont,
    QFontDatabase,
    QPainter,
    QPen,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

import exp_core
from metrics_engine import ExpMetricsEngine, MeasurementState

CONFIG_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "hud_config.json"
)

FONT_FAMILY = (
    "'Google Sans', 'Google Sans Medium', 'PingFang TC', 'PingFang HK',"
    " -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Microsoft JhengHei UI',"
    " 'Microsoft JhengHei', sans-serif"
)

ALL_METRIC_KEYS = [
    "練功時長",
    "1分鐘經驗",
    "預估10分",
    "累積10分",
    "預估60分",
    "累積60分",
    "累計經驗",
    "當前經驗",
    "升級預估時間",
    "EXP 進度條",
]

DEFAULT_GAME_MODE_KEYS = [
    "練功時長",
    "預估10分",
    "預估60分",
    "累計經驗",
    "升級預估時間",
]

SIMPLE_METRIC_CONFIG = {
    "練功時長": {"label": "時長", "color": "#94a3b8"},
    "1分鐘經驗": {"label": "1分", "color": "#38bdf8"},
    "預估10分": {"label": "預估10分", "color": "#38bdf8"},
    "累積10分": {"label": "累積10分", "color": "#818cf8"},
    "預估60分": {"label": "預估60分", "color": "#60a5fa"},
    "累積60分": {"label": "累積60分", "color": "#818cf8"},
    "累計經驗": {"label": "累計經驗", "color": "#c084fc"},
    "當前經驗": {"label": "當前", "color": "#fbbf24"},
    "升級預估時間": {"label": "升級預估", "color": "#34d399"},
}


def get_accum_exp_color(val: int) -> str:
  """Returns 7-tier hex color for gained accumulated EXP:
  0 ~ 20M:    #FFFFFF (White)
  20 ~ 40M:   #FFCC00 (Gold)
  40 ~ 60M:   #66CCFF (Sky Blue)
  60 ~ 80M:   #FF80FF (Pink)
  80 ~ 100M:  #FFFF66 (Light Yellow)
  100 ~ 120M: #66FF00 (Lime Green)
  120M+:      #FF66CC (Rose Pink)
  """
  if val < 20_000_000:
    return "#FFFFFF"
  if val < 40_000_000:
    return "#FFCC00"
  if val < 60_000_000:
    return "#66CCFF"
  if val < 80_000_000:
    return "#FF80FF"
  if val < 100_000_000:
    return "#FFFF66"
  if val < 120_000_000:
    return "#66FF00"
  return "#FF66CC"


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
  """Reusable two-column key-value row for EXP metrics."""

  def __init__(
      self,
      title: str,
      default_val: str = "--",
      parent=None,
      is_highlight: bool = False,
  ):
    super().__init__(parent)
    self.is_highlight = is_highlight
    self.scale = 1.0
    self.current_color = None
    self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
    self.layout = QHBoxLayout(self)
    self.layout.setContentsMargins(6, 3, 6, 3)
    self.layout.setSpacing(10)

    self.lbl_title = QLabel(title)
    self.lbl_title.setStyleSheet(f"""
            QLabel {{
                color: #94a3b8;
                font-size: 13px;
                font-weight: 500;
                font-family: {FONT_FAMILY};
            }}
        """)

    self.lbl_value = QLabel(default_val)
    val_color = "#FFFFFF" if is_highlight else "#f1f5f9"
    font_size = "16px" if is_highlight else "15px"
    font_weight = "700" if is_highlight else "600"
    self.lbl_value.setStyleSheet(f"""
            QLabel {{
                color: {val_color};
                font-size: {font_size};
                font-weight: {font_weight};
                font-family: {FONT_FAMILY};
            }}
        """)
    self.lbl_value.setAlignment(
        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
    )

    self.layout.addWidget(self.lbl_title)
    self.layout.addStretch()
    self.layout.addWidget(self.lbl_value)

  def update_scale(self, scale: float):
    self.scale = scale
    title_size = max(9, int(13 * scale))
    val_size = max(11, int((16 if self.is_highlight else 15) * scale))
    val_color = (
        self.current_color
        if self.current_color
        else ("#FFFFFF" if self.is_highlight else "#f1f5f9")
    )
    font_weight = "700" if self.is_highlight else "600"
    self.layout.setContentsMargins(
        max(3, int(6 * scale)),
        max(2, int(3 * scale)),
        max(3, int(6 * scale)),
        max(2, int(3 * scale)),
    )
    self.lbl_title.setStyleSheet(f"""
            QLabel {{
                color: #94a3b8;
                font-size: {title_size}px;
                font-weight: 500;
                font-family: {FONT_FAMILY};
            }}
        """)
    self.lbl_value.setStyleSheet(f"""
            QLabel {{
                color: {val_color};
                font-size: {val_size}px;
                font-weight: {font_weight};
                font-family: {FONT_FAMILY};
            }}
        """)

  def set_value(self, val_str: str, color: Optional[str] = None):
    self.lbl_value.setText(val_str)
    if color != self.current_color:
      self.current_color = color
      val_size = max(11, int((16 if self.is_highlight else 15) * self.scale))
      font_weight = "700" if self.is_highlight else "600"
      fg_color = (
          color if color else ("#FFFFFF" if self.is_highlight else "#f1f5f9")
      )
      self.lbl_value.setStyleSheet(f"""
                QLabel {{
                    color: {fg_color};
                    font-size: {val_size}px;
                    font-weight: {font_weight};
                    font-family: {FONT_FAMILY};
                }}
            """)


class SmoothCard(QFrame):
  """Custom container frame rendering high-precision anti-aliased rounded card and border."""

  def __init__(self, parent=None):
    super().__init__(parent)
    self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    self.is_pill = False

  def paintEvent(self, event):
    painter = QPainter(self)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    rect = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
    bg_color = QColor(14, 18, 28, 245)
    border_color = QColor(255, 255, 255, 28)

    painter.setBrush(QBrush(bg_color))
    painter.setPen(QPen(border_color, 1.2))
    if getattr(self, "is_pill", False):
      radius = rect.height() / 2.0
      painter.drawRoundedRect(rect, radius, radius)
    else:
      painter.drawRoundedRect(rect, 12.0, 12.0)


class SimpleMetricItem(QWidget):
  """Horizontal label-value pair widget for Simple Mode."""

  def __init__(self, key: str, label_text: str, label_color: str, parent=None):
    super().__init__(parent)
    self.key = key
    self.label_color = label_color
    self.scale = 1.0
    self.current_val_color = "#f8fafc"

    self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    layout = QHBoxLayout(self)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)

    self.lbl_label = QLabel(label_text, self)
    self.lbl_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
    self.lbl_value = QLabel("--", self)
    self.lbl_value.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    layout.addWidget(self.lbl_label)
    layout.addWidget(self.lbl_value)
    self.update_scale(1.0)

  def update_scale(self, scale: float = 1.0):
    self.scale = scale
    lbl_font_size = max(9, int(12 * scale))
    val_font_size = max(10, int(13 * scale))
    self.layout().setSpacing(max(2, int(4 * scale)))
    self.lbl_label.setStyleSheet(f"""
        QLabel {{
            color: {self.label_color};
            font-size: {lbl_font_size}px;
            font-weight: 600;
            font-family: {FONT_FAMILY};
            background: transparent;
        }}
    """)
    self.lbl_value.setStyleSheet(f"""
        QLabel {{
            color: {self.current_val_color};
            font-size: {val_font_size}px;
            font-weight: 700;
            font-family: {FONT_FAMILY};
            background: transparent;
        }}
    """)

  update_style = update_scale

  def set_value(self, val_str: str, color: Optional[str] = None):
    self.lbl_value.setText(val_str)
    if color:
      self.current_val_color = color
    else:
      self.current_val_color = "#f8fafc"
    val_font_size = max(10, int(13 * self.scale))
    self.lbl_value.setStyleSheet(f"""
        QLabel {{
            color: {self.current_val_color};
            font-size: {val_font_size}px;
            font-weight: 700;
            font-family: {FONT_FAMILY};
            background: transparent;
        }}
    """)


class SimpleProgressBarItem(QWidget):
  """Horizontal progress bar item for Simple Mode."""

  def __init__(self, parent=None):
    super().__init__(parent)
    self.scale = 1.0
    self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    layout = QHBoxLayout(self)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)

    self.lbl_label = QLabel("進度", self)
    self.lbl_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    self.bar = QProgressBar(self)
    self.bar.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
    self.bar.setTextVisible(False)
    self.bar.setRange(0, 10000)
    self.bar.setValue(0)

    layout.addWidget(self.lbl_label)
    layout.addWidget(self.bar)
    self.update_scale(1.0)

  def update_scale(self, scale: float = 1.0):
    self.scale = scale
    lbl_font_size = max(9, int(12 * scale))
    bar_w = max(30, int(46 * scale))
    bar_h = max(4, int(6 * scale))
    radius = max(2, int(3 * scale))
    self.layout().setSpacing(max(2, int(4 * scale)))
    self.lbl_label.setStyleSheet(f"""
        QLabel {{
            color: #38bdf8;
            font-size: {lbl_font_size}px;
            font-weight: 600;
            font-family: {FONT_FAMILY};
            background: transparent;
        }}
    """)
    self.bar.setFixedSize(bar_w, bar_h)
    self.bar.setStyleSheet(f"""
        QProgressBar {{
            background-color: rgba(255, 255, 255, 0.12);
            border-radius: {radius}px;
            border: none;
        }}
        QProgressBar::chunk {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #10b981, stop:1 #38bdf8);
            border-radius: {radius}px;
        }}
    """)

  update_style = update_scale

  def set_value(self, val_100x: int):
    self.bar.setValue(min(10000, max(0, val_100x)))


class SmoothButton(QPushButton):
  """QPushButton with vector-smoothed anti-aliased rounded background and borders."""

  def __init__(self, text: str = "", parent=None, is_close: bool = False):
    super().__init__(text, parent)
    self.is_close = is_close
    self.is_hovered = False
    self.custom_bg = None
    self.custom_border = None
    self.custom_color = None
    self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

  def enterEvent(self, event):
    self.is_hovered = True
    self.update()
    super().enterEvent(event)

  def leaveEvent(self, event):
    self.is_hovered = False
    self.update()
    super().leaveEvent(event)

  def set_custom_style(
      self,
      bg: Optional[QColor] = None,
      border: Optional[QColor] = None,
      text_color: Optional[QColor] = None,
  ):
    self.custom_bg = bg
    self.custom_border = border
    self.custom_color = text_color
    self.update()

  def paintEvent(self, event):
    painter = QPainter(self)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

    rect = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
    radius = min(rect.width(), rect.height()) / 2.0

    if self.custom_bg:
      bg = self.custom_bg
      border = self.custom_border if self.custom_border else QColor(0, 0, 0, 0)
      fg = self.custom_color if self.custom_color else QColor("#ffffff")
      if self.is_hovered:
        bg = bg.lighter(130)
    elif self.is_close:
      bg = QColor(239, 68, 68, 200) if self.is_hovered else QColor(255, 255, 255, 0)
      border = QColor(239, 68, 68, 120) if self.is_hovered else QColor(255, 255, 255, 0)
      fg = QColor("#ffffff") if self.is_hovered else QColor("#94a3b8")
    else:
      bg = QColor(255, 255, 255, 35) if self.is_hovered else QColor(255, 255, 255, 12)
      border = QColor(255, 255, 255, 50) if self.is_hovered else QColor(255, 255, 255, 20)
      fg = QColor("#ffffff") if self.is_hovered else QColor("#94a3b8")

    painter.setBrush(QBrush(bg))
    painter.setPen(QPen(border, 1.0))
    painter.drawRoundedRect(rect, radius, radius)

    painter.setPen(fg)
    painter.setFont(self.font())
    painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.text())


class GameModeSettingsDialog(QDialog):
  """Dialog allowing the user to select and drag-reorder metrics for Game Mode."""

  def __init__(
      self, current_order: List[str], current_items: List[str], parent=None
  ):
    super().__init__(parent)
    self.setWindowTitle("遊戲模式設定")
    self.setModal(True)
    self.setFixedWidth(340)
    self.setStyleSheet(f"""
        QDialog {{
            background-color: #181d28;
            color: #e2e8f0;
            font-family: {FONT_FAMILY};
            font-size: 13px;
        }}
        QLabel {{
            color: #94a3b8;
            font-size: 12px;
        }}
        QListWidget {{
            background-color: #111827;
            color: #f1f5f9;
            border: 1px solid rgba(255, 255, 255, 0.15);
            border-radius: 6px;
            padding: 4px;
            outline: none;
        }}
        QListWidget::item {{
            padding: 6px 8px;
            border-radius: 4px;
            margin: 1px 0px;
        }}
        QListWidget::item:selected {{
            background-color: rgba(16, 185, 129, 0.25);
            color: #ffffff;
        }}
        QListWidget::item:hover {{
            background-color: rgba(255, 255, 255, 0.06);
        }}
        QListWidget::indicator {{
            width: 16px;
            height: 16px;
            border-radius: 4px;
            border: 1px solid rgba(255, 255, 255, 0.3);
            background-color: rgba(255, 255, 255, 0.05);
        }}
        QListWidget::indicator:checked {{
            background-color: #10b981;
            border-color: #34d399;
        }}
        QPushButton {{
            background-color: rgba(255, 255, 255, 0.1);
            color: #e2e8f0;
            border: 1px solid rgba(255, 255, 255, 0.15);
            border-radius: 6px;
            padding: 6px 12px;
            font-size: 12px;
            font-family: {FONT_FAMILY};
        }}
        QPushButton:hover {{
            background-color: rgba(255, 255, 255, 0.18);
        }}
    """)

    layout = QVBoxLayout(self)
    layout.setContentsMargins(18, 16, 18, 16)
    layout.setSpacing(10)

    lbl_title = QLabel("指標顯示與排列設定")
    lbl_title.setStyleSheet("color: #f1f5f9; font-weight: 700; font-size: 14px;")
    layout.addWidget(lbl_title)

    lbl_hint = QLabel(
        "可直接滑鼠拖曳或使用右側按鈕調整排列順序（完整模式與遊戲模式皆套用此順序）；左側勾選框決定是否於遊戲模式顯示："
    )
    lbl_hint.setWordWrap(True)
    layout.addWidget(lbl_hint)

    body_layout = QHBoxLayout()
    body_layout.setSpacing(8)

    self.list_widget = QListWidget(self)
    self.list_widget.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
    self.list_widget.setDefaultDropAction(Qt.DropAction.MoveAction)
    self.list_widget.setDragDropOverwriteMode(False)
    self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)

    for name in current_order:
      it = QListWidgetItem(name, self.list_widget)
      it.setFlags(
          Qt.ItemFlag.ItemIsEnabled
          | Qt.ItemFlag.ItemIsSelectable
          | Qt.ItemFlag.ItemIsUserCheckable
          | Qt.ItemFlag.ItemIsDragEnabled
      )
      it.setCheckState(
          Qt.CheckState.Checked if name in current_items else Qt.CheckState.Unchecked
      )

    body_layout.addWidget(self.list_widget)

    btn_vbox = QVBoxLayout()
    btn_vbox.setSpacing(6)
    btn_up = QPushButton("▲ 上移", self)
    btn_up.setToolTip("將選取的項目向上移動一位")
    btn_up.clicked.connect(lambda: self._move_item(-1))

    btn_down = QPushButton("▼ 下移", self)
    btn_down.setToolTip("將選取的項目向下移動一位")
    btn_down.clicked.connect(lambda: self._move_item(1))

    btn_vbox.addWidget(btn_up)
    btn_vbox.addWidget(btn_down)
    btn_vbox.addStretch()
    body_layout.addLayout(btn_vbox)

    layout.addLayout(body_layout)

    btn_bar = QHBoxLayout()
    btn_bar.setSpacing(8)

    btn_reset = QPushButton("恢復預設", self)
    btn_reset.setToolTip("重置為預設順序與顯示項目")
    btn_reset.clicked.connect(self._reset_defaults)

    btn_cancel = QPushButton("取消", self)
    btn_cancel.clicked.connect(self.reject)

    btn_save = QPushButton("確認套用", self)
    btn_save.setStyleSheet(
        "background-color: #10b981; color: #ffffff; font-weight: bold; border: 1px solid #059669;"
    )
    btn_save.clicked.connect(self.accept)

    btn_bar.addWidget(btn_reset)
    btn_bar.addStretch()
    btn_bar.addWidget(btn_cancel)
    btn_bar.addWidget(btn_save)
    layout.addLayout(btn_bar)

  def _move_item(self, direction: int):
    r = self.list_widget.currentRow()
    if r < 0:
      return
    nr = r + direction
    if 0 <= nr < self.list_widget.count():
      item = self.list_widget.takeItem(r)
      self.list_widget.insertItem(nr, item)
      self.list_widget.setCurrentRow(nr)

  def _reset_defaults(self):
    self.list_widget.clear()
    for name in ALL_METRIC_KEYS:
      it = QListWidgetItem(name, self.list_widget)
      it.setFlags(
          Qt.ItemFlag.ItemIsEnabled
          | Qt.ItemFlag.ItemIsSelectable
          | Qt.ItemFlag.ItemIsUserCheckable
          | Qt.ItemFlag.ItemIsDragEnabled
      )
      it.setCheckState(
          Qt.CheckState.Checked
          if name in DEFAULT_GAME_MODE_KEYS
          else Qt.CheckState.Unchecked
      )

  def get_ordered_items(self) -> List[str]:
    selected = [
        self.list_widget.item(i).text()
        for i in range(self.list_widget.count())
        if self.list_widget.item(i).checkState() == Qt.CheckState.Checked
    ]
    return selected if selected else list(DEFAULT_GAME_MODE_KEYS)

  def get_full_order(self) -> List[str]:
    return [
        self.list_widget.item(i).text()
        for i in range(self.list_widget.count())
    ]


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
    self.simple_layout.setSpacing(14)

    self.simple_status_dot = QLabel("●", self.simple_widget)
    self.simple_status_dot.setAttribute(
        Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
    )
    self.simple_status_dot.setStyleSheet(
        "color: #eab308; font-size: 10px; background: transparent;"
    )

    self.simple_metric_widgets = {}
    for key, cfg in SIMPLE_METRIC_CONFIG.items():
      self.simple_metric_widgets[key] = SimpleMetricItem(
          key, cfg["label"], cfg["color"], self.simple_widget
      )
    self.simple_metric_widgets["EXP 進度條"] = SimpleProgressBarItem(
        self.simple_widget
    )

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
    action_settings.triggered.connect(self._open_game_mode_settings)

    menu.addSeparator()
    action_close = menu.addAction("✕ 關閉程式")
    action_close.triggered.connect(self.close)

    menu.exec(event.globalPos())

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

      # Set pill card padding
      pad_h = max(10, int(16 * self.ui_scale))
      pad_v = max(4, int(6 * self.ui_scale))
      self.card_layout.setContentsMargins(pad_h, pad_v, pad_h, pad_v)
      self.card_layout.setSpacing(0)

      # Rebuild simple layout items in the user-selected game_mode_items order
      while self.simple_layout.count() > 0:
        item = self.simple_layout.takeAt(0)
        w = item.widget()
        if w:
          w.hide()

      self.simple_layout.addWidget(self.simple_status_dot)
      self.simple_status_dot.show()

      for key in self.game_mode_items:
        if key in self.simple_metric_widgets:
          w = self.simple_metric_widgets[key]
          self.simple_layout.addWidget(w)
          w.show()

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

  def _on_scale_changed(self, val: int):
    self.ui_scale = val / 100.0
    self.lbl_scale_val.setText(f"{val}%")
    self._apply_scaling()

  def _on_opacity_changed(self, val: int):
    # val is transparency percentage (0% to 80%)
    # Reversed to window opacity (1.0 down to 0.20)
    self.opacity_val = max(0.1, (100 - val) / 100.0)
    self.setWindowOpacity(self.opacity_val)
    self.lbl_opacity_val.setText(f"{val}%")

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
      dot_char = "●" if getattr(self, "_is_locked", False) else "○"
      dot_color = "#4ade80" if getattr(self, "_is_locked", False) else "#eab308"
      self.simple_status_dot.setText(dot_char)
      self.simple_status_dot.setStyleSheet(
          f"color: {dot_color}; font-size: {dot_s}px; background: transparent;"
      )
    if hasattr(self, "simple_layout"):
      self.simple_layout.setSpacing(max(8, int(14 * s)))

    self.card_layout.activate()
    self.layout().activate()
    if self.current_mode == "simple":
      self.setMinimumSize(0, 0)
      self.setMaximumSize(16777215, 16777215)
      self.adjustSize()
      self.setFixedSize(self.sizeHint())
      self.update()
    else:
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
      for k, w in self.simple_metric_widgets.items():
        if isinstance(w, SimpleMetricItem):
          if k == "累計經驗":
            w.set_value(m.get("累計經驗", "--"), color=accum_color)
          elif k in m:
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
    event.accept()


def main():
  try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
  except Exception:
    pass

  app = QApplication(sys.argv)

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
  overlay.show()
  sys.exit(app.exec())


if __name__ == "__main__":
  main()

