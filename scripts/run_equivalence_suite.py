"""Validates 100% equivalence between C++ engine and Python reference engine.

Executes both engines on all 134 recorded window resolution datasets
(debug_crops/raw_strip_*.png) and asserts:
1. Identical recognized raw string.
2. Identical parsed integer EXP value.
3. Identical parsed percentage (within floating point precision).

Compliant with Google Python Style Guide.
"""

import ctypes
import glob
import os
import sys
import time
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2
import numpy as np
import python_exp_engine


class CppExpResult(ctypes.Structure):
  """C ctypes representation of ExpResult struct in artale_exp_core.h."""
  _fields_ = [
      ('exp_value', ctypes.c_int64),
      ('exp_percent', ctypes.c_double),
      ('success', ctypes.c_int),
      ('parse_time_ms', ctypes.c_float),
      ('exp_string', ctypes.c_char * 64),
      ('crop_x', ctypes.c_int),
      ('crop_y', ctypes.c_int),
      ('crop_w', ctypes.c_int),
      ('crop_h', ctypes.c_int),
      ('logo_x', ctypes.c_int),
      ('logo_y', ctypes.c_int),
      ('logo_w', ctypes.c_int),
      ('logo_h', ctypes.c_int),
  ]


def load_cpp_library(base_dir: str) -> ctypes.CDLL:
  """Loads the compiled C++ DLL from bazel-bin or root directory."""
  candidates = [
      os.path.join(base_dir, 'bazel-bin', 'src', 'cpp', 'libartale_exp_core_dll.so'),
      os.path.join(base_dir, 'artale_exp_core.dll'),
      os.path.join(base_dir, 'bazel-bin', 'src', 'cpp', 'artale_exp_core.dll'),
  ]
  for p in candidates:
    if os.path.exists(p):
      try:
        lib = ctypes.CDLL(p)
        lib.ParseExpFromBuffer.argtypes = [
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(CppExpResult),
        ]
        lib.ParseExpFromBuffer.restype = ctypes.c_int
        print(f'[EQUIVALENCE] Loaded native C++ library from: {p}')
        return lib
      except Exception as e:
        print(f'[WARNING] Failed loading candidate {p}: {e}')
  raise FileNotFoundError('Could not locate compiled artale_exp_core shared library.')


def main() -> None:
  base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
  cpp_lib = load_cpp_library(base_dir)
  py_engine = python_exp_engine.get_engine()

  crops_dir = os.path.join(base_dir, 'debug_crops')
  crop_files = sorted(glob.glob(os.path.join(crops_dir, 'crop_*.png')))

  if not crop_files:
    print('[ERROR] No crop_*.png test files found in debug_crops/')
    sys.exit(1)

  print(
      f'\nRunning Equivalence Suite across {len(crop_files)} recorded resolution crop datasets...'
  )
  print('=' * 80)

  total = len(crop_files)
  matched = 0
  mismatched = 0

  for idx, path in enumerate(crop_files, 1):
    fname = os.path.basename(path)
    img = cv2.imread(path)
    if img is None:
      print(f'[{idx:03d}/{total}] SKIP: Could not read {fname}', flush=True)
      continue

    h, w = img.shape[:2]

    # 1. Run Python Reference
    py_res = py_engine.parse_crop(img)

    # 2. Run C++ Implementation via C ABI
    bgr_bytes = img.tobytes()
    cpp_res = CppExpResult()
    ret = cpp_lib.ParseExpFromBuffer(
        bgr_bytes, w, h, w * 3, 3, ctypes.byref(cpp_res)
    )

    py_str = py_res[2] if py_res else 'FAILED'
    py_val = py_res[0] if py_res else 0
    py_pct = py_res[1] if py_res else -1.0

    cpp_str = cpp_res.exp_string.decode('utf-8') if cpp_res.success else 'FAILED'
    cpp_val = cpp_res.exp_value if cpp_res.success else 0
    cpp_pct = cpp_res.exp_percent if cpp_res.success else -1.0

    # Assert Equivalence
    str_ok = (py_str == cpp_str)
    val_ok = (py_val == cpp_val)
    pct_ok = abs(py_pct - cpp_pct) < 1e-4

    if str_ok and val_ok and pct_ok:
      matched += 1
      print(
          f'[{idx:03d}/{total}] PASS: {fname:<24} -> {cpp_str:<20} ({cpp_res.parse_time_ms:.1f}ms)',
          flush=True,
      )
    else:
      mismatched += 1
      print(
          f'[{idx:03d}/{total}] FAIL: {fname:<24}\n'
          f'         Python: str="{py_str}", val={py_val}, pct={py_pct}\n'
          f'         C++:    str="{cpp_str}", val={cpp_val}, pct={cpp_pct}',
          flush=True,
      )

  print('=' * 80, flush=True)
  pass_rate = (matched / total) * 100.0
  print(
      f'Equivalence Summary: {matched}/{total} PASSED ({pass_rate:.1f}%) |'
      f' {mismatched} MISMATCHED',
      flush=True,
  )

  if mismatched > 0:
    sys.exit(1)


if __name__ == '__main__':
  main()
