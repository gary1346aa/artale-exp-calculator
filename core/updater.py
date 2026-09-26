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
import ssl
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

  # Filter out non-archive assets (checksums, manifests, text files, signatures)
  archive_assets = [
      a for a in assets
      if not a.get("name", "").lower().endswith(
          (".sha256", ".sha512", ".sha1", ".md5", ".txt", ".json", ".sig")
      )
  ]
  if not archive_assets:
    archive_assets = assets

  if sys_platform == "win32":
    # Prefer Windows x64 zip / exe
    for a in archive_assets:
      name = a.get("name", "").lower()
      if ("win" in name or "windows" in name) and (
          name.endswith(".zip") or name.endswith(".exe")
      ):
        return a
    # Fallback to any .zip
    for a in archive_assets:
      name = a.get("name", "").lower()
      if name.endswith(".zip"):
        return a

  elif sys_platform == "darwin":
    # Prefer macOS Apple Silicon or Intel based on current ISA
    if is_arm:
      for a in archive_assets:
        name = a.get("name", "").lower()
        if (
            ("mac" in name or "darwin" in name)
            and ("arm64" in name or "apple" in name or "silicon" in name)
            and (name.endswith(".zip") or name.endswith(".dmg"))
        ):
          return a
    else:
      for a in archive_assets:
        name = a.get("name", "").lower()
        if (
            ("mac" in name or "darwin" in name)
            and ("x86_64" in name or "intel" in name or "x64" in name)
            and (name.endswith(".zip") or name.endswith(".dmg"))
        ):
          return a
    # Fallback to any mac asset ending with .zip or .dmg
    for a in archive_assets:
      name = a.get("name", "").lower()
      if ("mac" in name or "darwin" in name) and (
          name.endswith(".zip") or name.endswith(".dmg")
      ):
        return a
    # Fallback to any .zip
    for a in archive_assets:
      name = a.get("name", "").lower()
      if name.endswith(".zip"):
        return a

  # Generic fallback: only return an archive asset
  for a in archive_assets:
    name = a.get("name", "").lower()
    if name.endswith((".zip", ".dmg", ".tar.gz", ".exe")):
      return a

  return archive_assets[0] if archive_assets else None


def get_ssl_context() -> ssl.SSLContext:
  """Creates an SSLContext configured with system or bundled CA certificates.

  On macOS, packaged Python environments often fail to locate root CA
  certificates, leading to [SSL: CERTIFICATE_VERIFY_FAILED]. This function
  attempts to locate certificates via certifi or standard macOS certificate locations.
  """
  # 1. Try certifi if installed
  try:
    import certifi
    cafile = certifi.where()
    if os.path.exists(cafile):
      return ssl.create_default_context(cafile=cafile)
  except Exception:
    pass

  # 2. Try known macOS / Unix system certificate paths
  ca_candidates = [
      "/etc/ssl/cert.pem",
      "/private/etc/ssl/cert.pem",
      "/usr/local/etc/openssl/cert.pem",
      "/opt/homebrew/etc/openssl/cert.pem",
      "/etc/pki/tls/certs/ca-bundle.crt",
      "/etc/ssl/certs/ca-certificates.crt",
  ]
  for path in ca_candidates:
    if os.path.exists(path):
      try:
        return ssl.create_default_context(cafile=path)
      except Exception:
        continue

  # 3. Default system context
  try:
    return ssl.create_default_context()
  except Exception:
    pass

  # 4. Fallback to unverified context
  return ssl._create_unverified_context()


def _safe_urlopen(
    req: urllib.request.Request,
    timeout: int = 10,
    context: Optional[ssl.SSLContext] = None,
):
  """Opens a URL with robust SSL certificate handling and graceful fallback.

  Attempts to verify certificates first; if SSL certificate verification
  fails (e.g. on macOS without root CA bundles), automatically falls back
  to an unverified context so update checks and downloads can proceed.
  """
  ctx = context if context is not None else get_ssl_context()
  try:
    return urllib.request.urlopen(req, timeout=timeout, context=ctx)
  except urllib.error.URLError as e:
    err_str = str(e).lower()
    is_ssl_cert_err = (
        "certificate verify failed" in err_str
        or "certificate_verify_failed" in err_str
        or (hasattr(e, "reason") and isinstance(e.reason, ssl.SSLError))
        or "ssl" in err_str
    )
    if is_ssl_cert_err:
      logger.warning(
          "SSL certificate verification failed (%s). Retrying with unverified context...",
          e,
      )
      fallback_ctx = ssl._create_unverified_context()
      return urllib.request.urlopen(req, timeout=timeout, context=fallback_ctx)
    raise


def _fetch_fallback_manifest(repo: str, timeout: int = 5) -> Optional[dict]:
  """Fetches latest.json from raw.githubusercontent.com as a rate-limit fallback."""
  urls = [
      f"https://raw.githubusercontent.com/{repo}/refs/heads/master/latest.json",
      f"https://raw.githubusercontent.com/{repo}/master/latest.json",
  ]
  for url in urls:
    try:
      req = urllib.request.Request(
          url,
          headers={"User-Agent": "ArtaleExpCalculator-Updater"},
      )
      with _safe_urlopen(req, timeout=timeout) as resp:
        if resp.status == 200:
          return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
      logger.debug("Fallback manifest fetch failed for %s: %s", url, e)
  return None


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

  raw_data = None
  url = f"https://api.github.com/repos/{repo}/releases?per_page=10"
  req = urllib.request.Request(
      url,
      headers={
          "User-Agent": "ArtaleExpCalculator-Updater",
          "Accept": "application/vnd.github.v3+json",
      },
  )
  try:
    with _safe_urlopen(req, timeout=timeout) as resp:
      if resp.status == 200:
        raw_data = json.loads(resp.read().decode("utf-8"))
  except Exception as e:
    logger.debug("GitHub Releases API request failed: %s; trying manifest fallback", e)
    # Attempt rate-limit-free fallback via latest.json
    manifest = _fetch_fallback_manifest(repo, timeout=timeout)
    if manifest:
      tag_name = manifest.get("tag", "").strip()
      remote_version = manifest.get("version", tag_name.lstrip("vV"))
      latest_tuple = parse_version_tuple(remote_version)
      current_tuple = parse_version_tuple(current_version)

      if latest_tuple <= current_tuple:
        return False, None, f"目前已是最新版本 ({config.get_full_version_string()}) ✓"

      platform_key = "win-x64" if sys.platform == "win32" else "mac-arm64"
      download_info = manifest.get("downloads", {}).get(platform_key, {})
      download_url = download_info.get(
          "url", f"https://github.com/{repo}/releases/tag/{tag_name}"
      )
      sha256 = download_info.get("sha256")
      asset_name = download_url.split("/")[-1] if download_url else "update.zip"

      info = UpdateInfo(
          version=remote_version,
          tag_name=tag_name,
          release_notes="請前往 GitHub 查看最新發行版本說明",
          download_url=download_url,
          asset_name=asset_name,
          asset_size=0,
          published_at=manifest.get("release_date", ""),
          sha256=sha256,
      )
      return True, info, f"發現新版本 v{remote_version}"

    if isinstance(e, urllib.error.URLError):
      return False, None, f"網路連線失敗: {e}"
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
    with _safe_urlopen(req, timeout=timeout) as response:
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
    if sys.platform == "darwin" and getattr(sys, "frozen", False):
      exe_path = os.path.abspath(sys.executable)
      curr = exe_path
      found_app = None
      while curr and curr != os.path.dirname(curr):
        if curr.endswith(".app"):
          found_app = curr
          break
        curr = os.path.dirname(curr)
      target_dir = found_app if found_app else config.APP_DIR
    else:
      target_dir = config.APP_DIR

  current_pid = os.getpid()

  if sys.platform == "win32":
    ps1_content = f"""$ErrorActionPreference = 'SilentlyContinue'
$pidToWait = {current_pid}
$archive = '{archive_path}'
$target = '{target_dir}'

# 1. Wait up to 10 seconds for current process to exit
try {{
    $proc = Get-Process -Id $pidToWait -ErrorAction SilentlyContinue
    if ($proc) {{
        $proc.WaitForExit(10000)
    }}
}} catch {{}}

Start-Sleep -Milliseconds 600

# 2. Extract update archive into target directory
try {{
    Expand-Archive -LiteralPath $archive -DestinationPath $target -Force
}} catch {{}}

# 3. Restart main application
$exe = Join-Path $target 'ArtaleExpCalculator.exe'
if (Test-Path $exe) {{
    Start-Process -FilePath $exe -WorkingDirectory $target
}}

# 4. Clean up update archive and script
Remove-Item -LiteralPath $archive -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $MyInvocation.MyCommand.Path -Force -ErrorAction SilentlyContinue
"""
    script_path = os.path.join(tempfile.gettempdir(), f"artale_update_{current_pid}.ps1")
    try:
      with open(script_path, "w", encoding="utf-8") as f:
        f.write(ps1_content)

      # Launch hidden background PowerShell process on Windows (CREATE_NO_WINDOW + NEW_PROCESS_GROUP)
      CREATE_NO_WINDOW = 0x08000000
      subprocess.Popen(
          [
              "powershell.exe",
              "-NoProfile",
              "-NonInteractive",
              "-WindowStyle",
              "Hidden",
              "-ExecutionPolicy",
              "Bypass",
              "-File",
              script_path,
          ],
          creationflags=CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
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
    if command -v ditto >/dev/null 2>&1; then
        ditto "$NEW_APP" "$TARGET"
    else
        cp -a "$NEW_APP" "$TARGET"
    fi
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
