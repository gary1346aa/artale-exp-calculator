"""Live Artale Desktop EXP Tracker via Windows Graphics Capture (WGC).

Samples at 1 FPS (zero CPU overhead), captures un-occluded DirectX swapchain
frames directly from DWM, and adapts dynamically to live window resizing across
all resolutions (from 720p to 4K).
"""

import ctypes
import os
import sys
import time
import re
from datetime import datetime

# Configure UTF-8 stdout
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Ensure desktop access
user32 = ctypes.windll.user32
h_desk = user32.OpenDesktopW("Default", 0, False, 0x01FF)
if h_desk:
    user32.SetThreadDesktop(h_desk)

import cv2
import json
import numpy as np
from windows_capture import WindowsCapture, Frame

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROTOS_PATH = os.path.join(BASE_DIR, "data", "desktop_font_protos.json")
TPL_EXP_PATH = os.path.join(BASE_DIR, "data", "real_exp_logo.png")

# Load font prototypes and normalize to canonical 16x24
with open(PROTOS_PATH, "r", encoding="utf-8") as f:
    raw = json.load(f)
protos = {k: np.array(v["bitmap"], dtype=np.uint8) for k, v in raw.items()}
tpl_exp = cv2.imread(TPL_EXP_PATH, cv2.IMREAD_GRAYSCALE)

CANON_W, CANON_H = 16, 24
proto_ncc = {}
for ch, p in protos.items():
    p_res = cv2.resize(p.astype(np.float32), (CANON_W, CANON_H), interpolation=cv2.INTER_LINEAR)
    p_zm = p_res - np.mean(p_res)
    p_norm = np.linalg.norm(p_zm)
    proto_ncc[ch] = (p_zm, p_norm)

last_res = None
last_sample_time = 0.0
sample_interval = 1.0  # 1 FPS

def match_glyph_ncc(crop_binary, candidates):
    """Computes Normalized Cross Correlation (NCC) against candidate prototypes."""
    c_res = cv2.resize(crop_binary.astype(np.float32), (CANON_W, CANON_H), interpolation=cv2.INTER_LINEAR)
    c_zm = c_res - np.mean(c_res)
    c_norm = np.linalg.norm(c_zm)
    if c_norm == 0:
        return "?", 0.0
    best_c, best_s = "?", -1.0
    for ch in candidates:
        if ch not in proto_ncc:
            continue
        p_zm, p_norm = proto_ncc[ch]
        ncc = np.sum(c_zm * p_zm) / (c_norm * p_norm)
        if ncc > best_s:
            best_s = ncc
            best_c = ch
    return best_c, best_s

def parse_exp(frame_bgr):
    h, w, _ = frame_bgr.shape
    # Dynamic bottom strip proportional to window height (covers 720p to 4K)
    strip_h = max(100, int(h * 0.15))
    bottom = frame_bgr[-strip_h:, :]
    gray = cv2.cvtColor(bottom, cv2.COLOR_BGR2GRAY)
    
    # Dynamic multi-scale search range based on resolution
    scale_est = h / 960.0
    scales = np.linspace(max(0.40, scale_est * 0.65), min(3.80, scale_est * 1.45), 23)
    
    best_val = -1.0
    best_loc = None
    best_tw, best_th = 0, 0
    for s in scales:
        th, tw = int(tpl_exp.shape[0] * s), int(tpl_exp.shape[1] * s)
        if th >= bottom.shape[0] or tw >= bottom.shape[1] or th < 5:
            continue
        t_scaled = cv2.resize(tpl_exp, (tw, th), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)
        res = cv2.matchTemplate(gray, t_scaled, cv2.TM_CCOEFF_NORMED)
        min_v, max_v, min_l, max_l = cv2.minMaxLoc(res)
        if max_v > best_val:
            best_val = max_v
            best_loc = max_l
            best_tw, best_th = tw, th
            
    if best_val < 0.65:
        return None
        
    lx, ly = best_loc
    # Text line vertical slice (proportional to logo height th)
    y_start = max(0, ly - int(best_th * 0.35))
    y_end = min(bottom.shape[0], ly + int(best_th * 1.50))
    # Offset by 0.45*th to cleanly skip the dot of 'EXP.'
    x_start = lx + best_tw + int(best_th * 0.45)
    x_end = min(bottom.shape[1], x_start + int(best_th * 32))
    
    tc = bottom[y_start:y_end, x_start:x_end]
    # Optimal threshold for anti-aliased font on dark game background
    mask = (cv2.cvtColor(tc, cv2.COLOR_BGR2GRAY) > 130).astype(np.uint8)
    
    # Strip bottom gauge line: find first zero gap in the digits zone
    sub_sums = np.sum(mask[:, :int(best_th * 10)], axis=1)
    text_y2 = len(sub_sums)
    for y in range(len(sub_sums)):
        if sub_sums[y] == 0 and y > int(best_th * 0.6):
            text_y2 = y
            break
            
    clean_mask = mask[:text_y2, :]
    
    # Horizontal column projection
    col_sums = np.sum(clean_mask, axis=0)
    spans = []
    in_span = False
    start = 0
    for x in range(len(col_sums)):
        if col_sums[x] > 0 and not in_span:
            in_span = True
            start = x
        elif col_sums[x] == 0 and in_span:
            in_span = False
            spans.append((start, x))
    if in_span:
        spans.append((start, len(col_sums)))
        
    exp_digits = []
    pct_chars = []
    in_pct = False

    for idx, (s, e) in enumerate(spans):
        g = clean_mask[:, s:e]
        ry = np.where(np.sum(g, axis=1) > 0)[0]
        rx = np.where(np.sum(g, axis=0) > 0)[0]
        if len(ry) == 0 or len(rx) == 0:
            continue
        g_trim = g[ry[0]:ry[-1]+1, rx[0]:rx[-1]+1]
        gw, gh = g_trim.shape[1], g_trim.shape[0]
        
        # Skip 1px noise slivers
        if gw <= 1 and gh <= 4:
            continue
            
        if not in_pct:
            ch_br, s_br = match_glyph_ncc(g_trim, ["["])
            ch_dig, s_dig = match_glyph_ncc(g_trim, "0123456789")
            # Open bracket '[' only occurs after at least 1 EXP digit
            if len(exp_digits) >= 1 and s_br > 0.50 and s_br > s_dig:
                in_pct = True
                continue
            exp_digits.append(ch_dig)
        else:
            # Inside bracket: check for decimal dot '.'
            if gw <= max(3, int(best_th * 0.35)) and gh <= max(3, int(best_th * 0.35)):
                pct_chars.append(".")
                continue
            ch_cl, s_cl = match_glyph_ncc(g_trim, ["]"])
            ch_other, s_other = match_glyph_ncc(g_trim, "0123456789%")
            if s_cl > 0.45 and s_cl > s_other and len(pct_chars) >= 3:
                pct_chars.append("]")
                break
            pct_chars.append(ch_other)
            if ch_other == "%":
                # Percentage complete!
                pct_chars.append("]")
                break

    exp_str = "".join(exp_digits)
    pct_str = "".join(pct_chars)
    
    m_exp = re.search(r"(\d+)", exp_str)
    m_pct = re.search(r"(\d+\.?\d*)", pct_str)
    
    if m_exp:
        exp_val = int(m_exp.group(1))
        pct_val = float(m_pct.group(1)) if m_pct else None
        return exp_val, pct_val, f"{exp_str}[{pct_str}]"
    return None

def main():
    global last_res, last_sample_time
    print("=" * 80, flush=True)
    print("  Artale WGC EXP Tracker [Robust Multi-Scale 1 FPS Mode]", flush=True)
    print("=" * 80, flush=True)
    print("Sampling Rate : 1.0 frame / sec", flush=True)
    print("Target Window : 'MapleStory Worlds-Artale'", flush=True)
    print("Supported Res : Dynamic 720p ~ 4K+ with subpixel NCC matching", flush=True)
    print("Capacity      : Up to 10 digits EXP + 2+2 % (e.g. 1234567890[99.99%])", flush=True)
    print("Features      : Un-occluded background capture + dynamic resize auto-adaptation", flush=True)
    print("Press Ctrl+C to exit.\n", flush=True)

    capture = WindowsCapture(
        cursor_capture=False,
        draw_border=False,
        window_name="MapleStory Worlds-Artale"
    )

    @capture.event
    def on_frame_arrived(frame: Frame, capture_control):
        global last_res, last_sample_time
        now = time.time()
        # Enforce 1 FPS throttling
        if now - last_sample_time < sample_interval:
            return
        last_sample_time = now
        
        bgr = frame.convert_to_bgr().frame_buffer
        cur_res = (bgr.shape[1], bgr.shape[0])
        now_str = datetime.now().strftime("%H:%M:%S")
        
        if last_res != cur_res:
            print(f"\n[{now_str}] [WINDOW RESIZE] New Resolution: {cur_res[0]}x{cur_res[1]}", flush=True)
            last_res = cur_res
            
        t0 = time.perf_counter()
        parsed = parse_exp(bgr)
        dt_ms = (time.perf_counter() - t0) * 1000.0
        
        if parsed:
            exp_val, pct, raw_str = parsed
            pct_s = f"{pct:.2f}%" if pct is not None else "N/A"
            print(f"[{now_str}] [{cur_res[0]}x{cur_res[1]}] EXP: {exp_val:>12,d} [{pct_s:>6}] | Parse: {dt_ms:4.1f}ms | Status: LOCKED", flush=True)
        else:
            print(f"[{now_str}] [{cur_res[0]}x{cur_res[1]}] Status: Searching for EXP bar... ({dt_ms:4.1f}ms)", flush=True)

    @capture.event
    def on_closed():
        print("\n[INFO] Capture session closed.", flush=True)

    try:
        capture.start()
    except KeyboardInterrupt:
        print("\n[INFO] Stopped by user.", flush=True)

if __name__ == "__main__":
    main()
