"""Artale EXP Calculator - Command-Line Interface (CLI) Live Tracker.

Runs in the terminal without GUI overlay, outputting real-time EXP and
rate metrics to stdout at 1 FPS.
Complies with the Google Python Style Guide.
"""

from datetime import datetime
import sys
import time
from typing import Optional, Tuple

import config
from core.engine import is_cpp_active, parse_frame
from core.metrics import ExpMetricsEngine

try:
  from windows_capture import Frame, WindowsCapture
except ImportError:
  WindowsCapture = None
  Frame = None


def run_cli_tracker(
    window_name: str = config.DEFAULT_TARGET_WINDOW,
    sample_interval: float = 1.0,
) -> None:
  """Runs the real-time terminal tracking loop using Windows Graphics Capture.

  Args:
    window_name: Title of the target game window.
    sample_interval: Minimum time (in seconds) between processed frames.
  """
  if sys.platform != "win32" or WindowsCapture is None:
    print(
        "[ERROR] Live WGC capture is only supported on Windows with"
        " windows-capture installed."
    )
    return

  print("=" * 80, flush=True)
  print("  Artale EXP Calculator - CLI Live Tracker", flush=True)
  print("=" * 80, flush=True)
  print(f"Target Window : '{window_name}'", flush=True)
  print(f"Sampling Rate : {1.0 / sample_interval:.1f} FPS", flush=True)
  print(f"C++ Engine    : {'Active (SIMD)' if is_cpp_active() else 'Python Fallback'}", flush=True)
  print("=" * 80, flush=True)

  engine = ExpMetricsEngine()
  last_sample_time = 0.0
  last_res: Optional[Tuple[int, int]] = None

  try:
    capture = WindowsCapture(
        cursor_capture=False,
        draw_border=False,
        window_name=window_name,
    )
  except Exception as e:
    print(f"[ERROR] Failed to initialize WindowsCapture: {e}")
    return

  @capture.event
  def on_frame_arrived(frame: Frame, capture_control) -> None:
    nonlocal last_sample_time, last_res
    now = time.time()
    if now - last_sample_time < sample_interval:
      return
    last_sample_time = now

    now_str = datetime.now().strftime("%H:%M:%S")
    bgr = frame.convert_to_bgr().frame_buffer
    cur_res = (bgr.shape[1], bgr.shape[0])

    if last_res != cur_res:
      print(f"\n[{now_str}] Resolution changed: {cur_res[0]}x{cur_res[1]}", flush=True)
      last_res = cur_res

    parsed = parse_frame(bgr)
    if parsed:
      exp_val = parsed.exp_value
      pct = parsed.exp_percent
      dt_ms = parsed.elapsed_ms

      engine.add_sample(exp_val, pct)
      m = engine.get_metrics()

      print(
          f"[{now_str}] Current: {m['當前經驗']} | "
          f"Duration: {m['練功時長']} | "
          f"Total Gain: {m['總獲得經驗']} | "
          f"Rate/hr: {m['預估60分']} | "
          f"Level ETA: {m['升級預估時間']} | "
          f"Engine: {dt_ms:4.1f}ms",
          flush=True,
      )
    else:
      print(f"[{now_str}] [{cur_res[0]}x{cur_res[1]}] Scanning for EXP bar...", flush=True)

  @capture.event
  def on_closed() -> None:
    print("\n[INFO] Capture session closed.", flush=True)

  try:
    capture.start()
  except KeyboardInterrupt:
    print("\n[INFO] Stopped by user.", flush=True)


def main() -> None:
  """Entrypoint for standalone CLI execution."""
  run_cli_tracker()


if __name__ == "__main__":
  main()
