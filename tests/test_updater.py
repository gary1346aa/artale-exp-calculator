"""Unit tests for core.updater module."""

import hashlib
import os
import sys
import tempfile
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.updater import (
    check_for_update,
    parse_version_tuple,
    select_best_asset,
    verify_file_sha256,
)


class TestUpdater(unittest.TestCase):

  def test_parse_version_tuple(self):
    self.assertEqual(parse_version_tuple("1.0.0"), (1, 0, 0, 1, 0))
    self.assertEqual(parse_version_tuple("v1.2.3"), (1, 2, 3, 1, 0))
    self.assertEqual(parse_version_tuple("1.0.0-rc.1"), (1, 0, 0, 0, 1))
    self.assertEqual(parse_version_tuple("1.0.0-rc.2"), (1, 0, 0, 0, 2))
    self.assertEqual(parse_version_tuple("V2.0.1b"), (2, 0, 1, 0, 0))
    self.assertTrue(parse_version_tuple("1.0.0-rc.1") < parse_version_tuple("1.0.0-rc.2"))
    self.assertTrue(parse_version_tuple("1.0.0-rc.1") < parse_version_tuple("1.0.0"))
    self.assertTrue(parse_version_tuple("1.0.0-rc.2") < parse_version_tuple("1.0.0"))
    self.assertTrue(parse_version_tuple("1.0.1-rc.1") > parse_version_tuple("1.0.0"))
    self.assertTrue(parse_version_tuple("1.10.0") > parse_version_tuple("1.9.5"))
    self.assertTrue(parse_version_tuple("2.0.0") > parse_version_tuple("1.99.99"))
    self.assertEqual(parse_version_tuple("1.0.0"), parse_version_tuple("v1.0.0"))

  def test_select_best_asset_windows(self):
    assets = [
        {"name": "ArtaleExpCalculator-mac-arm64.zip", "browser_download_url": "http://mac"},
        {"name": "ArtaleExpCalculator-win-x64.zip", "browser_download_url": "http://win"},
    ]
    selected = select_best_asset(assets, sys_platform="win32", machine="AMD64")
    self.assertIsNotNone(selected)
    self.assertEqual(selected["name"], "ArtaleExpCalculator-win-x64.zip")

  def test_select_best_asset_macos_arm64(self):
    assets = [
        {"name": "ArtaleExpCalculator-mac-x86_64.zip", "browser_download_url": "http://mac-intel"},
        {"name": "ArtaleExpCalculator-mac-arm64.zip", "browser_download_url": "http://mac-arm"},
        {"name": "ArtaleExpCalculator-win-x64.zip", "browser_download_url": "http://win"},
    ]
    selected = select_best_asset(assets, sys_platform="darwin", machine="arm64")
    self.assertIsNotNone(selected)
    self.assertEqual(selected["name"], "ArtaleExpCalculator-mac-arm64.zip")

  def test_select_best_asset_macos_intel(self):
    assets = [
        {"name": "ArtaleExpCalculator-mac-x86_64.zip", "browser_download_url": "http://mac-intel"},
        {"name": "ArtaleExpCalculator-mac-arm64.zip", "browser_download_url": "http://mac-arm"},
    ]
    selected = select_best_asset(assets, sys_platform="darwin", machine="x86_64")
    self.assertIsNotNone(selected)
    self.assertEqual(selected["name"], "ArtaleExpCalculator-mac-x86_64.zip")

  def test_check_for_update_higher_version(self):
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = b"""{
      "tag_name": "v1.2.0",
      "body": "Bugfixes and new features",
      "assets": [
        {"name": "ArtaleExpCalculator-win-x64.zip", "browser_download_url": "https://github.com/test/download.zip", "size": 12345}
      ]
    }"""
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_resp
    with patch("urllib.request.urlopen", return_value=mock_cm):
      has_update, info, msg = check_for_update(current_version="1.0.0")
      self.assertTrue(has_update)
      self.assertIsNotNone(info)
      self.assertEqual(info.version, "1.2.0")
      self.assertEqual(info.asset_name, "ArtaleExpCalculator-win-x64.zip")
      self.assertIn("1.2.0", msg)

  def test_check_for_update_already_latest(self):
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = b'{"tag_name": "v1.0.0", "body": "Initial", "assets": []}'
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_resp
    with patch("urllib.request.urlopen", return_value=mock_cm):
      has_update, info, msg = check_for_update(current_version="1.0.0")
      self.assertFalse(has_update)
      self.assertIsNone(info)
      self.assertIn("最新版本", msg)

  def test_check_for_update_fallback_manifest(self):
    mock_manifest = {
        "tag": "v1.5.0",
        "version": "1.5.0",
        "release_date": "2026-09-26",
        "downloads": {
            "win-x64": {
                "url": "https://github.com/repo/releases/download/v1.5.0/win.zip",
                "sha256": "fakehash",
            }
        },
    }
    with patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.HTTPError(
            "url", 403, "Rate Limit", {}, None
        ),
    ):
      with patch(
          "core.updater._fetch_fallback_manifest", return_value=mock_manifest
      ):
        has_update, info, msg = check_for_update(current_version="1.0.0")
        self.assertTrue(has_update)
        self.assertIsNotNone(info)
        self.assertEqual(info.version, "1.5.0")
        self.assertEqual(info.sha256, "fakehash")
        self.assertIn("1.5.0", msg)

  def test_verify_file_sha256(self):
    with tempfile.NamedTemporaryFile("w+", delete=False) as f:
      f.write("Artale EXP Calculator Test Content")
      f_path = f.name

    try:
      expected_hash = hashlib.sha256(b"Artale EXP Calculator Test Content").hexdigest()
      self.assertTrue(verify_file_sha256(f_path, expected_hash))
      self.assertFalse(verify_file_sha256(f_path, "wrong_hash_123456"))
    finally:
      if os.path.exists(f_path):
        os.remove(f_path)

  def test_get_ssl_context(self):
    from core.updater import get_ssl_context
    import ssl
    ctx = get_ssl_context()
    self.assertIsInstance(ctx, ssl.SSLContext)

  def test_safe_urlopen_ssl_retry(self):
    from core.updater import _safe_urlopen
    import ssl

    mock_req = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status = 200

    ssl_error = urllib.error.URLError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed")
    call_count = 0

    def fake_urlopen(req, timeout=10, context=None):
      nonlocal call_count
      call_count += 1
      if call_count == 1:
        raise ssl_error
      return mock_resp

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
      resp = _safe_urlopen(mock_req, timeout=5)
      self.assertEqual(resp, mock_resp)
      self.assertEqual(call_count, 2)

  def test_safe_urlopen_non_ssl_error(self):
    from core.updater import _safe_urlopen

    mock_req = MagicMock()
    network_error = urllib.error.URLError("Connection refused")

    with patch("urllib.request.urlopen", side_effect=network_error):
      with self.assertRaises(urllib.error.URLError):
        _safe_urlopen(mock_req, timeout=5)


if __name__ == "__main__":
  unittest.main()

