"""Native C++ SIMD engine binding and frame recognition interface.

Complies with the Google Python Style Guide.
Zero top-level OpenCV imports to enable clean production bundling.
"""

import ctypes
import os
import sys
import time
from typing import Optional, Tuple
import numpy as np

import config

class ExpResult(ctypes.Structure):
  """C-compatible struct matching the native artale_exp_core export."""
  _fields_ = [
      ("exp_value", ctypes.c_int64),
      ("exp_percent", ctypes.c_double),
      ("success", ctypes.c_int),
      ("parse_time_ms", ctypes.c_float),
      ("exp_string", ctypes.c_char * 64),
      ("crop_x", ctypes.c_int),
      ("crop_y", ctypes.c_int),
      ("crop_w", ctypes.c_int),
      ("crop_h", ctypes.c_int),
      ("logo_x", ctypes.c_int),
      ("logo_y", ctypes.c_int),
      ("logo_w", ctypes.c_int),
      ("logo_h", ctypes.c_int),
  ]


class ParsedFrame:
  """Container holding parsed EXP, latency, and absolute bounding box coordinates."""

  __slots__ = (
      "exp_value",
      "exp_percent",
      "raw_string",
      "latency_ms",
      "crop_box",
      "logo_box",
  )

  def __init__(
      self,
      exp_val: int,
      pct_val: Optional[float],
      raw_str: str,
      latency_ms: float,
      crop_box: Tuple[int, int, int, int],
      logo_box: Tuple[int, int, int, int],
  ):
    self.exp_value = exp_val
    self.exp_percent = pct_val
    self.raw_string = raw_str
    self.latency_ms = latency_ms
    self.crop_box = crop_box
    self.logo_box = logo_box

  def __iter__(self):
    return iter((
        self.exp_value,
        self.exp_percent,
        self.raw_string,
        self.latency_ms,
    ))

  def __getitem__(self, idx: int):
    return (
        self.exp_value,
        self.exp_percent,
        self.raw_string,
        self.latency_ms,
        self.crop_box,
        self.logo_box,
    )[idx]

  def __len__(self) -> int:
    return 6

  def __repr__(self) -> str:
    return (
        f"ParsedFrame(exp={self.exp_value:,d}, pct={self.exp_percent}%, "
        f"str='{self.raw_string}', latency={self.latency_ms:.1f}ms, "
        f"crop={self.crop_box})"
    )


_core_dll: Optional[ctypes.CDLL] = None
_use_cpp: bool = False


def _init_core() -> None:
  """Locates and loads the compiled native C++ SIMD dynamic library."""
  global _core_dll, _use_cpp
  meipass = getattr(sys, "_MEIPASS", None)
  candidates = []
  if meipass:
    candidates.extend([
        os.path.join(meipass, "artale_exp_core.dll"),
        os.path.join(meipass, "libartale_exp_core.dylib"),
        os.path.join(meipass, "libartale_exp_core.so"),
    ])
  candidates.extend([
      os.path.join(config.BASE_DIR, "bazel-bin", "src", "cpp", "libartale_exp_core_dll.so"),
      os.path.join(config.BASE_DIR, "bazel-bin", "src", "cpp", "artale_exp_core.dll"),
      os.path.join(config.BASE_DIR, "bazel-bin", "src", "cpp", "libartale_exp_core.dylib"),
      os.path.join(config.BASE_DIR, "artale_exp_core.dll"),
      os.path.join(config.BASE_DIR, "build", "artale_exp_core.dll"),
      os.path.join(config.BASE_DIR, "libartale_exp_core.dylib"),
      os.path.join(config.BASE_DIR, "artale_exp_core.dylib"),
      os.path.join(config.BASE_DIR, "build", "libartale_exp_core.dylib"),
      os.path.join(config.BASE_DIR, "build", "artale_exp_core.dylib"),
      os.path.join(config.BASE_DIR, "artale_exp_core.so"),
      os.path.join(config.BASE_DIR, "libartale_exp_core.so"),
      os.path.join(config.BASE_DIR, "build", "libartale_exp_core.so"),
  ])
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
            ctypes.POINTER(ExpResult),
        ]
        lib.ParseExpFromBuffer.restype = ctypes.c_int
        _core_dll = lib
        _use_cpp = True
        if config.IS_DEV:
          print(f"[CORE] Loaded native C++ SIMD engine from: {os.path.basename(p)}")
        return
      except Exception as e:
        if config.IS_DEV:
          print(f"[CORE WARNING] Failed to load {p}: {e}")


_init_core()

# Allow runtime opt-out via USE_CPP=0
_USE_CPP_OVERRIDE = os.environ.get("USE_CPP", "1") == "1"
_use_cpp = _USE_CPP_OVERRIDE and (_core_dll is not None)

_cached_logo_loc = None
_cached_logo_scale = 1.0
_tpl_exp = None
_last_frame_shape = None
_cached_crop_box = None
_cached_logo_box = None


def _get_exp_tpl():
  """Lazy loads the EXP logo template using OpenCV if in fallback mode."""
  global _tpl_exp
  if _tpl_exp is None:
    try:
      import cv2
      tpl_path = config.get_resource_path(os.path.join("data", "real_exp_logo.png"))
      _tpl_exp = cv2.imread(tpl_path, cv2.IMREAD_GRAYSCALE)
    except ImportError:
      _tpl_exp = None
  return _tpl_exp


def _parse_frame_python(bgr_img: np.ndarray) -> Optional[ParsedFrame]:
  """Fallback Python parser using OpenCV/NumPy when C++ engine is unavailable."""
  global _cached_logo_loc, _cached_logo_scale, _last_frame_shape, _cached_crop_box, _cached_logo_box
  try:
    import cv2
    from core import python_engine
  except ImportError:
    return None

  engine = python_engine.get_engine()
  tpl = _get_exp_tpl()
  if tpl is None or bgr_img is None:
    return None

  t0 = time.perf_counter()
  h, w = bgr_img.shape[:2]
  cur_shape = (h, w)

  if _last_frame_shape != cur_shape:
    _last_frame_shape = cur_shape
    _cached_logo_loc = None
    _cached_crop_box = None
    _cached_logo_box = None

  if _cached_crop_box is not None:
    cx, cy, cw, ch = _cached_crop_box
    if cy + ch <= h and cx + cw <= w:
      crop_bgr = bgr_img[cy : cy + ch, cx : cx + cw]
      parsed = engine.parse_crop(crop_bgr)
      if parsed:
        exp_val, pct_val, raw_str, _crop_dt, _ = parsed
        dt_ms = (time.perf_counter() - t0) * 1000.0
        return ParsedFrame(exp_val, pct_val, raw_str, dt_ms, _cached_crop_box, _cached_logo_box)

  strip_h = min(h, max(80, int(h * 0.15)))
  strip_y = max(0, h - strip_h)
  strip_bgr = bgr_img[strip_y:, :]
  strip_gray = cv2.cvtColor(strip_bgr, cv2.COLOR_BGR2GRAY)

  found = False
  best_lx, best_ly, best_tw, best_th, best_v = 0, 0, 0, 0, -1.0

  if _cached_logo_loc is not None:
    cly, clx = _cached_logo_loc
    s = _cached_logo_scale
    scaled = cv2.resize(tpl, (0, 0), fx=s, fy=s, interpolation=cv2.INTER_LINEAR)
    th, tw = scaled.shape
    win_y1 = max(0, cly - 10)
    win_y2 = min(strip_h, cly + th + 10)
    win_x1 = max(0, clx - 15)
    win_x2 = min(w, clx + tw + 15)
    if win_y2 > win_y1 + th and win_x2 > win_x1 + tw:
      res = cv2.matchTemplate(
          strip_gray[win_y1:win_y2, win_x1:win_x2], scaled, cv2.TM_CCOEFF_NORMED
      )
      v = float(np.max(res))
      if v > 0.65:
        min_v, max_v, min_l, max_l = cv2.minMaxLoc(res)
        best_lx = win_x1 + max_l[0]
        best_ly = win_y1 + max_l[1]
        best_tw = tw
        best_th = th
        best_v = v
        found = True

  if not found:
    s_center = min(w / 3840.0, h / 2160.0)
    s_min = max(0.24, s_center * 0.65)
    s_max = min(1.45, s_center * 1.35)
    scales = np.linspace(s_min, s_max, 16)

    for s in scales:
      scaled = cv2.resize(tpl, (0, 0), fx=s, fy=s, interpolation=cv2.INTER_LINEAR)
      th, tw = scaled.shape
      if th >= strip_h or tw >= w:
        continue
      res = cv2.matchTemplate(strip_gray, scaled, cv2.TM_CCOEFF_NORMED)
      v = float(np.max(res))
      if v > best_v:
        min_v, max_v, min_l, max_l = cv2.minMaxLoc(res)
        best_v = v
        best_lx = max_l[0]
        best_ly = max_l[1]
        best_tw = tw
        best_th = th
        _cached_logo_scale = s

    if best_v > 0.65:
      _cached_logo_loc = (best_lx, best_ly)
      found = True

  if not found:
    return None

  crop_x = best_lx + best_tw
  crop_y = strip_y + best_ly
  crop_w = int(best_th * 9.5)
  crop_h = best_th

  if crop_x + crop_w > w:
    crop_w = w - crop_x
  if crop_y + crop_h > h:
    crop_h = h - crop_y

  if crop_w <= 10 or crop_h <= 10:
    return None

  crop_bgr = bgr_img[crop_y : crop_y + crop_h, crop_x : crop_x + crop_w]
  parsed = engine.parse_crop(crop_bgr)
  if not parsed:
    return None

  exp_val, pct_val, raw_str, _crop_dt, _ = parsed
  dt_ms = (time.perf_counter() - t0) * 1000.0
  crop_box = (crop_x, crop_y, crop_w, crop_h)
  logo_box = (best_lx, strip_y + best_ly, best_tw, best_th)
  _cached_crop_box = crop_box
  _cached_logo_box = logo_box
  return ParsedFrame(exp_val, pct_val, raw_str, dt_ms, crop_box, logo_box)


def parse_frame(bgr_img: Optional[np.ndarray]) -> Optional[ParsedFrame]:
  """Parses EXP value, percentage, and bounding boxes from a BGR/BGRA frame.

  Dispatches directly to the high-performance native C++ SIMD engine when
  available. Falls back gracefully to the Python reference engine if the C++
  shared library is missing.

  Args:
    bgr_img: Contiguous numpy array containing BGR or BGRA pixel bytes.

  Returns:
    ParsedFrame containing the recognition results, or None if no valid EXP
    reading was detected.
  """
  if bgr_img is None:
    return None

  h, w = bgr_img.shape[:2]
  c = bgr_img.shape[2] if len(bgr_img.shape) > 2 else 1
  stride = w * c

  if _use_cpp and _core_dll is not None:
    res = ExpResult()
    buf = np.ascontiguousarray(bgr_img)
    ret = _core_dll.ParseExpFromBuffer(
        buf.ctypes.data_as(ctypes.c_char_p),
        w,
        h,
        stride,
        c,
        ctypes.byref(res),
    )
    if ret == 0 and res.success:
      raw_str = res.exp_string.decode("utf-8", errors="ignore")
      pct_val = res.exp_percent if res.exp_percent >= 0 else None
      crop_box = (res.crop_x, res.crop_y, res.crop_w, res.crop_h)
      logo_box = (res.logo_x, res.logo_y, res.logo_w, res.logo_h)
      return ParsedFrame(
          res.exp_value, pct_val, raw_str, res.parse_time_ms, crop_box, logo_box
      )
    return None

  return _parse_frame_python(bgr_img)


def is_cpp_active() -> bool:
  """Returns True if the high-speed C++ SIMD engine is loaded and active."""
  return _use_cpp and (_core_dll is not None)


# Backward compatibility alias
parse_frame_buffer = parse_frame

