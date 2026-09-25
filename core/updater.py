"""Cross-platform auto-update engine for Artale EXP Calculator.

Complies with the Google Python Style Guide.
Handles checking GitHub Releases, background asset downloads, checksum verification,
and platform-specific in-place updates with auto-restart.
"""

from dataclasses import dataclass
import hashlib
import json
import logging
import os
import platform
import re
import subprocess
import sys
import tempfile
from typing import Callable, Optional, Tuple
import urllib.error
import urllib.request

import config

logger = logging.getLogger(__name__)


@dataclass
class UpdateInfo:
  """Metadata describing an available application release."""

  version: str
  tag_name: str
  release_notes: str
  download_url: str
  asset_name: str
  asset_size: int
  published_at: str = ""
  sha256: Optional[str] = None


def parse_version_tuple(version_str: str) -> Tuple[int, int, int, int, int]:
  """Parses a semantic version string into a comparable tuple.

  Adheres to SemVer 2.0 precedence:
  - Official release (e.g. 1.0.0): (1, 0, 0, 1, 0)
  - Release candidate (e.g. 1.0.0-rc.1): (1, 0, 0, 0, 1)
  - Release candidate 2 (e.g. 1.0.0-rc.2): (1, 0, 0, 0, 2)
  This guarantees: 1.0.0-rc.1 < 1.0.0-rc.2 < 1.0.0.
  """
  v = version_str.lstrip("vV").strip()
  match = re.match(
      r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:[-._]?([a-zA-Z0-9.]+))?$", v
  )
  if not match:
    return (0, 0, 0, 1, 0)
  major = int(match.group(1) or 0)
  minor = int(match.group(2) or 0)
  patch = int(match.group(3) or 0)
  pre = match.group(4)
  if pre is None or pre == "":
    return (major, minor, patch, 1, 0)
  digits = re.findall(r"\d+", pre)
  pre_num = int(digits[0]) if digits else 0
  return (major, minor, patch, 0, pre_num)


def select_best_asset(
    assets: list, sys_platform: str = sys.platform, machine: Optional[str] = None
) -> Optional[dict]:
  """Selects the appropriate release asset based on OS and architecture."""
  if not assets:
    return None

  if machine is None:
    machine = platform.machine().lower()
  else:
    machine = machine.lower()

  is_arm = "arm" in machine or "aarch64" in machine

  if sys_platform == "win32":
    # Prefer Windows x64 zip
    for a in assets:
      name = a.get("name", "").lower()
      if ("win" in name or "windows" in name) and name.endswith(".zip"):
        return a
    # Fallback to any .zip
    for a in assets:
      name = a.get("name", "").lower()
      if name.endswith(".zip"):
        return a

  elif sys_platform == "darwin":
    # Prefer macOS Apple Silicon or Intel based on current ISA
    if is_arm:
      for a in assets:
        name = a.get("name", "").lower()
        if ("mac" in name or "darwin" in name) and (
            "arm64" in name or "apple" in name or "silicon" in name
        ):
          return a
    else:
      for a in assets:
        name = a.get("name", "").lower()
        if ("mac" in name or "darwin" in name) and (
            "x86_64" in name or "intel" in name or "x64" in name
        ):
          return a
    # Fallback to any mac asset or zip
    for a in assets:
      name = a.get("name", "").lower()
      if "mac" in name and (name.endswith(".zip") or name.endswith(".dmg")):
        return a

  # Generic fallback to first asset
  return assets[0]


def check_for_update(
    repo: str = config.APP_GITHUB_REPO,
    current_version: str = config.APP_VERSION,
    timeout: int = 5,
    include_prereleases: Optional[bool] = None,
) -> Tuple[bool, Optional[UpdateInfo], str]:
  """Checks GitHub Releases API for a newer version.

  Returns:
      (has_update, update_info_if_any, status_message)
  """
  if include_prereleases is None:
    # If the user is currently on a pre-release (e.g. 1.0.0-rc.1), include pre-releases
    include_prereleases = "-" in current_version

  url = f"https://api.github.com/repos/{repo}/releases?per_page=10"
  req = urllib.request.Request(
      url,
      headers={
          "User-Agent": "ArtaleExpCalculator-Updater",
          "Accept": "application/vnd.github.v3+json",
      },
  )
  try:
    with urllib.request.urlopen(req, timeout=timeout) as resp:
      if resp.status != 200:
        return False, None, f"伺服器回應狀態碼: {resp.status}"
      raw_data = json.loads(resp.read().decode("utf-8"))
  except urllib.error.URLError as e:
    return False, None, f"網路連線失敗: {e}"
  except Exception as e:
    return False, None, f"更新檢查發生錯誤: {e}"

  if isinstance(raw_data, dict):
    releases_list = [raw_data]
  elif isinstance(raw_data, list):
    releases_list = raw_data
  else:
    return False, None, "未找到有效的發行版本資料"

  if not releases_list:
    return False, None, "尚未發布任何版本"

  candidates = [
      r for r in releases_list
      if not r.get("draft", False)
      and (include_prereleases or not r.get("prerelease", False))
  ]
  if not candidates:
    return False, None, f"目前已是最新版本 ({config.get_full_version_string()}) ✓"

  # Pick candidate with highest semantic version
  data = max(candidates, key=lambda r: parse_version_tuple(r.get("tag_name", "")))
  tag_name = data.get("tag_name", "").strip()
  if not tag_name:
    return False, None, "未找到有效的發行版本標籤"

  remote_version = tag_name.lstrip("vV")
  latest_tuple = parse_version_tuple(remote_version)
  current_tuple = parse_version_tuple(current_version)

  if latest_tuple <= current_tuple:
    return False, None, f"目前已是最新版本 ({config.get_full_version_string()}) ✓"

  # Find matching platform asset
  assets = data.get("assets", [])
  matched_asset = select_best_asset(assets)
  if not matched_asset:
    html_url = data.get(
        "html_url", f"https://github.com/{repo}/releases/latest"
    )
    info = UpdateInfo(
        version=remote_version,
        tag_name=tag_name,
        release_notes=data.get("body", "無更新日誌說明"),
        download_url=html_url,
        asset_name="browser_release",
        asset_size=0,
        published_at=data.get("published_at", ""),
    )
    return True, info, f"發現新版本 v{remote_version} (無直接下載包，請前往網頁下載)"

  info = UpdateInfo(
      version=remote_version,
      tag_name=tag_name,
      release_notes=data.get("body", "無更新日誌說明"),
      download_url=matched_asset.get("browser_download_url", ""),
      asset_name=matched_asset.get("name", "update.zip"),
      asset_size=matched_asset.get("size", 0),
      published_at=data.get("published_at", ""),
  )
  return True, info, f"發現新版本 v{remote_version}"


def download_file(
    url: str,
    destination_path: str,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    timeout: int = 30,
) -> bool:
  """Downloads a remote file with progress tracking."""
  req = urllib.request.Request(
      url,
      headers={"User-Agent": "ArtaleExpCalculator-Updater"},
  )
  try:
    with urllib.request.urlopen(req, timeout=timeout) as response:
      total_size = int(response.headers.get("content-length", 0))
      downloaded = 0
      chunk_size = 64 * 1024

      with open(destination_path, "wb") as f:
        while True:
          chunk = response.read(chunk_size)
          if not chunk:
            break
          f.write(chunk)
          downloaded += len(chunk)
          if progress_callback:
            progress_callback(downloaded, total_size)
    return True
  except Exception as e:
    logger.error("Download failed: %s", e)
    if os.path.exists(destination_path):
      try:
        os.remove(destination_path)
      except OSError:
        pass
    return False


def verify_file_sha256(file_path: str, expected_sha256: str) -> bool:
  """Verifies the SHA256 checksum of a downloaded file."""
  if not expected_sha256:
    return True
  hasher = hashlib.sha256()
  with open(file_path, "rb") as f:
    while chunk := f.read(64 * 1024):
      hasher.update(chunk)
  return hasher.hexdigest().lower() == expected_sha256.lower().strip()


def apply_update_and_restart(
    archive_path: str,
    target_dir: Optional[str] = None,
    is_dev: bool = config.IS_DEV,
) -> Tuple[bool, str]:
  """Prepares and launches the detached swap script, then exits the current application.

  In development mode, in-place replacement is blocked to protect git repositories.
  """
  if is_dev or not getattr(sys, "frozen", False):
    return (
        False,
        "目前處於開發環境 (Source Code Mode)，請透過 git pull 更新以維護原始程式碼。",
    )

  if target_dir is None:
    target_dir = config.APP_DIR

  current_pid = os.getpid()

  if sys.platform == "win32":
    bat_content = f"""@echo off
chcp 65001 >nul
set PID={current_pid}
set ARCHIVE="{archive_path}"
set TARGET="{target_dir}"

:WAIT_PROCESS
tasklist /fi "PID eq %PID%" 2>nul | find "%PID%" >nul
if "%ERRORLEVEL%"=="0" (
    timeout /t 1 /nobreak >nul
    goto WAIT_PROCESS
)

rem Extract new archive into target directory
powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath '%ARCHIVE%' -DestinationPath '%TARGET%' -Force"

rem Restart main application
cd /d "%TARGET%"
start "" "%TARGET%\\ArtaleExpCalculator.exe"

rem Clean up update archive and script
del "%ARCHIVE%" >nul 2>&1
(goto) 2>nul & del "%~f0"
"""
    script_path = os.path.join(tempfile.gettempdir(), f"artale_update_{current_pid}.bat")
    try:
      with open(script_path, "w", encoding="utf-8") as f:
        f.write(bat_content)

      # Launch detached process on Windows
      subprocess.Popen(
          ["cmd.exe", "/c", script_path],
          creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
          close_fds=True,
      )
      return True, "更新程序已啟動，正在重啟軟體..."
    except Exception as e:
      return False, f"啟動更新程序失敗: {e}"

  elif sys.platform == "darwin":
    sh_content = f"""#!/bin/bash
PID={current_pid}
ARCHIVE="{archive_path}"
TARGET="{target_dir}"

while kill -0 "$PID" 2>/dev/null; do
    sleep 1
done

TMP_DIR=$(mktemp -d /tmp/artale_update_XXXXXX)
unzip -q -o "$ARCHIVE" -d "$TMP_DIR"
NEW_APP=$(find "$TMP_DIR" -maxdepth 2 -name "ArtaleExpCalculator.app" | head -n 1)

if [ -n "$NEW_APP" ]; then
    rm -rf "$TARGET"
    cp -R "$NEW_APP" "$TARGET"
    xattr -dr com.apple.quarantine "$TARGET" 2>/dev/null || true
fi

rm -rf "$TMP_DIR" "$ARCHIVE"
open -n "$TARGET"
rm -- "$0"
"""
    script_path = os.path.join(tempfile.gettempdir(), f"artale_update_{current_pid}.sh")
    try:
      with open(script_path, "w", encoding="utf-8") as f:
        f.write(sh_content)
      os.chmod(script_path, 0o755)

      subprocess.Popen(
          ["/bin/bash", script_path],
          start_new_session=True,
          close_fds=True,
      )
      return True, "更新程序已啟動，正在重啟軟體..."
    except Exception as e:
      return False, f"啟動更新程序失敗: {e}"

  return False, f"不支援的作業系統: {sys.platform}"
