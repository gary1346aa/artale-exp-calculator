#!/bin/bash
# ========================================================
#   Artale EXP Calculator - macOS Standalone Build Script
# ========================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

echo "========================================================"
echo "  Building Artale EXP Calculator for macOS"
echo "========================================================"

cd "$ROOT_DIR"

# 1. Compile native C++ library with AppleClang
echo "[BUILD] Compiling native C++ engine (libartale_exp_core.dylib)..."
ARCH="$(uname -m)"
if [ "$ARCH" = "arm64" ]; then
    ARCH_FLAGS="-march=armv8-a"
else
    ARCH_FLAGS="-mavx2 -mfma"
fi

clang++ -std=c++17 -O3 $ARCH_FLAGS \
    -dynamiclib -fPIC \
    -Isrc/cpp/include -Isrc/cpp/src \
    src/cpp/src/exp_engine.cc src/cpp/src/artale_exp_core.cc \
    -o libartale_exp_core.dylib

echo "[BUILD] libartale_exp_core.dylib compiled successfully."

# 2. Check/Install PyInstaller
if ! python3 -c "import PyInstaller" 2>/dev/null; then
    echo "[BUILD] Installing PyInstaller..."
    pip3 install pyinstaller
fi

# 3. Build .app Bundle with PyInstaller
echo "[BUILD] Packaging ArtaleExpCalculator.app..."
python3 scripts/build_app.py "$@"

echo "========================================================"
echo "  Build Complete! App located at: dist/ArtaleExpCalculator.app"
echo "========================================================"
