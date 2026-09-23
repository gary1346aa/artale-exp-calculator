"""High-performance Artale EXP Core interface.

Loads the compiled native C++ SIMD engine (artale_exp_core.dll / libartale_exp.dylib)
with AVX2 / NEON vectorization, with an automatic fallback to Python NumPy/OpenCV.
"""

import ctypes
import os
import sys
import numpy as np

class ExpResult(ctypes.Structure):
    _fields_ = [
        ("exp_value", ctypes.c_int64),
        ("exp_percent", ctypes.c_double),
        ("success", ctypes.c_int),
        ("parse_time_ms", ctypes.c_float),
        ("exp_string", ctypes.c_char * 64),
    ]

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

# Fallback Python parser if C++ DLL is unavailable
def _fallback_parse(bgr_img):
    import live_tracker
    return live_tracker.parse_exp(bgr_img)

def parse_frame(bgr_img):
    """Parses EXP and percentage from an uncompressed BGR/BGRA numpy image buffer.

    Returns:
        (exp_val, pct_val, raw_str, latency_ms) or None
    """
    if bgr_img is None:
        return None

    h, w = bgr_img.shape[:2]
    c = bgr_img.shape[2] if len(bgr_img.shape) > 2 else 1
    stride = w * c

    if _use_cpp and _core_dll is not None:
        res = ExpResult()
        # Ensure contiguous buffer
        buf = np.ascontiguousarray(bgr_img)
        ret = _core_dll.ParseExpFromBuffer(
            buf.ctypes.data_as(ctypes.c_char_p),
            w, h, stride, c,
            ctypes.byref(res)
        )
        if ret == 0 and res.success:
            raw_str = res.exp_string.decode("utf-8", errors="ignore")
            pct_val = res.exp_percent if res.exp_percent >= 0 else None
            return res.exp_value, pct_val, raw_str, res.parse_time_ms
        return None

    return _fallback_parse(bgr_img)
