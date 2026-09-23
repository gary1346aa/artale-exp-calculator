"""High-performance Artale EXP Core interface.

Loads the compiled native C++ SIMD engine (artale_exp_core.dll / libartale_exp.dylib)
with AVX2 / NEON vectorization, with an automatic fallback to Python NumPy/OpenCV.
"""

import ctypes
import os
import sys
import numpy as np
import cv2

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
        os.path.join(base_dir, "artale_exp_core.so"),
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

    # Fallback to python live_tracker
    import live_tracker
    py_res = live_tracker.parse_exp(bgr_img)
    if py_res:
        return ParsedFrame(py_res[0], py_res[1], py_res[2], 0.0, (0, 0, 0, 0), (0, 0, 0, 0))
    return None


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

    # 2. Save annotated bottom strip with colored bounding boxes
    strip_file = os.path.join(output_dir, f"annotated_strip_{w}x{h}.png")
    strip_h = max(80, int(h * 0.15))
    strip_y = h - strip_h
    annotated = bgr_img[strip_y:, :].copy()

    # Red box for Logo
    rel_ly = ly - strip_y
    cv2.rectangle(annotated, (lx, rel_ly), (lx + lw, rel_ly + lh), (0, 0, 255), 2)
    cv2.putText(annotated, "EXP Logo", (lx, max(12, rel_ly - 4)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 255), 1)

    # Green box for Text Crop
    rel_cy = cy - strip_y
    cv2.rectangle(annotated, (cx, rel_cy), (cx + cw, rel_cy + ch), (0, 255, 0), 2)
    cv2.putText(annotated, f"Text Box: {parsed.raw_string}", (cx, max(12, rel_cy - 4)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)

    cv2.imwrite(strip_file, annotated)
    print(f"\n[CROP SAVED] Resolution {w}x{h} -> Saved Bounding Box Inspection:")
    print(f"  - Text Crop:       {crop_file}")
    print(f"  - Annotated Strip: {strip_file}\n", flush=True)

    return crop_file, strip_file
