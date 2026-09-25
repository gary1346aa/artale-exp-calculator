"""Cross-Platform Application Build Script for Artale EXP Calculator.

Builds standalone distributables for Windows (.exe) and macOS (.app bundle):
1. Compiles the native C++ SIMD engine (DLL / dylib) if not already built.
2. Bundles Python runtime, assets, font prototypes, and native binary via PyInstaller.
3. Outputs to the dist/ directory.

Usage:
    python scripts/build_app.py
    python scripts/build_app.py --clean
    python scripts/build_app.py --skip-native
"""

import argparse
import os
import platform
import shutil
import subprocess
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def log(msg: str) -> None:
  """Prints formatted status message."""
  print(f"[BUILD] {msg}", flush=True)


def ensure_native_library() -> bool:
  """Ensures the native C++ shared library exists, building it if needed.

  Returns:
    True if native library is available, False otherwise.
  """
  current_os = platform.system()
  log(f"Detected platform: {current_os} ({platform.machine()})")

  # 1. Check existing build artifacts
  if current_os == "Windows":
    candidates = [
        os.path.join(BASE_DIR, "bazel-bin", "src", "cpp", "libartale_exp_core_dll.so"),
        os.path.join(BASE_DIR, "bazel-bin", "src", "cpp", "artale_exp_core.dll"),
        os.path.join(BASE_DIR, "build", "artale_exp_core.dll"),
        os.path.join(BASE_DIR, "artale_exp_core.dll"),
    ]
  elif current_os == "Darwin":
    candidates = [
        os.path.join(BASE_DIR, "libartale_exp_core.dylib"),
        os.path.join(BASE_DIR, "build", "libartale_exp_core.dylib"),
        os.path.join(BASE_DIR, "bazel-bin", "src", "cpp", "libartale_exp_core.dylib"),
    ]
  else:
    candidates = [
        os.path.join(BASE_DIR, "libartale_exp_core.so"),
        os.path.join(BASE_DIR, "build", "libartale_exp_core.so"),
    ]

  for c in candidates:
    if os.path.exists(c):
      log(f"Found existing native library: {os.path.relpath(c, BASE_DIR)}")
      return True

  # 2. Build via CMake or Clang if not found
  log("Native library not found. Attempting build...")

  if current_os == "Darwin":
    # macOS clang++ build
    output_dylib = os.path.join(BASE_DIR, "libartale_exp_core.dylib")
    arch_flag = "-march=armv8-a" if platform.machine() == "arm64" else "-mavx2"
    cmd = [
        "clang++",
        "-std=c++17",
        "-O3",
        arch_flag,
        "-dynamiclib",
        "-fPIC",
        "-I",
        os.path.join(BASE_DIR, "src", "cpp", "include"),
        "-I",
        os.path.join(BASE_DIR, "src", "cpp", "src"),
        os.path.join(BASE_DIR, "src", "cpp", "src", "exp_engine.cc"),
        os.path.join(BASE_DIR, "src", "cpp", "src", "artale_exp_core.cc"),
        "-o",
        output_dylib,
    ]
    log(f"Running: {' '.join(cmd)}")
    res = subprocess.run(cmd, cwd=BASE_DIR)
    if res.returncode == 0 and os.path.exists(output_dylib):
      log(f"Successfully compiled native library: {output_dylib}")
      return True

  # Try CMake build
  cmake_dir = os.path.join(BASE_DIR, "build")
  os.makedirs(cmake_dir, exist_ok=True)
  try:
    log("Invoking CMake...")
    r1 = subprocess.run(
        ["cmake", os.path.join(BASE_DIR, "src", "cpp"), "-DCMAKE_BUILD_TYPE=Release"],
        cwd=cmake_dir,
    )
    if r1.returncode == 0:
      r2 = subprocess.run(["cmake", "--build", ".", "--config", "Release"], cwd=cmake_dir)
      if r2.returncode == 0:
        log("CMake build succeeded.")
        return True
  except FileNotFoundError:
    pass

  # Try Bazel build
  try:
    log("Invoking Bazel...")
    r = subprocess.run(["bazel", "build", "//src/cpp:artale_exp_core_dll"], cwd=BASE_DIR)
    if r.returncode == 0:
      log("Bazel build succeeded.")
      return True
  except FileNotFoundError:
    pass

  log("Warning: Could not build native C++ library. Pure Python engine will be used as fallback.")
  return False


def build_pyinstaller(clean: bool = False) -> int:
  """Invokes PyInstaller using ArtaleExpCalculator.spec.

  Args:
    clean: Whether to clean build caches before bundling.

  Returns:
    Exit code from PyInstaller process.
  """
  spec_path = os.path.join(BASE_DIR, "ArtaleExpCalculator.spec")
  if not os.path.exists(spec_path):
    log(f"Error: {spec_path} does not exist.")
    return 1

  cmd = [sys.executable, "-m", "PyInstaller"]
  if clean:
    cmd.append("--clean")
  cmd.extend(["--noconfirm", spec_path])

  log(f"Running PyInstaller: {' '.join(cmd)}")
  res = subprocess.run(cmd, cwd=BASE_DIR)
  if res.returncode == 0:
    dist_dir = os.path.join(BASE_DIR, "dist")
    log("=" * 60)
    log(f"SUCCESS! Application packaged into: {dist_dir}")
    if platform.system() == "Darwin":
      app_path = os.path.join(dist_dir, "ArtaleExpCalculator.app")
      log(f"macOS Bundle: {app_path}")
    else:
      exe_path = os.path.join(dist_dir, "ArtaleExpCalculator", "ArtaleExpCalculator.exe")
      log(f"Windows Executable: {exe_path}")
    log("=" * 60)
  else:
    log(f"PyInstaller failed with code {res.returncode}")
  return res.returncode


def main() -> None:
  """Parses arguments and runs the build process."""
  parser = argparse.ArgumentParser(description="Build Artale EXP Calculator Application")
  parser.add_argument("--clean", action="store_true", help="Clean build directories before packaging")
  parser.add_argument("--skip-native", action="store_true", help="Skip native C++ library build check")
  args = parser.parse_args()

  if args.clean:
    for d in ["build", "dist"]:
      p = os.path.join(BASE_DIR, d)
      if os.path.exists(p):
        log(f"Removing {p}")
        shutil.rmtree(p, ignore_errors=True)

  if not args.skip_native:
    ensure_native_library()

  exit_code = build_pyinstaller(clean=args.clean)
  sys.exit(exit_code)


if __name__ == "__main__":
  main()
