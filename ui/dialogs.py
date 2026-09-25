"""Settings dialogs for configuring metrics, ordering, and appearance.

Complies with the Google Python Style Guide.
"""

import json
from typing import List
import urllib.request
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

import config


class GameModeSettingsDialog(QDialog):
  """Dialog allowing the user to select and reorder metrics for Game and Full Mode."""

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
            font-family: {config.FONT_FAMILY};
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
            font-family: {config.FONT_FAMILY};
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

    body_layout.addWidget(self.list_widget)

    btn_vbox = QVBoxLayout()
    btn_vbox.setSpacing(6)
    btn_up = QPushButton("▲ 上移", self)
    btn_up.clicked.connect(lambda: self._move_item(-1))

    btn_down = QPushButton("▼ 下移", self)
    btn_down.clicked.connect(lambda: self._move_item(1))

    btn_vbox.addWidget(btn_up)
    btn_vbox.addWidget(btn_down)
    btn_vbox.addStretch()
    body_layout.addLayout(btn_vbox)

    layout.addLayout(body_layout)

    btn_bar = QHBoxLayout()
    btn_bar.setSpacing(8)

    btn_reset = QPushButton("恢復預設", self)
    btn_reset.clicked.connect(self._reset_defaults)

    btn_cancel = QPushButton("取消", self)
    btn_cancel.clicked.connect(self.reject)

    btn_save = QPushButton("確認套用", self)
    btn_save.setStyleSheet(
        "background-color: #10b981; color: #ffffff; font-weight: bold; border:"
        " 1px solid #059669;"
    )
    btn_save.clicked.connect(self.accept)

    btn_bar.addWidget(btn_reset)
    btn_bar.addStretch()
    btn_bar.addWidget(btn_cancel)
    btn_bar.addWidget(btn_save)
    layout.addLayout(btn_bar)

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


class UpdateCheckWorker(QThread):
  """Background thread to query GitHub Releases API without blocking the UI."""

  result_ready = pyqtSignal(bool, str, str)  # (success, tag_or_error, release_url)

  def run(self):
    url = (
        f"https://api.github.com/repos/{config.APP_GITHUB_REPO}/releases/latest"
    )
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "ArtaleExpCalculator-Client"},
    )
    try:
      with urllib.request.urlopen(req, timeout=5) as resp:
        if resp.status == 200:
          data = json.loads(resp.read().decode("utf-8"))
          tag = data.get("tag_name", "").lstrip("v")
          html_url = data.get(
              "html_url",
              f"https://github.com/{config.APP_GITHUB_REPO}/releases",
          )
          self.result_ready.emit(True, tag, html_url)
          return
      self.result_ready.emit(False, "伺服器無回應", "")
    except Exception as e:
      self.result_ready.emit(False, str(e), "")


class AboutDialog(QDialog):
  """Dialog displaying application information, author, version, contact, and copyright."""

  def __init__(self, parent=None):
    super().__init__(parent)
    self.setWindowTitle("關於 (About)")
    self.setModal(True)
    self.setFixedWidth(380)
    self.setStyleSheet(f"""
        QDialog {{
            background-color: #181d28;
            color: #e2e8f0;
            font-family: {config.FONT_FAMILY};
            font-size: 13px;
        }}
        QLabel {{
            color: #94a3b8;
            font-size: 12px;
        }}
        QPushButton {{
            background-color: rgba(255, 255, 255, 0.1);
            color: #e2e8f0;
            border: 1px solid rgba(255, 255, 255, 0.15);
            border-radius: 6px;
            padding: 6px 14px;
            font-size: 12px;
            font-family: {config.FONT_FAMILY};
        }}
        QPushButton:hover {{
            background-color: rgba(255, 255, 255, 0.18);
        }}
        QPushButton:disabled {{
            color: #64748b;
            background-color: rgba(255, 255, 255, 0.04);
            border-color: rgba(255, 255, 255, 0.08);
        }}
    """)

    layout = QVBoxLayout(self)
    layout.setContentsMargins(20, 20, 20, 20)
    layout.setSpacing(14)

    # Header title
    lbl_app_title = QLabel(config.APP_NAME)
    lbl_app_title.setStyleSheet(
        "color: #f1f5f9; font-weight: 700; font-size: 16px; letter-spacing:"
        " 0.5px;"
    )
    layout.addWidget(lbl_app_title)

    # Info Card
    info_card = QFrame(self)
    info_card.setObjectName("infoCard")
    info_card.setStyleSheet("""
        QFrame#infoCard {
            background-color: #111827;
            border: 1px solid rgba(255, 255, 255, 0.12);
            border-radius: 8px;
        }
        QLabel {
            border: none;
            background: transparent;
        }
    """)
    card_layout = QVBoxLayout(info_card)
    card_layout.setContentsMargins(14, 12, 14, 12)
    card_layout.setSpacing(10)

    def _make_row(label: str, value: str, is_rich: bool = False) -> QHBoxLayout:
      row = QHBoxLayout()
      row.setSpacing(12)
      lbl_k = QLabel(label)
      lbl_k.setStyleSheet("color: #94a3b8; font-size: 12px;")
      lbl_v = QLabel()
      if is_rich:
        lbl_v.setText(value)
      else:
        lbl_v.setText(value)
      lbl_v.setStyleSheet("color: #f1f5f9; font-size: 12px; font-weight: 500;")
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

    # Action / Button row: [檢查更新] [狀態] ... [確定]
    btn_box = QHBoxLayout()
    btn_box.setSpacing(10)

    self.btn_check_update = QPushButton("檢查更新")
    self.btn_check_update.clicked.connect(self._check_for_updates)
    btn_box.addWidget(self.btn_check_update)

    self.lbl_update_status = QLabel("")
    self.lbl_update_status.setStyleSheet("font-size: 11px;")
    self.lbl_update_status.setOpenExternalLinks(True)
    btn_box.addWidget(self.lbl_update_status)

    btn_box.addStretch()

    btn_ok = QPushButton("確定")
    btn_ok.setFixedWidth(70)
    btn_ok.clicked.connect(self.accept)
    btn_box.addWidget(btn_ok)

    layout.addLayout(btn_box)

    self._worker = None

  def _check_for_updates(self):
    """Initiates an asynchronous check for updates against GitHub Releases."""
    self.btn_check_update.setEnabled(False)
    self.lbl_update_status.setText("檢查中...")
    self.lbl_update_status.setStyleSheet("color: #94a3b8; font-size: 11px;")

    self._worker = UpdateCheckWorker(self)
    self._worker.result_ready.connect(self._on_update_result)
    self._worker.start()

  def _on_update_result(self, success: bool, tag_or_err: str, release_url: str):
    self.btn_check_update.setEnabled(True)
    if not success:
      self.lbl_update_status.setText("無法連線至更新伺服器")
      self.lbl_update_status.setStyleSheet("color: #f87171; font-size: 11px;")
      return

    def _parse_ver(v_str: str) -> tuple:
      parts = []
      for p in v_str.split("."):
        digits = "".join(filter(str.isdigit, p))
        parts.append(int(digits) if digits else 0)
      return tuple(parts)

    try:
      latest_v = _parse_ver(tag_or_err)
      current_v = _parse_ver(config.APP_VERSION)
      if latest_v > current_v:
        self.lbl_update_status.setText(
            f'<a href="{release_url}" style="color: #38bdf8; text-decoration:'
            f' underline;">發現新版本 v{tag_or_err}</a>'
        )
      else:
        self.lbl_update_status.setText("已是最新版本 ✓")
        self.lbl_update_status.setStyleSheet("color: #34d399; font-size: 11px;")
    except Exception:
      self.lbl_update_status.setText("版本格式解析失敗")
      self.lbl_update_status.setStyleSheet("color: #f87171; font-size: 11px;")


