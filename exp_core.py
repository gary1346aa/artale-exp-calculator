"""Artale EXP Core interface.

Loads the compiled native C++ SIMD engine (artale_exp_core.dll / libartale_exp.dylib)
with AVX2 / NEON vectorization, with an automatic fallback to Python NumPy/OpenCV.
"""

import ctypes
import os
import sys
import numpy as np
import cv2
import time

class ExpResult(ctypes.Structure):
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
    """Rich container holding parsed EXP, latency, and absolute bounding box coordinates."""
    __slots__ = ("exp_value", "exp_percent", "raw_string", "latency_ms", "crop_box", "logo_box")

    def __init__(self, exp_val: int, pct_val: float, raw_str: str, latency_ms: float,
                 crop_box: tuple, logo_box: tuple):
        self.exp_value = exp_val
        self.exp_percent = pct_val
        self.raw_string = raw_str
        self.latency_ms = latency_ms
        self.crop_box = crop_box      # (crop_x, crop_y, crop_w, crop_h)
        self.logo_box = logo_box      # (logo_x, logo_y, logo_w, logo_h)

    def __iter__(self):
        return iter((self.exp_value, self.exp_percent, self.raw_string, self.latency_ms))

    def __getitem__(self, idx):
        return (self.exp_value, self.exp_percent, self.raw_string, self.latency_ms, self.crop_box, self.logo_box)[idx]

    def __len__(self):
        return 6

    def __repr__(self):
        return (f"ParsedFrame(exp={self.exp_value:,d}, pct={self.exp_percent}%, "
                f"str='{self.raw_string}', latency={self.latency_ms:.1f}ms, "
                f"crop={self.crop_box})")

_core_dll = None
_use_cpp = False

def _init_core():
    global _core_dll, _use_cpp
    base_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(base_dir, "artale_exp_core.dll"),
        os.path.join(base_dir, "build", "artale_exp_core.dll"),
        os.path.join(base_dir, "libartale_exp_core.dylib"),
        os.path.join(base_dir, "artale_exp_core.dylib"),
        os.path.join(base_dir, "build", "libartale_exp_core.dylib"),
        os.path.join(base_dir, "build", "artale_exp_core.dylib"),
        os.path.join(base_dir, "artale_exp_core.so"),
        os.path.join(base_dir, "libartale_exp_core.so"),
        os.path.join(base_dir, "build", "libartale_exp_core.so"),
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
                    ctypes.POINTER(ExpResult),
                ]
                lib.ParseExpFromBuffer.restype = ctypes.c_int
                _core_dll = lib
                _use_cpp = True
                print(f"[CORE] Loaded native C++ SIMD engine from: {os.path.basename(p)}")
                return
            except Exception as e:
                print(f"[CORE WARNING] Failed to load {p}: {e}")

_init_core()

# Default to C++ engine when available, allowing opt-out via USE_CPP=0
_USE_CPP_OVERRIDE = os.environ.get("USE_CPP", "1") == "1"
_use_cpp = _USE_CPP_OVERRIDE and (_core_dll is not None)

_cached_logo_loc = None
_cached_logo_scale = 1.0
_tpl_exp = None

def _get_exp_tpl():
    global _tpl_exp
    if _tpl_exp is None:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        tpl_path = os.path.join(base_dir, "data", "real_exp_logo.png")
        _tpl_exp = cv2.imread(tpl_path, cv2.IMREAD_GRAYSCALE)
    return _tpl_exp

_last_frame_shape = None
_cached_crop_box = None
_cached_logo_box = None

def _parse_frame_python(bgr_img) -> ParsedFrame | None:
    global _cached_logo_loc, _cached_logo_scale, _last_frame_shape, _cached_crop_box, _cached_logo_box
    import python_exp_engine
    engine = python_exp_engine.get_engine()
    tpl = _get_exp_tpl()
    if tpl is None or bgr_img is None:
        return None

    t0 = time.perf_counter()
    h, w = bgr_img.shape[:2]
    cur_shape = (h, w)

    # Invalidate cache if resolution changed
    if _last_frame_shape != cur_shape:
        _last_frame_shape = cur_shape
        _cached_logo_loc = None
        _cached_crop_box = None
        _cached_logo_box = None

    # Cached path: If resolution has not changed and bounding box is cached, reuse it.
    if _cached_crop_box is not None:
        cx, cy, cw, ch = _cached_crop_box
        if cy + ch <= h and cx + cw <= w:
            crop_bgr = bgr_img[cy:cy + ch, cx:cx + cw]
            parsed = engine.parse_crop(crop_bgr)
            if parsed:
                exp_val, pct_val, raw_str, _crop_dt, _ = parsed
                dt_ms = (time.perf_counter() - t0) * 1000.0
                return ParsedFrame(exp_val, pct_val, raw_str, dt_ms, _cached_crop_box, _cached_logo_box)
            # If parsing failed on cached box (e.g. obscured/moved), clear and re-detect
            _cached_crop_box = None
            _cached_logo_box = None

    strip_h = min(h, max(80, int(h * 0.15)))
    strip_y = max(0, h - strip_h)
    strip_bgr = bgr_img[strip_y:, :]
    strip_gray = cv2.cvtColor(strip_bgr, cv2.COLOR_BGR2GRAY)

    found = False
    best_lx, best_ly = 0, 0
    best_tw, best_th = 0, 0

    # 1. Fast path: check cached location if available
    if _cached_logo_loc is not None:
        clx, cly = _cached_logo_loc
        s = _cached_logo_scale
        scaled = cv2.resize(tpl, (0, 0), fx=s, fy=s, interpolation=cv2.INTER_LINEAR)
        th, tw = scaled.shape
        win_y1 = max(0, cly - 10)
        win_y2 = min(strip_h, cly + th + 10)
        win_x1 = max(0, clx - 10)
        win_x2 = min(w, clx + tw + 10)
        if win_y2 > win_y1 + th and win_x2 > win_x1 + tw:
            res = cv2.matchTemplate(strip_gray[win_y1:win_y2, win_x1:win_x2], scaled, cv2.TM_CCOEFF_NORMED)
            v = float(np.max(res))
            if v > 0.65:
                dy, dx = np.unravel_index(np.argmax(res), res.shape)
                best_lx = win_x1 + dx
                best_ly = win_y1 + dy
                best_tw = tw
                best_th = th
                _cached_logo_loc = (best_lx, best_ly)
                found = True

    # 2. Slow path: multi-scale search guided by window resolution
    if not found:
        best_v = -1.0
        # Expected UI scale follows the smaller window dimension (aspect-ratio aware)
        s_center = min(w / 3840.0, h / 2160.0)
        scales = np.linspace(max(0.24, s_center * 0.65), min(1.45, s_center * 1.35), 16)
        for s in scales:
            scaled = cv2.resize(tpl, (0, 0), fx=s, fy=s, interpolation=cv2.INTER_LINEAR)
            th, tw = scaled.shape
            if th >= strip_h or tw >= w:
                continue
            res = cv2.matchTemplate(strip_gray, scaled, cv2.TM_CCOEFF_NORMED)
            v = float(np.max(res))
            if v > best_v:
                best_v = v
                dy, dx = np.unravel_index(np.argmax(res), res.shape)
                best_lx = dx
                best_ly = dy
                best_tw = tw
                best_th = th
                _cached_logo_scale = s

        if best_v > 0.65:
            _cached_logo_loc = (best_lx, best_ly)
            found = True

    if not found:
        return None

    # Text region bounding box
    crop_x = best_lx + best_tw
    crop_y = strip_y + best_ly
    crop_w = int(best_th * 9.5)
    crop_h = best_th

    # Clamp bounds
    if crop_x + crop_w > w:
        crop_w = w - crop_x
    if crop_y + crop_h > h:
        crop_h = h - crop_y

    if crop_w <= 10 or crop_h <= 10:
        return None

    crop_bgr = bgr_img[crop_y:crop_y + crop_h, crop_x:crop_x + crop_w]
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

def parse_frame(bgr_img) -> ParsedFrame | None:
    """Parses EXP, percentage, and bounding box from an uncompressed BGR/BGRA numpy image buffer.

    Returns:
        ParsedFrame or None
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
            w, h, stride, c,
            ctypes.byref(res)
        )
        if ret == 0 and res.success:
            raw_str = res.exp_string.decode("utf-8", errors="ignore")
            pct_val = res.exp_percent if res.exp_percent >= 0 else None
            crop_box = (res.crop_x, res.crop_y, res.crop_w, res.crop_h)
            logo_box = (res.logo_x, res.logo_y, res.logo_w, res.logo_h)
            return ParsedFrame(res.exp_value, pct_val, raw_str, res.parse_time_ms, crop_box, logo_box)
        return None

    # Python engine with pristine prototypes
    return _parse_frame_python(bgr_img)


def save_crop_debug(bgr_img, parsed: ParsedFrame, output_dir: str = "debug_crops"):
    """Saves the exact cropped text box and annotated strip whenever resolution changes."""
    if bgr_img is None or parsed is None:
        return None

    os.makedirs(output_dir, exist_ok=True)
    h, w = bgr_img.shape[:2]
    cx, cy, cw, ch = parsed.crop_box
    lx, ly, lw, lh = parsed.logo_box

    # 1. Save exact text bounding box crop
    crop_file = os.path.join(output_dir, f"crop_{w}x{h}.png")
    if cw > 0 and ch > 0 and cy + ch <= h and cx + cw <= w:
        crop_img = bgr_img[cy:cy + ch, cx:cx + cw]
        cv2.imwrite(crop_file, crop_img)

    # 2. Save raw untouched bottom strip (no drawings)
    raw_strip_file = os.path.join(output_dir, f"raw_strip_{w}x{h}.png")
    strip_h = min(h, max(80, int(h * 0.15)))
    strip_y = max(0, h - strip_h)
    raw_strip = bgr_img[strip_y:strip_y + strip_h, :].copy()
    cv2.imwrite(raw_strip_file, raw_strip)

    # 3. Save raw untouched logo crop (no drawings)
    raw_logo_file = os.path.join(output_dir, f"raw_logo_{w}x{h}.png")
    if lw > 0 and lh > 0 and ly + lh <= h and lx + lw <= w:
        cv2.imwrite(raw_logo_file, bgr_img[ly:ly + lh, lx:lx + lw])

    # 4. Save annotated bottom strip with colored bounding boxes
    strip_file = os.path.join(output_dir, f"annotated_strip_{w}x{h}.png")
    annotated = raw_strip.copy()

    # Red box for Logo (1px hairline border so details are visible)
    rel_ly = ly - strip_y
    cv2.rectangle(annotated, (lx, rel_ly), (lx + lw, rel_ly + lh), (0, 0, 255), 1)
    cv2.putText(annotated, "EXP Logo", (lx, max(10, rel_ly - 3)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 0, 255), 1)

    # Green box for Text Crop (1px hairline border so details are visible)
    rel_cy = cy - strip_y
    cv2.rectangle(annotated, (cx, rel_cy), (cx + cw, rel_cy + ch), (0, 255, 0), 1)
    cv2.putText(annotated, f"Text: {parsed.raw_string}", (cx, max(10, rel_cy - 3)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 255, 0), 1)

    cv2.imwrite(strip_file, annotated)
    print(f"\n[CROP SAVED] Resolution {w}x{h} -> Saved Bounding Box Inspection:")
    print(f"  - Raw Undrawn Strip: {raw_strip_file}")
    print(f"  - Raw Logo Crop:     {raw_logo_file}")
    print(f"  - Text Crop:         {crop_file}")
    print(f"  - Annotated Strip:   {strip_file}\n", flush=True)

    return crop_file, strip_file
