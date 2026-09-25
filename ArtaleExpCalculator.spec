# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build specification for Artale EXP Calculator.

Supports Windows (.exe onedir/onefile) and macOS (.app bundle).
Complies with Google Style Guide conventions.
"""

import os
import sys

block_cipher = None

# Platform-specific native library discovery
binaries = []
if sys.platform == "win32":
  candidates = [
      os.path.join("bazel-bin", "src", "cpp", "libartale_exp_core_dll.so"),
      os.path.join("bazel-bin", "src", "cpp", "artale_exp_core.dll"),
      "artale_exp_core.dll",
      os.path.join("build", "artale_exp_core.dll"),
  ]
  for cand in candidates:
    if os.path.exists(cand):
      # Map to artale_exp_core.dll in the bundle root
      binaries.append((cand, "."))
      break
elif sys.platform == "darwin":
  candidates = [
      "libartale_exp_core.dylib",
      os.path.join("build", "libartale_exp_core.dylib"),
      os.path.join("bazel-bin", "src", "cpp", "libartale_exp_core.dylib"),
  ]
  for cand in candidates:
    if os.path.exists(cand):
      binaries.append((cand, "."))
      break

datas = [
    ("data", "data"),
    ("assets", "assets"),
]

hiddenimports = [
    "PyQt6.QtCore",
    "PyQt6.QtGui",
    "PyQt6.QtWidgets",
    "core",
    "core.engine",
    "core.metrics",
    "core.capture",
    "core.python_engine",
    "ui",
    "ui.components",
    "ui.dialogs",
    "ui.hotkeys",
    "ui.overlay",
    "dev",
    "dev.cli_tracker",
    "dev.video_simulation",
    "dev.window_picker",
    "config",
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "notebook", "scipy"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ArtaleExpCalculator",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=(
        os.path.join("assets", "app_icon.ico")
        if sys.platform == "win32" and os.path.exists(os.path.join("assets", "app_icon.ico"))
        else None
    ),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="ArtaleExpCalculator",
)

if sys.platform == "darwin":
  app = BUNDLE(
      coll,
      name="ArtaleExpCalculator.app",
      icon=os.path.join("assets", "app_icon.png") if os.path.exists(os.path.join("assets", "app_icon.png")) else None,
      bundle_identifier="com.artale.expcalculator",
      info_plist={
          "CFBundleDisplayName": "Artale EXP Calculator",
          "CFBundleShortVersionString": "1.0.0",
          "NSHighResolutionCapable": "True",
      },
  )
