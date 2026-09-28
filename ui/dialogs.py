"""Settings dialogs for configuring metrics, ordering, and appearance.

Complies with the Google Python Style Guide.
"""

import logging
import os
import subprocess
import sys
import tempfile
from typing import List, Optional
from PyQt6.QtCore import QPointF, QRect, QRectF, QSize, Qt, QThread, QUrl, pyqtSignal
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QCursor,
    QDesktopServices,
    QFont,
    QFontDatabase,
    QFontMetricsF,
    QPainter,
    QPainterPath,
    QPen,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QApplication,
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSlider,
    QSpinBox,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

import config
from core.updater import (
    UpdateInfo,
    apply_update_and_restart,
    check_for_update,
    download_file,
)

logger = logging.getLogger(__name__)


def _ensure_dialog_fonts() -> None:
  """Ensures bundled Google Sans and PingFang TC fonts are registered in QFontDatabase."""
  if not QFontDatabase.families():
    return
  loaded_families = set(QFontDatabase.families())
  if "Google Sans" in loaded_families and "PingFang TC" in loaded_families:
    return
  fonts_dir = config.get_resource_path(os.path.join("assets", "fonts"))
  if os.path.isdir(fonts_dir):
    font_files = (
        ["GoogleSans.ttf"]
        if sys.platform == "darwin"
        else [
            "GoogleSans.ttf",
            "PingFangTC-Regular.otf",
            "PingFangTC-Medium.otf",
        ]
    )
    for fname in font_files:
      fpath = os.path.join(fonts_dir, fname)
      if os.path.isfile(fpath):
        QFontDatabase.addApplicationFont(fpath)


def _make_smooth_font(
    pixel_size: int = 12,
    weight: QFont.Weight = QFont.Weight.Normal,
    latin_first: bool = False,
) -> QFont:
  """Creates a QFont matching the main HUD's crisp PingFang TC / Google Sans rendering."""
  _ensure_dialog_fonts()
  font = QFont()
  if latin_first:
    font.setFamilies(["Google Sans", "PingFang TC", "sans-serif"])
  else:
    font.setFamilies(["PingFang TC", "Google Sans", "sans-serif"])
  font.setPixelSize(pixel_size)
  font.setWeight(weight)
  return font


def _apply_smooth_font_recursively(root: QWidget) -> None:
  """No-op placeholder; widgets explicitly configure their QFont via _make_smooth_font."""
  return


def _draw_smooth_checkbox_indicator(
    painter: QPainter,
    rect: QRectF,
    checked: bool,
    hovered: bool = False,
    enabled: bool = True,
) -> None:
  """Draws a vector-smoothed rounded checkbox indicator with an anti-aliased checkmark."""
  painter.save()
  painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

  if not enabled:
    bg = QColor(255, 255, 255, 8)
    border = QColor(255, 255, 255, 35)
  elif checked:
    bg = QColor("#10b981")
    border = QColor("#34d399")
  else:
    bg = QColor(255, 255, 255, 22 if hovered else 13)
    border = QColor(255, 255, 255, 110 if hovered else 76)

  painter.setBrush(QBrush(bg))
  painter.setPen(QPen(border, 1.2))
  painter.drawRoundedRect(rect, 4.0, 4.0)

  if checked:
    check_color = QColor("#ffffff") if enabled else QColor(255, 255, 255, 120)
    pen = QPen(
        check_color,
        1.8,
        Qt.PenStyle.SolidLine,
        Qt.PenCapStyle.RoundCap,
        Qt.PenJoinStyle.RoundJoin,
    )
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    cx = rect.x()
    cy = rect.y()
    w = rect.width()
    h = rect.height()
    path = QPainterPath()
    path.moveTo(cx + w * 0.26, cy + h * 0.52)
    path.lineTo(cx + w * 0.44, cy + h * 0.70)
    path.lineTo(cx + w * 0.75, cy + h * 0.32)
    painter.drawPath(path)

  painter.restore()


class SmoothCardFrame(QFrame):
  """Frame with vector-smoothed anti-aliased rounded background and border."""

  def __init__(
      self,
      bg_color: QColor = QColor("#111827"),
      border_color: QColor = QColor(255, 255, 255, 38),
      parent_bg: QColor = QColor("#181d28"),
      radius: float = 6.0,
      parent=None,
  ):
    super().__init__(parent)
    self._bg_color = bg_color
    self._border_color = border_color
    self._parent_bg = parent_bg
    self._radius = radius

  def paintEvent(self, event) -> None:
    painter = QPainter(self)
    painter.fillRect(self.rect(), self._parent_bg)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    rect = QRectF(self.rect()).adjusted(0.6, 0.6, -0.6, -0.6)
    painter.setBrush(QBrush(self._bg_color))
    painter.setPen(QPen(self._border_color, 1.1))
    painter.drawRoundedRect(rect, self._radius, self._radius)


class SmoothCheckBox(QCheckBox):
  """CheckBox with vector-smoothed indicator and unhinted anti-aliased text."""

  def __init__(self, text: str = "", parent=None):
    super().__init__(text, parent)
    self._hovered = False
    self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
    self.setFont(_make_smooth_font(12, QFont.Weight.Normal))
    self.setMinimumHeight(24)

  def enterEvent(self, event) -> None:
    self._hovered = True
    self.update()
    super().enterEvent(event)

  def leaveEvent(self, event) -> None:
    self._hovered = False
    self.update()
    super().leaveEvent(event)

  def sizeHint(self) -> QSize:
    fm = QFontMetricsF(self.font())
    text_w = int(fm.horizontalAdvance(self.text()))
    return QSize(16 + 8 + text_w + 8, max(24, int(fm.height() + 6)))

  def minimumSizeHint(self) -> QSize:
    return self.sizeHint()

  def hitButton(self, pos) -> bool:
    return self.rect().contains(pos)

  def paintEvent(self, event) -> None:
    painter = QPainter(self)
    painter.fillRect(self.rect(), QColor("#181d28"))
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

    h = self.height()
    ind_size = 16.0
    ind_rect = QRectF(1.0, (h - ind_size) / 2.0, ind_size, ind_size)
    _draw_smooth_checkbox_indicator(
        painter,
        ind_rect,
        checked=self.isChecked(),
        hovered=self._hovered,
        enabled=self.isEnabled(),
    )

    painter.setFont(self.font())
    text_color = QColor("#f1f5f9") if self.isEnabled() else QColor("#64748b")
    painter.setPen(text_color)
    text_rect = QRectF(
        ind_rect.right() + 8.0,
        0.0,
        self.width() - ind_rect.right() - 8.0,
        float(h),
    )
    painter.drawText(
        text_rect,
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        self.text(),
    )


class SmoothSpinBox(QSpinBox):
  """SpinBox with vector-smoothed rounded border and clean number-only input."""

  def __init__(self, parent=None):
    super().__init__(parent)
    self.setFrame(False)
    font = _make_smooth_font(12, QFont.Weight.Medium, latin_first=True)
    self.setFont(font)
    if self.lineEdit():
      self.lineEdit().setFont(font)
      self.lineEdit().setStyleSheet(
          "QLineEdit { background-color: #111827; color: #f1f5f9; border: none;"
          " selection-background-color: #0284c7; selection-color: #ffffff; }"
      )
    self.setStyleSheet(
        "QSpinBox { background: transparent; border: none; padding: 3px 6px; }"
    )

  def changeEvent(self, event) -> None:
    super().changeEvent(event)
    if self.lineEdit():
      col = "#f1f5f9" if self.isEnabled() else "#64748b"
      bg = "#111827" if self.isEnabled() else "#141b26"
      self.lineEdit().setStyleSheet(
          f"QLineEdit {{ background-color: {bg}; color: {col}; border: none;"
          " selection-background-color: #0284c7; selection-color: #ffffff; }"
      )
    self.update()

  def paintEvent(self, event) -> None:
    painter = QPainter(self)
    painter.fillRect(self.rect(), QColor("#181d28"))
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    rect = QRectF(self.rect()).adjusted(0.6, 0.6, -0.6, -0.6)
    if not self.isEnabled():
      bg = QColor("#141b26")
      border = QColor(255, 255, 255, 20)
    elif self.hasFocus() or (self.lineEdit() and self.lineEdit().hasFocus()):
      bg = QColor("#111827")
      border = QColor("#34d399")
    else:
      bg = QColor("#111827")
      border = QColor(255, 255, 255, 50)
    painter.setBrush(QBrush(bg))
    painter.setPen(QPen(border, 1.1))
    painter.drawRoundedRect(rect, 5.0, 5.0)
    painter.end()
    super().paintEvent(event)


class SmoothDialogButton(QPushButton):
  """PushButton with vector-smoothed rounded border, optional arrow icon, and unhinted font."""

  def __init__(
      self,
      text: str = "",
      parent=None,
      arrow: Optional[str] = None,
  ):
    super().__init__(text, parent)
    self._hovered = False
    self._arrow = arrow  # "up", "down", or None
    self._bg_color = QColor("#2a3140")
    self._hover_bg_color = QColor("#374052")
    self._border_color = QColor(255, 255, 255, 42)
    self._text_color = QColor("#e2e8f0")
    self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
    self.setFont(_make_smooth_font(12, QFont.Weight.Normal))
    self.setMinimumHeight(30)

  def set_color_scheme(
      self,
      bg: QColor,
      hover_bg: QColor,
      border: QColor,
      text_color: QColor = QColor("#ffffff"),
      bold: bool = False,
  ) -> None:
    self._bg_color = bg
    self._hover_bg_color = hover_bg
    self._border_color = border
    self._text_color = text_color
    weight = QFont.Weight.DemiBold if bold else QFont.Weight.Normal
    self.setFont(_make_smooth_font(12, weight))
    self.update()

  def enterEvent(self, event) -> None:
    self._hovered = True
    self.update()
    super().enterEvent(event)

  def leaveEvent(self, event) -> None:
    self._hovered = False
    self.update()
    super().leaveEvent(event)

  def sizeHint(self) -> QSize:
    fm = QFontMetricsF(self.font())
    label_text = self.text()
    if self._arrow and label_text.startswith(("▲ ", "▼ ")):
      label_text = label_text[2:]
    text_w = int(fm.horizontalAdvance(label_text))
    arrow_extra = 14 if self._arrow else 0
    return QSize(text_w + arrow_extra + 26, max(30, int(fm.height() + 12)))

  def minimumSizeHint(self) -> QSize:
    return self.sizeHint()

  def paintEvent(self, event) -> None:
    painter = QPainter(self)
    painter.fillRect(self.rect(), QColor("#181d28"))
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

    rect = QRectF(self.rect()).adjusted(0.6, 0.6, -0.6, -0.6)
    if not self.isEnabled():
      bg = QColor("#1e2431")
      border = QColor(255, 255, 255, 20)
      fg = QColor("#64748b")
    else:
      bg = self._hover_bg_color if self._hovered else self._bg_color
      border = self._border_color
      fg = self._text_color

    painter.setBrush(QBrush(bg))
    painter.setPen(QPen(border, 1.1))
    painter.drawRoundedRect(rect, 6.0, 6.0)

    painter.setFont(self.font())
    painter.setPen(fg)

    label_text = self.text()
    if self._arrow and label_text.startswith(("▲ ", "▼ ")):
      label_text = label_text[2:]

    if self._arrow:
      fm = QFontMetricsF(self.font())
      text_w = fm.horizontalAdvance(label_text)
      tri_w = 8.0
      tri_h = 5.5
      gap = 5.0
      total_w = tri_w + gap + text_w
      start_x = rect.center().x() - total_w / 2.0
      cy = rect.center().y()

      tri_cx = start_x + tri_w / 2.0
      path = QPainterPath()
      if self._arrow == "up":
        path.moveTo(tri_cx, cy - tri_h / 2.0)
        path.lineTo(tri_cx - tri_w / 2.0, cy + tri_h / 2.0)
        path.lineTo(tri_cx + tri_w / 2.0, cy + tri_h / 2.0)
      else:
        path.moveTo(tri_cx - tri_w / 2.0, cy - tri_h / 2.0)
        path.lineTo(tri_cx + tri_w / 2.0, cy - tri_h / 2.0)
        path.lineTo(tri_cx, cy + tri_h / 2.0)
      path.closeSubpath()
      painter.setPen(Qt.PenStyle.NoPen)
      painter.setBrush(QBrush(fg))
      painter.drawPath(path)

      painter.setPen(fg)
      text_rect = QRectF(
          start_x + tri_w + gap, rect.top(), text_w + 4.0, rect.height()
      )
      painter.drawText(
          text_rect,
          Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
          label_text,
      )
    else:
      painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, label_text)


class SmoothListDelegate(QStyledItemDelegate):
  """Custom delegate that paints list items and checkboxes with full vector antialiasing."""

  def __init__(self, parent=None):
    super().__init__(parent)
    self._font = _make_smooth_font(12, QFont.Weight.Normal)

  def sizeHint(self, option, index) -> QSize:
    return QSize(120, 28)

  def paint(self, painter: QPainter, option, index) -> None:
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

    item_rect = QRectF(option.rect).adjusted(2.0, 1.0, -2.0, -1.0)
    is_selected = bool(option.state & QStyle.StateFlag.State_Selected)
    is_hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)

    if is_selected:
      painter.setBrush(QBrush(QColor("#173a35")))
      painter.setPen(Qt.PenStyle.NoPen)
      painter.drawRoundedRect(item_rect, 4.5, 4.5)
    elif is_hovered:
      painter.setBrush(QBrush(QColor("#1c2434")))
      painter.setPen(Qt.PenStyle.NoPen)
      painter.drawRoundedRect(item_rect, 4.5, 4.5)

    check_state = index.data(Qt.ItemDataRole.CheckStateRole)
    is_checked = check_state == Qt.CheckState.Checked or check_state == 2
    ind_size = 16.0
    ind_rect = QRectF(
        item_rect.left() + 8.0,
        item_rect.center().y() - ind_size / 2.0,
        ind_size,
        ind_size,
    )
    _draw_smooth_checkbox_indicator(
        painter, ind_rect, checked=is_checked, hovered=is_hovered
    )

    text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
    painter.setFont(self._font)
    painter.setPen(QColor("#ffffff" if is_selected else "#f1f5f9"))
    text_rect = QRectF(
        ind_rect.right() + 9.0,
        item_rect.top(),
        item_rect.right() - ind_rect.right() - 12.0,
        item_rect.height(),
    )
    painter.drawText(
        text_rect,
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        text,
    )
    painter.restore()


class SmoothListWidget(QListWidget):
  """ListWidget with vector-smoothed outer rounded border and custom checkbox delegate."""

  def __init__(self, parent=None):
    super().__init__(parent)
    self.setFrameShape(QFrame.Shape.NoFrame)
    self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    self.setMouseTracking(True)
    self.setItemDelegate(SmoothListDelegate(self))
    self.setStyleSheet("""
        QListWidget {
            background-color: #111827;
            border: none;
            padding: 0px;
            outline: none;
        }
        QScrollBar:vertical {
            background: #111827;
            width: 8px;
            margin: 4px 2px 4px 2px;
        }
        QScrollBar::handle:vertical {
            background: rgba(255, 255, 255, 0.22);
            border-radius: 2px;
            min-height: 24px;
        }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
            height: 0px;
        }
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
            background: none;
        }
    """)

  def mousePressEvent(self, event) -> None:
    if event.button() == Qt.MouseButton.LeftButton:
      pos = event.pos()
      item = self.itemAt(pos)
      if item is not None:
        rect = self.visualItemRect(item)
        # Checkbox hit area on the left side of the row
        if rect.left() <= pos.x() <= rect.left() + 32:
          new_state = (
              Qt.CheckState.Unchecked
              if item.checkState() == Qt.CheckState.Checked
              else Qt.CheckState.Checked
          )
          item.setCheckState(new_state)
          self.setCurrentItem(item)
          self.viewport().update()
          event.accept()
          return
    super().mousePressEvent(event)


class SmoothSlider(QSlider):
  """Horizontal slider with vector-smoothed anti-aliased groove and circular handle."""

  def __init__(self, parent=None):
    super().__init__(Qt.Orientation.Horizontal, parent)
    self._hovered = False
    self.setFixedHeight(22)
    self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

  def enterEvent(self, event) -> None:
    self._hovered = True
    self.update()
    super().enterEvent(event)

  def leaveEvent(self, event) -> None:
    self._hovered = False
    self.update()
    super().leaveEvent(event)

  def paintEvent(self, event) -> None:
    painter = QPainter(self)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.fillRect(self.rect(), QColor("#181d28"))

    w = float(self.width())
    h = float(self.height())
    cy = h / 2.0
    r_handle = 6.0
    pad_x = r_handle + 2.0
    track_w = max(1.0, w - 2.0 * pad_x)
    track_h = 4.0

    val_range = max(1, self.maximum() - self.minimum())
    ratio = max(0.0, min(1.0, (self.value() - self.minimum()) / float(val_range)))
    hx = pad_x + ratio * track_w

    # Draw background groove
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(QColor(255, 255, 255, 38)))
    painter.drawRoundedRect(
        QRectF(pad_x, cy - track_h / 2.0, track_w, track_h), 2.0, 2.0
    )

    # Draw filled sub-page
    if hx > pad_x:
      painter.setBrush(QBrush(QColor("#10b981")))
      painter.drawRoundedRect(
          QRectF(pad_x, cy - track_h / 2.0, hx - pad_x, track_h), 2.0, 2.0
      )

    # Draw circular handle
    handle_col = QColor("#6ee7b7") if (self._hovered or self.isSliderDown()) else QColor("#34d399")
    painter.setBrush(QBrush(handle_col))
    painter.setPen(QPen(QColor("#ffffff"), 1.2))
    painter.drawEllipse(QPointF(hx, cy), r_handle, r_handle)


class GameModeSettingsDialog(QDialog):
  """Dialog allowing the user to select and reorder metrics, appearance, and auto-pause."""

  def __init__(
      self,
      current_order: List[str],
      current_items: List[str],
      parent=None,
      auto_pause_enabled: bool = config.DEFAULT_AUTO_PAUSE_ENABLED,
      auto_pause_seconds: int = config.DEFAULT_AUTO_PAUSE_SECONDS,
      ui_scale: float = 1.0,
      opacity_val: float = 0.95,
      base_width: int = config.DEFAULT_BASE_WIDTH,
      row_spacing: int = config.DEFAULT_ROW_SPACING,
      font_weight: int = config.DEFAULT_FONT_WEIGHT,
  ):
    super().__init__(parent)
    _ensure_dialog_fonts()
    self._overlay_parent = parent
    self._orig_scale = float(ui_scale)
    self._orig_opacity = float(opacity_val)
    self._orig_width = int(base_width)
    self._orig_spacing = int(row_spacing)
    self._orig_weight = int(font_weight)

    self.setWindowTitle("設定")
    self.setModal(True)
    self.setFixedWidth(360)
    self.setStyleSheet("""
        QDialog {
            background-color: #181d28;
            color: #e2e8f0;
        }
        QLabel {
            color: #94a3b8;
            background-color: #181d28;
        }
    """)

    layout = QVBoxLayout(self)
    layout.setContentsMargins(18, 16, 18, 16)
    layout.setSpacing(10)

    lbl_title = QLabel("指標顯示與排列設定", self)
    lbl_title.setFont(_make_smooth_font(14, QFont.Weight.Bold))
    lbl_title.setStyleSheet("color: #f1f5f9; background-color: #181d28;")
    layout.addWidget(lbl_title)

    lbl_hint = QLabel(
        "可直接滑鼠拖曳或使用右側按鈕調整排列順序（完整模式與遊戲模式皆套用此順序）；左側勾選框決定是否於遊戲模式顯示：",
        self,
    )
    lbl_hint.setFont(_make_smooth_font(12, QFont.Weight.Normal))
    lbl_hint.setWordWrap(True)
    layout.addWidget(lbl_hint)

    body_layout = QHBoxLayout()
    body_layout.setSpacing(8)

    list_card = SmoothCardFrame(
        bg_color=QColor("#111827"),
        border_color=QColor(255, 255, 255, 38),
        parent_bg=QColor("#181d28"),
        radius=6.0,
        parent=self,
    )
    list_card_layout = QVBoxLayout(list_card)
    list_card_layout.setContentsMargins(5, 5, 5, 5)
    list_card_layout.setSpacing(0)

    self.list_widget = SmoothListWidget(list_card)
    self.list_widget.setVerticalScrollBarPolicy(
        Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    )
    self.list_widget.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
    self.list_widget.setDefaultDropAction(Qt.DropAction.MoveAction)
    self.list_widget.setDragDropOverwriteMode(False)
    self.list_widget.setSelectionMode(
        QAbstractItemView.SelectionMode.SingleSelection
    )

    for name in current_order:
      it = QListWidgetItem(name, self.list_widget)
      it.setFlags(
          Qt.ItemFlag.ItemIsEnabled
          | Qt.ItemFlag.ItemIsSelectable
          | Qt.ItemFlag.ItemIsUserCheckable
          | Qt.ItemFlag.ItemIsDragEnabled
      )
      it.setCheckState(
          Qt.CheckState.Checked
          if name in current_items
          else Qt.CheckState.Unchecked
      )

    item_count = max(10, len(current_order))
    list_inner_h = item_count * 28 + 2
    self.list_widget.setFixedHeight(list_inner_h)
    list_card_layout.addWidget(self.list_widget)
    list_card.setFixedHeight(list_inner_h + 10)
    body_layout.addWidget(list_card)

    btn_vbox = QVBoxLayout()
    btn_vbox.setSpacing(6)
    btn_up = SmoothDialogButton("▲ 上移", self, arrow="up")
    btn_up.clicked.connect(lambda: self._move_item(-1))

    btn_down = SmoothDialogButton("▼ 下移", self, arrow="down")
    btn_down.clicked.connect(lambda: self._move_item(1))

    btn_vbox.addWidget(btn_up)
    btn_vbox.addWidget(btn_down)
    btn_vbox.addStretch()
    body_layout.addLayout(btn_vbox)

    layout.addLayout(body_layout)

    # Appearance & Typography section (縮放, 透明, 寬度, 行距, 字體粗細)
    sep_style = QWidget(self)
    sep_style.setFixedHeight(1)
    sep_style.setStyleSheet("background-color: rgba(255, 255, 255, 0.10);")
    layout.addWidget(sep_style)

    lbl_style_title = QLabel("外觀與排版設定", self)
    lbl_style_title.setFont(_make_smooth_font(13, QFont.Weight.Bold))
    lbl_style_title.setStyleSheet("color: #f1f5f9; background-color: #181d28;")
    layout.addWidget(lbl_style_title)

    sliders_vbox = QVBoxLayout()
    sliders_vbox.setSpacing(4)

    # 1. Scale slider (縮放: 50 ~ 200 %)
    row_sc = QHBoxLayout()
    row_sc.setSpacing(8)
    lbl_sc_name = QLabel("縮放", self)
    lbl_sc_name.setFixedWidth(56)
    self.slider_scale = SmoothSlider(self)
    self.slider_scale.setRange(50, 200)
    scale_pct = max(50, min(200, int(round(float(ui_scale) * 100))))
    self.slider_scale.setValue(scale_pct)
    self.lbl_scale_val = QLabel(f"{scale_pct}%", self)
    self.lbl_scale_val.setFixedWidth(48)
    self.lbl_scale_val.setAlignment(
        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
    )
    self.slider_scale.valueChanged.connect(self._on_scale_changed)
    row_sc.addWidget(lbl_sc_name)
    row_sc.addWidget(self.slider_scale, 1)
    row_sc.addWidget(self.lbl_scale_val)
    sliders_vbox.addLayout(row_sc)

    # 2. Transparency slider (透明: 0 ~ 80 %)
    row_op = QHBoxLayout()
    row_op.setSpacing(8)
    lbl_op_name = QLabel("透明", self)
    lbl_op_name.setFixedWidth(56)
    self.slider_opacity = SmoothSlider(self)
    self.slider_opacity.setRange(0, 80)
    trans_pct = max(0, min(80, int(round((1.0 - float(opacity_val)) * 100))))
    self.slider_opacity.setValue(trans_pct)
    self.lbl_opacity_val = QLabel(f"{trans_pct}%", self)
    self.lbl_opacity_val.setFixedWidth(48)
    self.lbl_opacity_val.setAlignment(
        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
    )
    self.slider_opacity.valueChanged.connect(self._on_opacity_changed)
    row_op.addWidget(lbl_op_name)
    row_op.addWidget(self.slider_opacity, 1)
    row_op.addWidget(self.lbl_opacity_val)
    sliders_vbox.addLayout(row_op)

    # 3. Width slider (寬度: 235 ~ 340 px)
    row_w = QHBoxLayout()
    row_w.setSpacing(8)
    lbl_w_name = QLabel("寬度", self)
    lbl_w_name.setFixedWidth(56)
    self.slider_width = SmoothSlider(self)
    self.slider_width.setRange(235, 340)
    self.slider_width.setValue(max(235, min(340, int(base_width))))
    self.lbl_width_val = QLabel(f"{self.slider_width.value()} px", self)
    self.lbl_width_val.setFixedWidth(48)
    self.lbl_width_val.setAlignment(
        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
    )
    self.slider_width.valueChanged.connect(self._on_width_changed)
    row_w.addWidget(lbl_w_name)
    row_w.addWidget(self.slider_width, 1)
    row_w.addWidget(self.lbl_width_val)
    sliders_vbox.addLayout(row_w)

    # 4. Row spacing slider (行距: 0 ~ 6 px)
    row_sp = QHBoxLayout()
    row_sp.setSpacing(8)
    lbl_sp_name = QLabel("行距", self)
    lbl_sp_name.setFixedWidth(56)
    self.slider_spacing = SmoothSlider(self)
    self.slider_spacing.setRange(0, 6)
    self.slider_spacing.setValue(max(0, min(6, int(row_spacing))))
    self.lbl_spacing_val = QLabel(f"{self.slider_spacing.value()} px", self)
    self.lbl_spacing_val.setFixedWidth(48)
    self.lbl_spacing_val.setAlignment(
        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
    )
    self.slider_spacing.valueChanged.connect(self._on_spacing_changed)
    row_sp.addWidget(lbl_sp_name)
    row_sp.addWidget(self.slider_spacing, 1)
    row_sp.addWidget(self.lbl_spacing_val)
    sliders_vbox.addLayout(row_sp)

    # 5. Font weight slider (字體粗細: 400 ~ 700, step 100)
    row_fw = QHBoxLayout()
    row_fw.setSpacing(8)
    lbl_fw_name = QLabel("字體粗細", self)
    lbl_fw_name.setFixedWidth(56)
    self.slider_weight = SmoothSlider(self)
    self.slider_weight.setRange(400, 700)
    self.slider_weight.setSingleStep(100)
    self.slider_weight.setPageStep(100)
    snapped_fw = int(round(max(400, min(700, int(font_weight))) / 100.0) * 100)
    self.slider_weight.setValue(snapped_fw)
    self.lbl_weight_val = QLabel(f"{snapped_fw}", self)
    self.lbl_weight_val.setFixedWidth(48)
    self.lbl_weight_val.setAlignment(
        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
    )
    self.slider_weight.valueChanged.connect(self._on_weight_changed)
    row_fw.addWidget(lbl_fw_name)
    row_fw.addWidget(self.slider_weight, 1)
    row_fw.addWidget(self.lbl_weight_val)
    sliders_vbox.addLayout(row_fw)

    layout.addLayout(sliders_vbox)

    # Auto-Pause configuration section
    sep = QWidget(self)
    sep.setFixedHeight(1)
    sep.setStyleSheet("background-color: rgba(255, 255, 255, 0.10);")
    layout.addWidget(sep)

    lbl_ap_title = QLabel("自動暫停設定", self)
    lbl_ap_title.setFont(_make_smooth_font(13, QFont.Weight.Bold))
    lbl_ap_title.setStyleSheet("color: #f1f5f9; background-color: #181d28;")
    layout.addWidget(lbl_ap_title)

    ap_row = QHBoxLayout()
    ap_row.setSpacing(6)

    self.chk_auto_pause = SmoothCheckBox("閒置時自動暫停", self)
    self.chk_auto_pause.setChecked(bool(auto_pause_enabled))
    self.chk_auto_pause.setMinimumWidth(120)

    lbl_ap_sec = QLabel("閒置秒數：", self)
    lbl_ap_sec.setFont(_make_smooth_font(12, QFont.Weight.Normal))
    self.spin_auto_pause_sec = SmoothSpinBox(self)
    self.spin_auto_pause_sec.setRange(1, 300)
    self.spin_auto_pause_sec.setButtonSymbols(
        QAbstractSpinBox.ButtonSymbols.NoButtons
    )
    self.spin_auto_pause_sec.setAlignment(Qt.AlignmentFlag.AlignCenter)
    self.spin_auto_pause_sec.setFixedSize(54, 28)
    self.spin_auto_pause_sec.setValue(max(1, min(300, int(auto_pause_seconds))))
    self.spin_auto_pause_sec.setEnabled(bool(auto_pause_enabled))
    self.chk_auto_pause.toggled.connect(self.spin_auto_pause_sec.setEnabled)

    ap_row.addWidget(self.chk_auto_pause, 1)
    ap_row.addWidget(lbl_ap_sec)
    ap_row.addWidget(self.spin_auto_pause_sec)
    layout.addLayout(ap_row)

    btn_bar = QHBoxLayout()
    btn_bar.setSpacing(8)

    btn_reset = SmoothDialogButton("恢復預設", self)
    btn_reset.clicked.connect(self._reset_defaults)

    btn_cancel = SmoothDialogButton("取消", self)
    btn_cancel.clicked.connect(self.reject)

    btn_save = SmoothDialogButton("確認套用", self)
    btn_save.set_color_scheme(
        bg=QColor("#10b981"),
        hover_bg=QColor("#059669"),
        border=QColor("#059669"),
        text_color=QColor("#ffffff"),
        bold=True,
    )
    btn_save.clicked.connect(self.accept)

    btn_bar.addWidget(btn_reset)
    btn_bar.addStretch()
    btn_bar.addWidget(btn_cancel)
    btn_bar.addWidget(btn_save)
    layout.addLayout(btn_bar)

    _apply_smooth_font_recursively(self)

  def _on_scale_changed(self, val: int) -> None:
    self.lbl_scale_val.setText(f"{val}%")
    if self._overlay_parent and hasattr(self._overlay_parent, "set_ui_scale"):
      self._overlay_parent.set_ui_scale(val / 100.0)

  def _on_opacity_changed(self, val: int) -> None:
    self.lbl_opacity_val.setText(f"{val}%")
    if self._overlay_parent and hasattr(self._overlay_parent, "set_ui_opacity"):
      self._overlay_parent.set_ui_opacity((100 - val) / 100.0)

  def _on_width_changed(self, val: int) -> None:
    self.lbl_width_val.setText(f"{val} px")
    if self._overlay_parent and hasattr(self._overlay_parent, "set_base_width"):
      self._overlay_parent.set_base_width(val)

  def _on_spacing_changed(self, val: int) -> None:
    self.lbl_spacing_val.setText(f"{val} px")
    if self._overlay_parent and hasattr(self._overlay_parent, "set_row_spacing"):
      self._overlay_parent.set_row_spacing(val)

  def _on_weight_changed(self, val: int) -> None:
    snapped = int(round(max(400, min(700, val)) / 100.0) * 100)
    if snapped != val:
      self.slider_weight.blockSignals(True)
      self.slider_weight.setValue(snapped)
      self.slider_weight.blockSignals(False)
    self.lbl_weight_val.setText(f"{snapped}")
    if self._overlay_parent and hasattr(self._overlay_parent, "set_font_weight"):
      self._overlay_parent.set_font_weight(snapped)

  def reject(self) -> None:
    if self._overlay_parent:
      if hasattr(self._overlay_parent, "set_ui_scale"):
        self._overlay_parent.set_ui_scale(self._orig_scale)
      if hasattr(self._overlay_parent, "set_ui_opacity"):
        self._overlay_parent.set_ui_opacity(self._orig_opacity)
      if hasattr(self._overlay_parent, "set_base_width"):
        self._overlay_parent.set_base_width(self._orig_width)
      if hasattr(self._overlay_parent, "set_row_spacing"):
        self._overlay_parent.set_row_spacing(self._orig_spacing)
      if hasattr(self._overlay_parent, "set_font_weight"):
        self._overlay_parent.set_font_weight(self._orig_weight)
    super().reject()

  def _move_item(self, direction: int) -> None:
    r = self.list_widget.currentRow()
    if r < 0:
      return
    nr = r + direction
    if 0 <= nr < self.list_widget.count():
      item = self.list_widget.takeItem(r)
      self.list_widget.insertItem(nr, item)
      self.list_widget.setCurrentRow(nr)

  def _reset_defaults(self) -> None:
    self.list_widget.clear()
    for name in config.ALL_METRIC_KEYS:
      it = QListWidgetItem(name, self.list_widget)
      it.setFlags(
          Qt.ItemFlag.ItemIsEnabled
          | Qt.ItemFlag.ItemIsSelectable
          | Qt.ItemFlag.ItemIsUserCheckable
          | Qt.ItemFlag.ItemIsDragEnabled
      )
      it.setCheckState(
          Qt.CheckState.Checked
          if name in config.DEFAULT_GAME_MODE_KEYS
          else Qt.CheckState.Unchecked
      )
    self.chk_auto_pause.setChecked(config.DEFAULT_AUTO_PAUSE_ENABLED)
    self.spin_auto_pause_sec.setValue(config.DEFAULT_AUTO_PAUSE_SECONDS)
    self.slider_scale.setValue(100)
    self.slider_opacity.setValue(5)
    self.slider_width.setValue(config.DEFAULT_BASE_WIDTH)
    self.slider_spacing.setValue(config.DEFAULT_ROW_SPACING)
    self.slider_weight.setValue(config.DEFAULT_FONT_WEIGHT)

  def get_ordered_items(self) -> List[str]:
    selected = [
        self.list_widget.item(i).text()
        for i in range(self.list_widget.count())
        if self.list_widget.item(i).checkState() == Qt.CheckState.Checked
    ]
    return selected if selected else list(config.DEFAULT_GAME_MODE_KEYS)

  def get_full_order(self) -> List[str]:
    return [
        self.list_widget.item(i).text()
        for i in range(self.list_widget.count())
    ]

  def get_auto_pause_enabled(self) -> bool:
    return self.chk_auto_pause.isChecked()

  def get_auto_pause_seconds(self) -> int:
    return int(self.spin_auto_pause_sec.value())

  def get_ui_scale(self) -> float:
    return round(self.slider_scale.value() / 100.0, 2)

  def get_opacity_val(self) -> float:
    return round((100 - self.slider_opacity.value()) / 100.0, 2)

  def get_base_width(self) -> int:
    return int(self.slider_width.value())

  def get_row_spacing(self) -> int:
    return int(self.slider_spacing.value())

  def get_font_weight(self) -> int:
    return int(round(self.slider_weight.value() / 100.0) * 100)


class UpdateCheckWorker(QThread):
  """Background thread to query GitHub Releases API without blocking the UI."""

  result_ready = pyqtSignal(bool, object, str)  # (has_update, update_info, status_msg)

  def run(self):
    has_update, info, msg = check_for_update(
        repo=config.APP_GITHUB_REPO,
        current_version=config.APP_VERSION,
    )
    self.result_ready.emit(has_update, info, msg)


class UpdateDownloadWorker(QThread):
  """Background thread to download update asset with progress reporting."""

  progress = pyqtSignal(int, int)  # (downloaded, total)
  finished = pyqtSignal(bool, str)  # (success, path_or_error)

  def __init__(self, download_url: str, dest_path: str, parent=None):
    super().__init__(parent)
    self.download_url = download_url
    self.dest_path = dest_path

  def run(self):
    try:
      success = download_file(
          self.download_url,
          self.dest_path,
          progress_callback=lambda d, t: self.progress.emit(d, t),
      )
      if not success:
        self.finished.emit(False, "下載失敗，請檢查網路連線")
        return

      if self.dest_path.endswith(".zip"):
        import zipfile
        if not zipfile.is_zipfile(self.dest_path):
          try:
            os.remove(self.dest_path)
          except OSError:
            pass
          self.finished.emit(False, "下載的更新檔案損毀或不是有效的壓縮檔 (ZIP corrupt)")
          return

      self.finished.emit(True, self.dest_path)
    except Exception as e:
      logger.error("Download worker exception: %s", e)
      self.finished.emit(False, f"下載發生錯誤: {e}")


class AboutDialog(QDialog):
  """Dialog displaying application information, author, version, contact, and copyright."""

  def __init__(self, parent=None):
    super().__init__(parent)
    _ensure_dialog_fonts()
    self.setWindowTitle("關於 (About)")
    self.setModal(True)
    self.setFixedWidth(500)
    self.setStyleSheet("""
        QDialog {
            background-color: #181d28;
            color: #e2e8f0;
        }
        QLabel {
            color: #94a3b8;
            background-color: #181d28;
        }
    """)

    layout = QVBoxLayout(self)
    layout.setContentsMargins(20, 20, 20, 20)
    layout.setSpacing(14)

    # Header title
    lbl_app_title = QLabel(config.APP_NAME, self)
    lbl_app_title.setFont(_make_smooth_font(16, QFont.Weight.Bold, latin_first=True))
    lbl_app_title.setStyleSheet("color: #f1f5f9; background-color: #181d28;")
    layout.addWidget(lbl_app_title)

    # Info Card with smooth anti-aliased rounded border
    info_card = SmoothCardFrame(
        bg_color=QColor("#111827"),
        border_color=QColor(255, 255, 255, 32),
        radius=8.0,
        parent=self,
    )
    card_layout = QVBoxLayout(info_card)
    card_layout.setContentsMargins(14, 12, 14, 12)
    card_layout.setSpacing(10)

    def _make_row(label: str, value: str, is_rich: bool = False) -> QHBoxLayout:
      row = QHBoxLayout()
      row.setSpacing(12)
      lbl_k = QLabel(label, info_card)
      lbl_k.setFont(_make_smooth_font(12, QFont.Weight.Normal))
      lbl_k.setStyleSheet("color: #94a3b8; background-color: #111827;")
      lbl_v = QLabel(info_card)
      lbl_v.setText(value)
      lbl_v.setFont(_make_smooth_font(12, QFont.Weight.Medium, latin_first=True))
      lbl_v.setStyleSheet("color: #f1f5f9; background-color: #111827;")
      lbl_v.setTextInteractionFlags(
          Qt.TextInteractionFlag.TextSelectableByMouse
      )
      row.addWidget(lbl_k)
      row.addStretch()
      row.addWidget(lbl_v)
      return row

    card_layout.addLayout(_make_row("作者 (Author)", config.APP_AUTHOR))
    card_layout.addLayout(
        _make_row("版本 (Version)", config.get_full_version_string())
    )
    card_layout.addLayout(_make_row("Discord ID", config.APP_DISCORD_ID))
    card_layout.addLayout(
        _make_row(
            "版權 (Copyright)",
            '<span style="color: #94a3b8;">© 2026 By </span><b style="color:'
            ' #f1f5f9; font-weight: 700;">G8G</b>',
            is_rich=True,
        )
    )
    layout.addWidget(info_card)

    # Action / Button row: [檢查更新] [查看日誌] [狀態] ... [確定]
    btn_box = QHBoxLayout()
    btn_box.setSpacing(10)

    self.btn_check_update = SmoothDialogButton("檢查更新", self)
    self.btn_check_update.clicked.connect(self._on_action_clicked)
    btn_box.addWidget(self.btn_check_update)

    self.btn_view_logs = SmoothDialogButton("查看日誌", self)
    self.btn_view_logs.clicked.connect(self._open_logs)
    btn_box.addWidget(self.btn_view_logs)

    self.lbl_update_status = QLabel("", self)
    self.lbl_update_status.setFont(_make_smooth_font(11, QFont.Weight.Normal))
    self.lbl_update_status.setStyleSheet("color: #94a3b8; background-color: #181d28;")
    self.lbl_update_status.setWordWrap(True)
    self.lbl_update_status.setOpenExternalLinks(True)
    btn_box.addWidget(self.lbl_update_status, 1)

    btn_box.addStretch()

    btn_ok = SmoothDialogButton("確定", self)
    btn_ok.setFixedWidth(70)
    btn_ok.clicked.connect(self.accept)
    btn_box.addWidget(btn_ok)

    layout.addLayout(btn_box)

    self.available_update: Optional[UpdateInfo] = None
    self.downloaded_archive_path: Optional[str] = None
    self._check_worker: Optional[UpdateCheckWorker] = None
    self._download_worker: Optional[UpdateDownloadWorker] = None

    _apply_smooth_font_recursively(self)

  def _on_action_clicked(self):
    """Handles action button click depending on updater state."""
    if self.downloaded_archive_path:
      # Apply and restart
      success, msg = apply_update_and_restart(self.downloaded_archive_path)
      if success:
        self.lbl_update_status.setText(msg)
        self.btn_check_update.setEnabled(False)
        # Close dialog and app to let restart script take over
        QDialog.accept(self)
        qapp = QApplication.instance()
        if qapp:
          qapp.closeAllWindows()
          qapp.quit()
        else:
          sys.exit(0)
      else:
        self.lbl_update_status.setText(msg)
        self.lbl_update_status.setStyleSheet("color: #f87171; background-color: #181d28;")
      return

    if self.available_update:
      # Start download
      self._start_download(self.available_update)
      return

    # Check for updates
    self._check_for_updates()

  def _open_logs(self):
    """Opens the local log file in the system default text viewer."""
    log_file = os.path.join(config.USER_CONFIG_DIR, "artale_app.log")
    try:
      if not os.path.exists(log_file):
        os.makedirs(config.USER_CONFIG_DIR, exist_ok=True)
        with open(log_file, "w", encoding="utf-8") as f:
          f.write(f"--- Artale EXP Calculator Log ---\nVersion: {config.get_full_version_string()}\n")
      if not QDesktopServices.openUrl(QUrl.fromLocalFile(log_file)):
        if sys.platform == "darwin":
          subprocess.Popen(["open", log_file])
        elif sys.platform == "win32":
          os.startfile(log_file)
        else:
          subprocess.Popen(["xdg-open", log_file])
    except Exception as e:
      logger.error("Failed to open log file %s: %s", log_file, e)
      self.lbl_update_status.setText(f"無法開啟日誌: {e}")

  def _check_for_updates(self):
    """Initiates an asynchronous check for updates against GitHub Releases."""
    self.btn_check_update.setEnabled(False)
    self.lbl_update_status.setText("檢查中...")
    self.lbl_update_status.setStyleSheet("color: #94a3b8; background-color: #181d28;")

    self._check_worker = UpdateCheckWorker(self)
    self._check_worker.result_ready.connect(self._on_check_result)
    self._check_worker.start()

  def _on_check_result(
      self, has_update: bool, info: Optional[UpdateInfo], status_msg: str
  ):
    self.btn_check_update.setEnabled(True)
    if has_update and info:
      self.available_update = info
      if getattr(info, "is_same_version", False):
        self.btn_check_update.setText("重新下載安裝")
        self.btn_check_update.set_color_scheme(
            bg=QColor("#0284c7"),
            hover_bg=QColor("#0369a1"),
            border=QColor("#0369a1"),
            text_color=QColor("#ffffff"),
            bold=True,
        )
        self.lbl_update_status.setText(
            f'<a href="{info.download_url}" style="color: #34d399; text-decoration:'
            f' underline;">目前已是最新版本 v{info.version}</a>'
        )
      else:
        self.btn_check_update.setText("立即下載更新")
        self.btn_check_update.set_color_scheme(
            bg=QColor("#0284c7"),
            hover_bg=QColor("#0369a1"),
            border=QColor("#0369a1"),
            text_color=QColor("#ffffff"),
            bold=True,
        )
        self.lbl_update_status.setText(
            f'<a href="{info.download_url}" style="color: #38bdf8; text-decoration:'
            f' underline;">發現新版本 v{info.version}</a>'
        )
    else:
      self.available_update = None
      if "最新版本" in status_msg:
        self.lbl_update_status.setText(status_msg)
        self.lbl_update_status.setStyleSheet("color: #34d399; background-color: #181d28;")
      else:
        self.lbl_update_status.setText(status_msg)
        self.lbl_update_status.setStyleSheet("color: #f87171; background-color: #181d28;")

  def _start_download(self, info: UpdateInfo):
    """Starts background downloading of the release asset."""
    try:
      self.btn_check_update.setEnabled(False)
      self.btn_check_update.setText("下載中...")
      self.btn_check_update.set_color_scheme(
          bg=QColor(255, 255, 255, 25),
          hover_bg=QColor(255, 255, 255, 45),
          border=QColor(255, 255, 255, 38),
          text_color=QColor("#94a3b8"),
          bold=True,
      )
      self.lbl_update_status.setText("準備下載中...")
      self.lbl_update_status.setStyleSheet("color: #94a3b8; background-color: #181d28;")

      dest_filename = info.asset_name if info.asset_name else "update.zip"
      dest_path = os.path.join(tempfile.gettempdir(), dest_filename)

      self._download_worker = UpdateDownloadWorker(info.download_url, dest_path, self)
      self._download_worker.progress.connect(self._on_download_progress)
      self._download_worker.finished.connect(self._on_download_finished)
      self._download_worker.start()
    except Exception as e:
      logger.error("Failed to start download: %s", e)
      self.btn_check_update.setEnabled(True)
      self.btn_check_update.setText("重新下載")
      self.btn_check_update.set_color_scheme(
          bg=QColor("#0284c7"),
          hover_bg=QColor("#0369a1"),
          border=QColor("#0369a1"),
          text_color=QColor("#ffffff"),
          bold=True,
      )
      self.lbl_update_status.setText(f"下載初始化失敗: {e}")
      self.lbl_update_status.setStyleSheet("color: #f87171; background-color: #181d28;")

  def _on_download_progress(self, downloaded: int, total: int):
    if total > 0:
      pct = int(downloaded * 100 / total)
      mb_down = downloaded / (1024 * 1024)
      mb_total = total / (1024 * 1024)
      self.lbl_update_status.setText(
          f"下載中: {pct}% ({mb_down:.1f}/{mb_total:.1f} MB)"
      )
    else:
      mb_down = downloaded / (1024 * 1024)
      self.lbl_update_status.setText(f"已下載: {mb_down:.1f} MB")

  def _on_download_finished(self, success: bool, path_or_err: str):
    self.btn_check_update.setEnabled(True)
    if success:
      self.downloaded_archive_path = path_or_err
      self.btn_check_update.setText("套用並重啟")
      self.btn_check_update.set_color_scheme(
          bg=QColor("#10b981"),
          hover_bg=QColor("#059669"),
          border=QColor("#059669"),
          text_color=QColor("#ffffff"),
          bold=True,
      )
      self.lbl_update_status.setText("下載完成！點擊按鈕重啟套用")
      self.lbl_update_status.setStyleSheet("color: #34d399; background-color: #181d28;")
    else:
      self.lbl_update_status.setText(path_or_err)
      self.lbl_update_status.setStyleSheet("color: #f87171; background-color: #181d28;")
      self.btn_check_update.setText("重新下載")
      self.btn_check_update.set_color_scheme(
          bg=QColor("#0284c7"),
          hover_bg=QColor("#0369a1"),
          border=QColor("#0369a1"),
          text_color=QColor("#ffffff"),
          bold=True,
      )
