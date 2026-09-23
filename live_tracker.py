"""Live Artale Desktop EXP Tracker via Windows Graphics Capture (WGC).

Samples at 1 FPS (zero CPU overhead), captures un-occluded DirectX swapchain
frames directly from DWM, and adapts dynamically to live window resizing.
Accommodates up to 10-digit EXP numbers and 2+2 percentage (e.g. 1234567890[99.99%]).
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

# Load font prototypes
with open(PROTOS_PATH, "r", encoding="utf-8") as f:
    raw = json.load(f)
protos = {k: np.array(v["bitmap"], dtype=np.uint8) for k, v in raw.items()}
tpl_exp = cv2.imread(TPL_EXP_PATH, cv2.IMREAD_GRAYSCALE)

last_res = None
last_sample_time = 0.0
sample_interval = 1.0  # 1 FPS

def parse_exp(bgr_img):
    h, w, _ = bgr_img.shape
    bottom = bgr_img[-120:, :]
    gray = cv2.cvtColor(bottom, cv2.COLOR_BGR2GRAY)
    
    # Multi-scale EXP. logo template match across dynamic window scales
    best_val = -1
    best_loc = None
    best_tw, best_th = 0, 0
    scale_base = h / 1000.0
    scales = np.linspace(max(0.6, scale_base * 0.7), min(2.0, scale_base * 1.4), 11)
    for s in scales:
        th, tw = int(tpl_exp.shape[0] * s), int(tpl_exp.shape[1] * s)
        if th >= bottom.shape[0] or tw >= bottom.shape[1]:
            continue
        t_scaled = cv2.resize(tpl_exp, (tw, th), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)
        res = cv2.matchTemplate(gray, t_scaled, cv2.TM_CCOEFF_NORMED)
        min_v, max_v, min_l, max_l = cv2.minMaxLoc(res)
        if max_v > best_val:
            best_val = max_v
            best_loc = max_l
            best_tw, best_th = tw, th
            
    if best_val < 0.70:
        return None
        
    lx, ly = best_loc
    # Text region after EXP. logo:
    # Width accommodates at least 10 digits EXP + [99.99%] (approx 20 chars, up to ~500px)
    text_w = min(int(best_th * 30), bottom.shape[1] - (lx + best_tw + 4))
    y_start = max(0, ly - 6)
    y_end = min(bottom.shape[0], ly + best_th + 1)
    text_crop = bottom[y_start:y_end, lx + best_tw + 4 : lx + best_tw + 4 + text_w]
    tc_gray = cv2.cvtColor(text_crop, cv2.COLOR_BGR2GRAY)
    mask = (tc_gray > 175).astype(np.uint8)
    
    # Connected components segmentation
    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
    glyphs = []
    for i in range(1, num_labels):
        gx, gy, gw, gh, garea = stats[i]
        if gh < 3 or garea < 2 or gw > 40:
            continue
        glyphs.append((gx, gy, gw, gh, mask[gy:gy+gh, gx:gx+gw]))
        
    glyphs.sort(key=lambda g: g[0])
    
    chars = []
    found_open_bracket = False
    for gx, gy, gw, gh, crop in glyphs:
        if gw <= 4 and gh <= 4:
            chars.append(".")
            continue
        best_iou = -1
        best_ch = "?"
        for ch, proto in protos.items():
            if ch == ".":
                continue
            p_res = cv2.resize(proto, (gw, gh), interpolation=cv2.INTER_NEAREST)
            inter = np.sum((crop > 0) & (p_res > 0))
            union = np.sum((crop > 0) | (p_res > 0))
            iou = inter / union if union > 0 else 0
            if iou > best_iou:
                best_iou = iou
                best_ch = ch
                
        if best_ch == "[":
            found_open_bracket = True
        elif best_ch == "]" and found_open_bracket:
            chars.append("]")
            break
        chars.append(best_ch)
        
    raw_str = "".join(chars)
    # Parse up to 10-digit EXP and percent (e.g. 1234567890[99.99%])
    m = re.search(r"(\d+)\[(\d+\.?\d*)", raw_str)
    if m:
        exp_val = int(m.group(1))
        pct_val = float(m.group(2))
        return exp_val, pct_val, raw_str
    elif raw_str:
        digits_only = "".join(c for c in raw_str.split("[")[0] if c.isdigit())
        if digits_only:
            return int(digits_only), None, raw_str
            
    return None

def main():
    global last_res, last_sample_time
    print("=" * 80, flush=True)
    print("  Artale WGC EXP Tracker [1 FPS Mode]", flush=True)
    print("=" * 80, flush=True)
    print("Sampling Rate : 1.0 frame / sec", flush=True)
    print("Target Window : 'MapleStory Worlds-Artale'", flush=True)
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
