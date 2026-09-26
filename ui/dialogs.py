"""Settings dialogs for configuring metrics, ordering, and appearance.

Complies with the Google Python Style Guide.
"""

import logging
import os
import subprocess
import sys
import tempfile
from typing import Dict, List, Optional
from PyQt6.QtCore import Qt, QThread, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QKeySequence
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

import config

logger = logging.getLogger(__name__)


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


from core.updater import (
    UpdateInfo,
    apply_update_and_restart,
    check_for_update,
    download_file,
)


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
    self.setWindowTitle("關於 (About)")
    self.setModal(True)
    self.setFixedWidth(400)
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
    self.btn_check_update.clicked.connect(self._on_action_clicked)
    btn_box.addWidget(self.btn_check_update)

    self.btn_view_logs = QPushButton("查看日誌")
    self.btn_view_logs.clicked.connect(self._open_logs)
    btn_box.addWidget(self.btn_view_logs)

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

    self.available_update: Optional[UpdateInfo] = None
    self.downloaded_archive_path: Optional[str] = None
    self._check_worker: Optional[UpdateCheckWorker] = None
    self._download_worker: Optional[UpdateDownloadWorker] = None

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
        self.lbl_update_status.setStyleSheet("color: #f87171; font-size: 11px;")
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
    self.lbl_update_status.setStyleSheet("color: #94a3b8; font-size: 11px;")

    self._check_worker = UpdateCheckWorker(self)
    self._check_worker.result_ready.connect(self._on_check_result)
    self._check_worker.start()

  def _on_check_result(
      self, has_update: bool, info: Optional[UpdateInfo], status_msg: str
  ):
    self.btn_check_update.setEnabled(True)
    if has_update and info:
      self.available_update = info
      self.btn_check_update.setText("立即下載更新")
      self.btn_check_update.setStyleSheet(
          "background-color: #0284c7; color: white; border: none; font-weight:"
          " 600;"
      )
      self.lbl_update_status.setText(
          f'<a href="{info.download_url}" style="color: #38bdf8; text-decoration:'
          f' underline;">發現新版本 v{info.version}</a>'
      )
    else:
      self.available_update = None
      if "最新版本" in status_msg:
        self.lbl_update_status.setText(status_msg)
        self.lbl_update_status.setStyleSheet("color: #34d399; font-size: 11px;")
      else:
        self.lbl_update_status.setText(status_msg)
        self.lbl_update_status.setStyleSheet("color: #f87171; font-size: 11px;")

  def _start_download(self, info: UpdateInfo):
    """Starts background downloading of the release asset."""
    try:
      self.btn_check_update.setEnabled(False)
      self.btn_check_update.setText("下載中...")
      self.lbl_update_status.setText("準備下載中...")
      self.lbl_update_status.setStyleSheet("color: #94a3b8; font-size: 11px;")

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
      self.lbl_update_status.setText(f"下載初始化失敗: {e}")
      self.lbl_update_status.setStyleSheet("color: #f87171; font-size: 11px;")

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
      self.btn_check_update.setStyleSheet(
          "background-color: #10b981; color: white; border: none; font-weight:"
          " 600;"
      )
      self.lbl_update_status.setText("下載完成！點擊按鈕重啟套用")
      self.lbl_update_status.setStyleSheet("color: #34d399; font-size: 11px;")
    else:
      self.lbl_update_status.setText(path_or_err)
      self.lbl_update_status.setStyleSheet("color: #f87171; font-size: 11px;")
      self.btn_check_update.setText("重新下載")


class HotkeySettingsDialog(QDialog):
  """OBS-style hotkey configuration dialog allowing users to capture custom shortcuts."""

  def __init__(self, current_hotkeys: Optional[Dict[str, str]] = None, parent=None):
    super().__init__(parent)
    self.setWindowTitle("快捷鍵設定")
    self.setModal(True)
    self.setFixedWidth(490)
    self.current_hotkeys = dict(config.DEFAULT_HOTKEYS)
    if current_hotkeys:
      self.current_hotkeys.update(current_hotkeys)
    self.edits: Dict[str, QKeySequenceEdit] = {}

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
        QKeySequenceEdit {{
            background-color: #0f172a;
            border: 1px solid rgba(255, 255, 255, 0.15);
            border-radius: 6px;
            color: #38bdf8;
            font-family: {config.FONT_FAMILY};
            font-size: 13px;
            font-weight: 600;
            padding: 6px 10px;
        }}
        QKeySequenceEdit:focus {{
            border: 1px solid #38bdf8;
            background-color: #1e293b;
        }}
        QPushButton {{
            background-color: rgba(255, 255, 255, 0.08);
            color: #e2e8f0;
            border: 1px solid rgba(255, 255, 255, 0.12);
            border-radius: 6px;
            padding: 5px 12px;
            font-size: 12px;
            font-family: {config.FONT_FAMILY};
        }}
        QPushButton:hover {{
            background-color: rgba(255, 255, 255, 0.16);
            border-color: rgba(255, 255, 255, 0.25);
        }}
        QPushButton:pressed {{
            background-color: rgba(255, 255, 255, 0.05);
        }}
    """)
    self._init_ui()

  def _init_ui(self):
    main_layout = QVBoxLayout(self)
    main_layout.setContentsMargins(24, 20, 24, 20)
    main_layout.setSpacing(16)

    # Title & Subtitle
    title_lbl = QLabel("自訂遊戲快捷鍵")
    title_lbl.setStyleSheet("font-size: 16px; font-weight: 700; color: #f8fafc;")
    main_layout.addWidget(title_lbl)

    desc_lbl = QLabel("點擊下方輸入框後，按下想要設定的按鍵組合 (例如 F6、Option+F6、Ctrl+1 等)")
    desc_lbl.setStyleSheet("font-size: 12px; color: #94a3b8;")
    desc_lbl.setWordWrap(True)
    main_layout.addWidget(desc_lbl)

    # Grid Container for Shortcuts (OBS Style)
    grid_frame = QFrame()
    grid_frame.setStyleSheet("""
        QFrame {
            background-color: rgba(0, 0, 0, 0.2);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 8px;
            padding: 8px;
        }
    """)
    grid = QGridLayout(grid_frame)
    grid.setContentsMargins(12, 12, 12, 12)
    grid.setHorizontalSpacing(10)
    grid.setVerticalSpacing(12)

    actions = [
        (config.HOTKEY_AUTO_START, "自動開始"),
        (config.HOTKEY_START_PAUSE, "開始 / 暫停"),
        (config.HOTKEY_RESET, "重置統計"),
        (config.HOTKEY_SWITCH_MODE, "切換模式"),
    ]

    for row, (action_key, action_label) in enumerate(actions):
      # Label
      lbl = QLabel(action_label)
      lbl.setStyleSheet("font-weight: 600; color: #e2e8f0; font-size: 13px;")
      lbl.setFixedWidth(85)
      grid.addWidget(lbl, row, 0)

      # Key Sequence Edit Box
      edit = QKeySequenceEdit()
      current_val = self.current_hotkeys.get(action_key, "")
      if current_val:
        edit.setKeySequence(QKeySequence(current_val))
      edit.setMinimumWidth(180)
      grid.addWidget(edit, row, 1)
      self.edits[action_key] = edit

      # Revert Button (↺)
      btn_revert = QPushButton("↺")
      btn_revert.setFixedSize(30, 30)
      btn_revert.setToolTip("恢復預設值")
      btn_revert.setStyleSheet("padding: 0px; font-size: 14px; font-weight: bold;")
      default_seq = config.DEFAULT_HOTKEYS.get(action_key, "")
      btn_revert.clicked.connect(lambda _, e=edit, d=default_seq: e.setKeySequence(QKeySequence(d)))
      grid.addWidget(btn_revert, row, 2)

      # Clear Button (✕)
      btn_clear = QPushButton("✕")
      btn_clear.setFixedSize(30, 30)
      btn_clear.setToolTip("清除快捷鍵")
      btn_clear.setStyleSheet("padding: 0px; font-size: 12px; color: #f87171;")
      btn_clear.clicked.connect(edit.clear)
      grid.addWidget(btn_clear, row, 3)

    main_layout.addWidget(grid_frame)

    # Tip Card
    tip_frame = QFrame()
    tip_frame.setStyleSheet("""
        QFrame {
            background-color: rgba(56, 189, 248, 0.08);
            border: 1px solid rgba(56, 189, 248, 0.2);
            border-radius: 6px;
            padding: 8px 12px;
        }
    """)
    tip_layout = QVBoxLayout(tip_frame)
    tip_layout.setContentsMargins(0, 0, 0, 0)
    tip_layout.setSpacing(6)

    if sys.platform == "darwin":
      tip_text = (
          "💡 <b>macOS 全域監聽說明：</b><br>"
          "• 含修飾鍵組合 (例如 <b>Option+F6~F9</b> 或 <b>Ctrl+1~4</b>)："
          "免任何系統權限即可直接在《楓之谷世界》背景全域生效！<br>"
          "• 若想使用純單鍵 (如純 F6)：需開啟系統偏好設定授權「輔助使用」。"
      )
      tip_lbl = QLabel(tip_text)
      tip_lbl.setWordWrap(True)
      tip_lbl.setStyleSheet("color: #bae6fd; font-size: 11px; line-height: 1.4;")
      tip_layout.addWidget(tip_lbl)

      btn_open_access = QPushButton("開啟 macOS 輔助使用設定")
      btn_open_access.setStyleSheet("""
          QPushButton {
              background-color: rgba(56, 189, 248, 0.15);
              color: #38bdf8;
              border: 1px solid rgba(56, 189, 248, 0.3);
              font-size: 11px;
              padding: 4px 8px;
          }
          QPushButton:hover {
              background-color: rgba(56, 189, 248, 0.25);
          }
      """)
      btn_open_access.clicked.connect(self._open_macos_accessibility)
      tip_layout.addWidget(btn_open_access)
    else:
      tip_lbl = QLabel("💡 <b>提示：</b>所有設定的快捷鍵均可在遊戲全螢幕或背景執行時全域觸發。")
      tip_lbl.setWordWrap(True)
      tip_lbl.setStyleSheet("color: #bae6fd; font-size: 11px;")
      tip_layout.addWidget(tip_lbl)

    main_layout.addWidget(tip_frame)

    # Bottom Actions Bar
    btn_bar = QHBoxLayout()
    btn_reset_all = QPushButton("全部重置預設")
    btn_reset_all.clicked.connect(self._reset_all_defaults)
    btn_bar.addWidget(btn_reset_all)

    btn_bar.addStretch()

    btn_cancel = QPushButton("取消")
    btn_cancel.clicked.connect(self.reject)
    btn_bar.addWidget(btn_cancel)

    btn_save = QPushButton("儲存設定")
    btn_save.setStyleSheet("""
        QPushButton {
            background-color: #0284c7;
            color: #ffffff;
            font-weight: 600;
            border: none;
            padding: 6px 18px;
        }
        QPushButton:hover {
            background-color: #0369a1;
        }
    """)
    btn_save.clicked.connect(self.accept)
    btn_bar.addWidget(btn_save)

    main_layout.addLayout(btn_bar)

  def _open_macos_accessibility(self):
    """Opens macOS System Settings directly to Privacy & Security -> Accessibility."""
    if sys.platform == "darwin":
      try:
        subprocess.Popen([
            "open",
            "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
        ])
      except Exception as e:
        logger.warning("Failed to open System Settings: %s", e)

  def _reset_all_defaults(self):
    """Resets all action edits to their platform defaults."""
    for action_key, edit in self.edits.items():
      default_seq = config.DEFAULT_HOTKEYS.get(action_key, "")
      edit.setKeySequence(QKeySequence(default_seq))

  def get_hotkeys(self) -> Dict[str, str]:
    """Returns the updated dictionary of action to portable key sequence string."""
    res = {}
    for action_key, edit in self.edits.items():
      seq = edit.keySequence()
      res[action_key] = seq.toString(QKeySequence.SequenceFormat.PortableText)
    return res



