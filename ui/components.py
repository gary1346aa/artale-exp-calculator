"""Reusable vector-rendered UI widgets and controls for Artale EXP Calculator.

Complies with the Google Python Style Guide.
"""

import math
from typing import Optional, Union

from PyQt6.QtCore import QPointF, QRectF, QSize, QTimer, Qt
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QCursor,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
)
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QWidget,
)

import config


class StatusDotWidget(QLabel):
  """Lightweight antialiased status indicator circle supporting solid, hollow, and breathing states."""

  def __init__(self, size: int = 12, parent=None):
    super().__init__("●", parent)
    self._dot_size: int = size
    self._is_solid: bool = True
    self._color: QColor = QColor("#4ade80")
    self._is_breathing: bool = False
    self._breath_alpha: float = 1.0
    self._breath_step: float = 0.0

    self.setFixedSize(size, size)
    self.setAlignment(Qt.AlignmentFlag.AlignCenter)
    self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    self._breath_timer = QTimer(self)
    self._breath_timer.setInterval(40)  # ~25 FPS
    self._breath_timer.timeout.connect(self._on_breath_tick)

  def update_scale(self, size: int) -> None:
    """Updates the fixed bounding size of the dot."""
    self._dot_size = max(8, size)
    self.setFixedSize(self._dot_size, self._dot_size)
    self.setStyleSheet(
        f"color: {self._color.name()}; font-size: {self._dot_size}px; background: transparent;"
    )
    self.update()

  def set_state(
      self,
      is_solid: bool,
      color: Union[QColor, str],
      is_breathing: bool = False,
      tooltip: str = "",
  ) -> None:
    """Updates the state, color, breathing animation, and tooltip of the dot."""
    self._is_solid = is_solid
    self._color = QColor(color) if isinstance(color, str) else color
    self.setText("●" if is_solid else "○")
    self.setStyleSheet(
        f"color: {self._color.name()}; font-size: {self._dot_size}px; background: transparent;"
    )
    if tooltip:
      self.setToolTip(tooltip)

    if is_breathing != self._is_breathing:
      self._is_breathing = is_breathing
      if is_breathing:
        self._breath_step = math.pi / 2.0  # Start at full brightness (1.0)
        self._breath_alpha = 1.0
        self._breath_timer.start()
      else:
        self._breath_timer.stop()
        self._breath_alpha = 1.0
    self.update()

  def _on_breath_tick(self) -> None:
    self._breath_step += 0.14
    # Smooth sinusoidal breathing between 0.0 and 1.0
    self._breath_alpha = 0.50 + 0.50 * math.sin(self._breath_step)
    self.update()

  def paintEvent(self, event) -> None:
    if not self._is_breathing:
      super().paintEvent(event)
      return

    alpha = max(0.0, min(1.0, self._breath_alpha))
    if alpha <= 0.005:
      return

    painter = QPainter(self)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    col = QColor(self._color)
    col.setAlphaF(alpha)

    # Circle radius
    r = max(2.0, (self._dot_size - 4) / 2.0)
    cx = self.width() / 2.0
    cy = self.height() / 2.0

    if self._is_solid:
      painter.setPen(Qt.PenStyle.NoPen)
      painter.setBrush(QBrush(col))
      painter.drawEllipse(QPointF(cx, cy), r, r)
    else:
      pen = QPen(col, max(1.5, self._dot_size * 0.15))
      painter.setPen(pen)
      painter.setBrush(Qt.BrushStyle.NoBrush)
      painter.drawEllipse(QPointF(cx, cy), r, r)



class MetricRow(QFrame):
  """Two-column key-value display row for Standard and Game Mode cards."""

  def __init__(
      self,
      title: str,
      default_val: str = "--",
      parent=None,
      is_highlight: bool = False,
  ):
    super().__init__(parent)
    self.is_highlight: bool = is_highlight
    self.scale: float = 1.0
    self.current_color: Optional[str] = None
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
            font-family: {config.FONT_FAMILY};
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
            font-family: {config.FONT_FAMILY};
        }}
    """)
    self.lbl_value.setAlignment(
        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
    )

    self.layout.addWidget(self.lbl_title)
    self.layout.addStretch()
    self.layout.addWidget(self.lbl_value)

  def update_scale(self, scale: float) -> None:
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
            font-family: {config.FONT_FAMILY};
        }}
    """)
    self.lbl_value.setStyleSheet(f"""
        QLabel {{
            color: {val_color};
            font-size: {val_size}px;
            font-weight: {font_weight};
            font-family: {config.FONT_FAMILY};
        }}
    """)

  def set_value(self, val_str: str, color: Optional[str] = None) -> None:
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
              font-family: {config.FONT_FAMILY};
          }}
      """)


class SmoothCard(QFrame):
  """Container frame rendering anti-aliased rounded background and borders."""

  def __init__(self, parent=None):
    super().__init__(parent)
    self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    self.is_pill: bool = False

  def paintEvent(self, event) -> None:
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
  """Compact horizontal label-value widget for Simple Mode."""

  def __init__(
      self, key: str, label_text: str, label_color: str, parent=None
  ):
    super().__init__(parent)
    self.key: str = key
    self.label_color: str = label_color
    self.scale: float = 1.0
    self.current_val_color: str = "#f8fafc"

    self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    layout = QHBoxLayout(self)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)

    self.lbl_label = QLabel(label_text, self)
    self.lbl_label.setAttribute(
        Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
    )
    self.lbl_value = QLabel("--", self)
    self.lbl_value.setAttribute(
        Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
    )
    self.lbl_value.setAlignment(
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
    )

    layout.addWidget(self.lbl_label)
    layout.addWidget(self.lbl_value)
    self.update_scale(1.0)

  def update_scale(self, scale: float = 1.0) -> None:
    self.scale = scale
    lbl_font_size = max(9, int(12 * scale))
    val_font_size = max(10, int(13 * scale))
    self.layout().setSpacing(max(2, int(4 * scale)))
    val_min_w = max(45, int(76 * scale))
    self.lbl_value.setMinimumWidth(val_min_w)
    self.lbl_label.setStyleSheet(f"""
        QLabel {{
            color: {self.label_color};
            font-size: {lbl_font_size}px;
            font-weight: 600;
            font-family: {config.FONT_FAMILY};
            background: transparent;
        }}
    """)
    self.lbl_value.setStyleSheet(f"""
        QLabel {{
            color: {self.current_val_color};
            font-size: {val_font_size}px;
            font-weight: 700;
            font-family: {config.FONT_FAMILY};
            background: transparent;
        }}
    """)

  update_style = update_scale

  def set_value(self, val_str: str, color: Optional[str] = None) -> None:
    self.lbl_value.setText(val_str)
    self.current_val_color = color if color else "#f8fafc"
    val_font_size = max(10, int(13 * self.scale))
    self.lbl_value.setStyleSheet(f"""
        QLabel {{
            color: {self.current_val_color};
            font-size: {val_font_size}px;
            font-weight: 700;
            font-family: {config.FONT_FAMILY};
            background: transparent;
        }}
    """)


class SimpleProgressBarItem(QWidget):
  """Horizontal progress bar item for Simple Mode."""

  def __init__(self, parent=None):
    super().__init__(parent)
    self.scale: float = 1.0
    self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    layout = QHBoxLayout(self)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)

    self.lbl_label = QLabel("進度", self)
    self.lbl_label.setAttribute(
        Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
    )

    self.bar = QProgressBar(self)
    self.bar.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
    self.bar.setTextVisible(False)
    self.bar.setRange(0, 10000)
    self.bar.setValue(0)

    layout.addWidget(self.lbl_label)
    layout.addWidget(self.bar)
    self.update_scale(1.0)

  def update_scale(self, scale: float = 1.0) -> None:
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
            font-family: {config.FONT_FAMILY};
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

  def set_value(self, val_100x: int) -> None:
    self.bar.setValue(min(10000, max(0, val_100x)))


def draw_vector_icon(
    painter: QPainter,
    icon_name: str,
    cx: float,
    cy: float,
    color: QColor,
    size: float = 12.0,
) -> None:
  """Draws a unified geometric vector symbol with consistent line weight and optical centering."""
  pen_w = max(1.4, size * 0.14)
  pen = QPen(
      color,
      pen_w,
      Qt.PenStyle.SolidLine,
      Qt.PenCapStyle.RoundCap,
      Qt.PenJoinStyle.RoundJoin,
  )

  if icon_name == "play":
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(color))
    s = size * 0.44
    # Optical centering shift +0.8px to the right
    poly = [
        QPointF(cx - s * 0.8 + 0.8, cy - s),
        QPointF(cx + s * 1.1 + 0.8, cy),
        QPointF(cx - s * 0.8 + 0.8, cy + s),
    ]
    painter.drawPolygon(poly)

  elif icon_name == "pause":
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(color))
    bar_w = max(2.2, size * 0.24)
    bar_h = size * 0.85
    gap = max(2.4, size * 0.28)
    r = bar_w / 2.0
    painter.drawRoundedRect(
        QRectF(cx - gap / 2.0 - bar_w, cy - bar_h / 2.0, bar_w, bar_h), r, r
    )
    painter.drawRoundedRect(
        QRectF(cx + gap / 2.0, cy - bar_h / 2.0, bar_w, bar_h), r, r
    )

  elif icon_name == "reset":
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    r = size * 0.42
    path = QPainterPath()
    path.arcMoveTo(QRectF(cx - r, cy - r, r * 2, r * 2), 60)
    path.arcTo(QRectF(cx - r, cy - r, r * 2, r * 2), 60, -290)
    painter.drawPath(path)
    # Arrowhead
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(color))
    arr_s = max(2.2, size * 0.22)
    arrow = [
        QPointF(cx + r - arr_s * 0.3, cy - r * 0.3),
        QPointF(cx + r + arr_s * 0.8, cy - r * 0.8),
        QPointF(cx + r - arr_s * 0.3, cy - r * 1.3),
    ]
    painter.drawPolygon(arrow)

  elif icon_name in ("mode", "game_mode"):
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    box_w = size * 0.95
    box_h = size * 0.82
    painter.drawRoundedRect(
        QRectF(cx - box_w / 2.0, cy - box_h / 2.0, box_w, box_h), 1.8, 1.8
    )
    # Divider for card mode
    painter.drawLine(
        QPointF(cx - box_w * 0.08, cy - box_h / 2.0),
        QPointF(cx - box_w * 0.08, cy + box_h / 2.0),
    )

  elif icon_name == "simple_mode":
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    bar_w = size * 1.0
    bar_h = size * 0.44
    painter.drawRoundedRect(
        QRectF(cx - bar_w / 2.0, cy - bar_h / 2.0, bar_w, bar_h),
        bar_h / 2.0,
        bar_h / 2.0,
    )

  elif icon_name == "settings":
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    r_in = size * 0.22
    painter.drawEllipse(QPointF(cx, cy), r_in, r_in)
    r_out = size * 0.48
    for i in range(6):
      ang = i * math.pi / 3.0
      p1 = QPointF(
          cx + (r_in + 0.8) * math.cos(ang), cy + (r_in + 0.8) * math.sin(ang)
      )
      p2 = QPointF(cx + r_out * math.cos(ang), cy + r_out * math.sin(ang))
      painter.drawLine(p1, p2)

  elif icon_name == "close":
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    d = size * 0.36
    painter.drawLine(QPointF(cx - d, cy - d), QPointF(cx + d, cy + d))
    painter.drawLine(QPointF(cx - d, cy + d), QPointF(cx + d, cy - d))

  elif icon_name == "autostart":
    # Automotive Auto Start-Stop: Circular arrow with bold 'A'
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    r = size * 0.48
    path = QPainterPath()
    path.arcMoveTo(QRectF(cx - r, cy - r, r * 2, r * 2), 30)
    path.arcTo(QRectF(cx - r, cy - r, r * 2, r * 2), 30, 290)
    painter.drawPath(path)

    # Arrowhead
    end_pt = path.currentPosition()
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(color))
    s_arr = max(2.0, size * 0.20)
    painter.drawPolygon([
        end_pt + QPointF(-s_arr * 0.7, s_arr * 0.9),
        end_pt + QPointF(s_arr * 0.9, 0),
        end_pt + QPointF(-s_arr * 0.7, -s_arr * 0.9),
    ])

    # Bold 'A' in center
    a_font = QFont("Arial", max(7, int(size * 0.65)), QFont.Weight.Bold)
    painter.setFont(a_font)
    painter.setPen(color)
    painter.drawText(
        QRectF(cx - r, cy - r - 0.5, r * 2, r * 2),
        Qt.AlignmentFlag.AlignCenter,
        "A",
    )


class SmoothButton(QPushButton):
  """QPushButton with vector-smoothed anti-aliased background, vector icons, and hover states."""

  def __init__(
      self,
      text: str = "",
      parent=None,
      is_close: bool = False,
      icon_name: Optional[str] = None,
  ):
    super().__init__(text, parent)
    self.is_close: bool = is_close
    self.icon_name: Optional[str] = icon_name
    self.is_hovered: bool = False
    self.custom_bg: Optional[QColor] = None
    self.custom_border: Optional[QColor] = None
    self.custom_color: Optional[QColor] = None
    self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

  def set_icon_name(self, name: Optional[str]) -> None:
    """Sets the vector icon name ('play', 'pause', 'reset', 'game_mode', 'simple_mode', 'settings', 'close', 'autostart')."""
    self.icon_name = name
    self.update()

  def enterEvent(self, event) -> None:
    self.is_hovered = True
    self.update()
    super().enterEvent(event)

  def leaveEvent(self, event) -> None:
    self.is_hovered = False
    self.update()
    super().leaveEvent(event)

  def set_custom_style(
      self,
      bg: Optional[QColor] = None,
      border: Optional[QColor] = None,
      text_color: Optional[QColor] = None,
  ) -> None:
    self.custom_bg = bg
    self.custom_border = border
    self.custom_color = text_color
  def sizeHint(self) -> QSize:
    sh = super().sizeHint()
    if self.icon_name == "autostart":
      fm = self.fontMetrics()
      text_w = fm.horizontalAdvance(self.text())
      w = text_w + 36
      return QSize(max(sh.width(), w), max(sh.height(), 24))
    elif self.icon_name and not self.text():
      return QSize(24, 24)
    return sh

  def minimumSizeHint(self) -> QSize:
    return self.sizeHint()

  def paintEvent(self, event) -> None:
    painter = QPainter(self)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

    rect = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
    radius = min(rect.width(), rect.height()) / 2.0

    if self.custom_bg:
      bg = self.custom_bg
      border = (
          self.custom_border if self.custom_border else QColor(0, 0, 0, 0)
      )
      fg = self.custom_color if self.custom_color else QColor("#ffffff")
      if self.is_hovered:
        bg = bg.lighter(130)
    elif self.is_close:
      bg = (
          QColor(239, 68, 68, 200)
          if self.is_hovered
          else QColor(255, 255, 255, 0)
      )
      border = (
          QColor(239, 68, 68, 120)
          if self.is_hovered
          else QColor(255, 255, 255, 0)
      )
      fg = QColor("#ffffff") if self.is_hovered else QColor("#94a3b8")
    else:
      bg = (
          QColor(255, 255, 255, 35)
          if self.is_hovered
          else QColor(255, 255, 255, 12)
      )
      border = (
          QColor(255, 255, 255, 50)
          if self.is_hovered
          else QColor(255, 255, 255, 20)
      )
      fg = QColor("#ffffff") if self.is_hovered else QColor("#94a3b8")

    painter.setBrush(QBrush(bg))
    painter.setPen(QPen(border, 1.0))
    painter.drawRoundedRect(rect, radius, radius)

    cx = rect.center().x()
    cy = rect.center().y()

    if self.icon_name == "autostart":
      # Auto-start with automotive (A) symbol on left + text
      ic_size = min(rect.height() * 0.58, 14.0)
      ic_x = rect.left() + max(14.0, rect.height() * 0.58)
      draw_vector_icon(painter, "autostart", ic_x, cy, fg, ic_size)

      text_rect = QRectF(
          ic_x + ic_size * 0.5 + 6.0,
          rect.top(),
          rect.right() - (ic_x + ic_size * 0.5 + 6.0),
          rect.height(),
      )
      painter.setFont(self.font())
      painter.setPen(fg)
      painter.drawText(
          text_rect,
          Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
          self.text(),
      )
    elif self.icon_name:
      # Icon-only button: optically centered vector icon
      ic_size = min(rect.width(), rect.height()) * 0.52
      draw_vector_icon(painter, self.icon_name, cx, cy, fg, ic_size)
    else:
      painter.setPen(fg)
      painter.setFont(self.font())
      painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.text())
