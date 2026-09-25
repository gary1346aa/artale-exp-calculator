"""Developer dialog for discovering and selecting open desktop windows.

Complies with the Google Python Style Guide.
Non-blocking window enumeration using Win32 API.
"""

import ctypes
import ctypes.wintypes
import os
import sys
from typing import List, Optional, Tuple

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

import config


def get_visible_windows() -> List[Tuple[int, str]]:
  """Enumerates visible top-level windows safely without IPC deadlocks.

  Returns:
    List of (hwnd, title) tuples for visible windows.
  """
  if sys.platform == "darwin":
    from core.capture_macos import get_macos_visible_windows
    return get_macos_visible_windows()

  if sys.platform != "win32":
    return []

  user32 = ctypes.windll.user32
  results: List[Tuple[int, str]] = []
  curr_pid = os.getpid()

  def enum_cb(hwnd, _):
    if not user32.IsWindowVisible(hwnd):
      return True
    lp_pid = ctypes.wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(lp_pid))
    if lp_pid.value == curr_pid:
      return True

    buf = ctypes.create_unicode_buffer(512)
    n = user32.InternalGetWindowText(hwnd, buf, 512)
    if n <= 0:
      return True
    title = buf.value.strip()
    if not title:
      return True

    is_cloaked = ctypes.c_int(0)
    try:
      ctypes.windll.dwmapi.DwmGetWindowAttribute(
          hwnd, 14, ctypes.byref(is_cloaked), ctypes.sizeof(is_cloaked)
      )
      if is_cloaked.value:
        return True
    except Exception:
      pass

    if title in [
        "Program Manager",
        "NVIDIA GeForce Overlay",
        "Windows Input Experience",
    ]:
      return True

    results.append((hwnd, title))
    return True

  wnd_enum_proc = ctypes.WINFUNCTYPE(
      ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM
  )
  user32.EnumWindows(wnd_enum_proc(enum_cb), 0)
  return results


class SelectWindowDialog(QDialog):
  """Dialog allowing user to choose any open window for live capture."""

  def __init__(
      self,
      current_window: str = config.DEFAULT_TARGET_WINDOW,
      current_hwnd: Optional[int] = None,
      parent=None,
  ):
    super().__init__(parent)
    self.setWindowTitle("選擇擷取視窗")
    self.setModal(True)
    self.setMinimumSize(420, 360)
    self.selected_title: str = current_window
    self.selected_hwnd: Optional[int] = current_hwnd

    self.setStyleSheet(f"""
        QDialog {{
            background-color: #0e121c;
            color: #f1f5f9;
            font-family: {config.FONT_FAMILY};
        }}
        QLabel {{
            color: #94a3b8;
            font-size: 12px;
            font-family: {config.FONT_FAMILY};
        }}
        QLineEdit {{
            background-color: rgba(255, 255, 255, 0.08);
            color: #f1f5f9;
            border: 1px solid rgba(255, 255, 255, 0.18);
            border-radius: 6px;
            padding: 6px 10px;
            font-size: 12px;
            font-family: {config.FONT_FAMILY};
        }}
        QLineEdit:focus {{
            border-color: #38bdf8;
        }}
        QListWidget {{
            background-color: rgba(255, 255, 255, 0.04);
            border: 1px solid rgba(255, 255, 255, 0.12);
            border-radius: 8px;
            color: #e2e8f0;
            padding: 4px;
            font-size: 12px;
            font-family: {config.FONT_FAMILY};
        }}
        QListWidget::item {{
            padding: 6px 10px;
            border-radius: 4px;
            margin: 1px 0px;
        }}
        QListWidget::item:selected {{
            background-color: rgba(56, 189, 248, 0.25);
            color: #ffffff;
            font-weight: 600;
        }}
        QPushButton {{
            background-color: rgba(255, 255, 255, 0.1);
            color: #e2e8f0;
            border: 1px solid rgba(255, 255, 255, 0.15);
            border-radius: 6px;
            padding: 6px 12px;
            font-size: 12px;
            font-family: {config.FONT_FAMILY};
        }}
        QPushButton:hover {{
            background-color: rgba(255, 255, 255, 0.18);
        }}
    """)

    layout = QVBoxLayout(self)
    layout.setContentsMargins(18, 16, 18, 16)
    layout.setSpacing(10)

    lbl_title = QLabel("選擇擷取視窗 (Select Window)")
    lbl_title.setStyleSheet("color: #f1f5f9; font-weight: 700; font-size: 14px;")
    layout.addWidget(lbl_title)

    lbl_hint = QLabel(
        "請選擇欲即時追蹤經驗值的視窗（支援 Artale 遊戲、影片播放器等）："
    )
    lbl_hint.setWordWrap(True)
    layout.addWidget(lbl_hint)

    self.txt_filter = QLineEdit(self)
    self.txt_filter.setPlaceholderText("🔍 搜尋視窗名稱...")
    self.txt_filter.textChanged.connect(self._filter_list)
    layout.addWidget(self.txt_filter)

    self.list_widget = QListWidget(self)
    self.list_widget.setSelectionMode(
        QAbstractItemView.SelectionMode.SingleSelection
    )
    self.list_widget.itemDoubleClicked.connect(self._on_confirm)
    layout.addWidget(self.list_widget)

    self._populate_windows()

    btn_bar = QHBoxLayout()
    btn_bar.setSpacing(8)

    btn_refresh = QPushButton("↺ 重新整理", self)
    btn_refresh.clicked.connect(self._populate_windows)

    btn_default = QPushButton("預設遊戲視窗", self)
    btn_default.clicked.connect(self._select_default)

    btn_cancel = QPushButton("取消", self)
    btn_cancel.clicked.connect(self.reject)

    btn_save = QPushButton("確認選取", self)
    btn_save.setStyleSheet(
        "background-color: #10b981; color: #ffffff; font-weight: bold; border:"
        " 1px solid #059669;"
    )
    btn_save.clicked.connect(self._on_confirm)

    btn_bar.addWidget(btn_refresh)
    btn_bar.addWidget(btn_default)
    btn_bar.addStretch()
    btn_bar.addWidget(btn_cancel)
    btn_bar.addWidget(btn_save)
    layout.addLayout(btn_bar)

  def _populate_windows(self) -> None:
    self.list_widget.clear()

    # Default Artale item
    def_item = QListWidgetItem(
        f"{config.DEFAULT_TARGET_WINDOW} (預設遊戲視窗)", self.list_widget
    )
    def_item.setData(
        Qt.ItemDataRole.UserRole, (config.DEFAULT_TARGET_WINDOW, None)
    )

    open_wins = get_visible_windows()
    for hwnd, title in open_wins:
      if "ARTALE EXP" in title or "Artale EXP Calculator" in title:
        continue
      if title == config.DEFAULT_TARGET_WINDOW:
        continue
      it = QListWidgetItem(f"{title} (HWND: {hwnd})", self.list_widget)
      it.setData(Qt.ItemDataRole.UserRole, (title, hwnd))

    found = False
    for i in range(self.list_widget.count()):
      it = self.list_widget.item(i)
      t, h = it.data(Qt.ItemDataRole.UserRole)
      if (self.selected_hwnd and h == self.selected_hwnd) or (
          t == self.selected_title
      ):
        self.list_widget.setCurrentItem(it)
        found = True
        break
    if not found and self.list_widget.count() > 0:
      self.list_widget.setCurrentRow(0)

  def _filter_list(self, query: str) -> None:
    query = query.strip().lower()
    for i in range(self.list_widget.count()):
      it = self.list_widget.item(i)
      it.setHidden(query not in it.text().lower())

  def _select_default(self) -> None:
    self.selected_title = config.DEFAULT_TARGET_WINDOW
    self.selected_hwnd = None
    self.accept()

  def _on_confirm(self) -> None:
    it = self.list_widget.currentItem()
    if it:
      self.selected_title, self.selected_hwnd = it.data(
          Qt.ItemDataRole.UserRole
      )
    self.accept()

  def get_selected(self) -> Tuple[str, Optional[int]]:
    """Returns the selected (title, hwnd)."""
    return self.selected_title, self.selected_hwnd
