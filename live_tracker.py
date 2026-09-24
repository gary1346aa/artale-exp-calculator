"""Live Artale Desktop EXP Tracker via Windows Graphics Capture (WGC).

Samples at 1 FPS, captures un-occluded DirectX swapchain
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

import cv2
import json
import numpy as np
from windows_capture import WindowsCapture, Frame
import exp_core
from metrics_engine import ExpMetricsEngine

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
    # Text line vertical slice (exact same y1 and y2 as EXP logo)
    y_start = max(0, ly)
    y_end = min(bottom.shape[0], ly + best_th)
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
        
    glyphs = []
    for s, e in spans:
        g = clean_mask[:, s:e]
        ry = np.where(np.sum(g, axis=1) > 0)[0]
        rx = np.where(np.sum(g, axis=0) > 0)[0]
        if len(ry) == 0 or len(rx) == 0:
            continue
        gt = g[ry[0]:ry[-1]+1, rx[0]:rx[-1]+1]
        gw, gh = gt.shape[1], gt.shape[0]
        if gw <= 1 and gh <= 3:
            continue
        glyphs.append((gw, gh, gt))

    if not glyphs:
        return None

    first_few_h = [gh for gw, gh, _ in glyphs[:4] if gh > 4]
    base_digit_h = np.median(first_few_h) if first_few_h else best_th * 0.85
    base_digit_w = np.median([gw for gw, gh, _ in glyphs[:4] if gh > 4]) if first_few_h else best_th * 0.6

    exp_digits = []
    pct_chars = []
    in_pct = False

    for gw, gh, gt in glyphs:
        if not in_pct:
            ch_br, s_br = match_glyph_ncc(gt, ["["])
            ch_dig, s_dig = match_glyph_ncc(gt, "0123456789")
            
            is_bracket = False
            if len(exp_digits) >= 1:
                # Open bracket '[' is strictly taller than standard digits (~1.22x) and narrower (~0.5x)
                if gh >= 1.08 * base_digit_h and gw <= 0.80 * base_digit_w:
                    is_bracket = True
                elif s_br > 0.35 and s_br > s_dig:
                    is_bracket = True

            if is_bracket:
                in_pct = True
                continue
            exp_digits.append(ch_dig)
        else:
            # Inside bracket:
            # 1. Decimal dot check (small bounding box)
            if gw <= max(4, int(base_digit_h * 0.35)) and gh <= max(4, int(base_digit_h * 0.35)):
                pct_chars.append(".")
                continue
            # 2. Percentage sign '%' check (wide bounding box)
            ch_pct, s_pct = match_glyph_ncc(gt, ["%"])
            ch_dig, s_dig = match_glyph_ncc(gt, "0123456789")
            if (s_pct > 0.30 and s_pct > s_dig) or gw >= 1.3 * base_digit_w:
                pct_chars.append("%")
                break
            # 3. Closing bracket ']' check or length termination
            if (gh >= 1.08 * base_digit_h and gw <= 0.80 * base_digit_w) or len(pct_chars) >= 4:
                break
            pct_chars.append(ch_dig)

    exp_str = "".join(exp_digits)
    pct_str = "".join(pct_chars).replace("%", "")
    
    if exp_str.isdigit():
        exp_val = int(exp_str)
        try:
            pct_val = float(pct_str)
        except Exception:
            pct_val = None
        pct_display = f"{pct_val:.2f}%" if pct_val is not None else "N/A"
        return exp_val, pct_val, f"{exp_str}[{pct_display}]"
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
    if sys.platform == "win32":
        user32 = ctypes.windll.user32
        h_desk = user32.OpenDesktopW("Default", 0, False, 0x01FF)
        if h_desk:
            user32.SetThreadDesktop(h_desk)

    capture = WindowsCapture(
        cursor_capture=False,
        draw_border=False,
        window_name="MapleStory Worlds-Artale"
    )

    engine = ExpMetricsEngine()

    @capture.event
    def on_frame_arrived(frame: Frame, capture_control):
        global last_res, last_sample_time
        now = time.time()
        now_str = datetime.now().strftime("%H:%M:%S")
        # Enforce 1 FPS throttling
        if now - last_sample_time < sample_interval:
            return
        last_sample_time = now
        
        bgr = frame.convert_to_bgr().frame_buffer
        cur_res = (bgr.shape[1], bgr.shape[0])
        res_changed = (last_res != cur_res)
        if res_changed:
            print(f"\n[{now_str}] [視窗尺寸變更] 當前解析度: {cur_res[0]}x{cur_res[1]}", flush=True)
            last_res = cur_res
            try:
                os.makedirs("debug_crops", exist_ok=True)
                strip_h = min(cur_res[1], max(80, int(cur_res[1] * 0.15)))
                cv2.imwrite(f"debug_crops/raw_strip_{cur_res[0]}x{cur_res[1]}.png", bgr[cur_res[1] - strip_h:, :])
            except Exception:
                pass
            
        parsed = exp_core.parse_frame(bgr)
        
        if parsed:
            if res_changed:
                exp_core.save_crop_debug(bgr, parsed)

            if len(parsed) >= 4:
                exp_val, pct, raw_str, dt_ms = parsed[:4]
            else:
                exp_val, pct, raw_str = parsed
                dt_ms = 0.0
            
            engine.add_sample(exp_val, pct)
            m = engine.get_metrics()
            
            print(
                f"[{now_str}] 經驗: {m['當前經驗']} | "
                f"時長: {m['練功時長']} | "
                f"總獲得: {m['總獲得經驗']} | "
                f"時薪: {m['預估60分']} | "
                f"升級預估: {m['升級預估時間']} | "
                f"延遲: {dt_ms:4.1f}ms",
                flush=True
            )
        else:
            print(f"[{now_str}] [{cur_res[0]}x{cur_res[1]}] 狀態: 搜尋經驗條中...", flush=True)

    @capture.event
    def on_closed():
        print("\n[INFO] Capture session closed.", flush=True)

    try:
        capture.start()
    except KeyboardInterrupt:
        print("\n[INFO] Stopped by user.", flush=True)

if __name__ == "__main__":
    main()
