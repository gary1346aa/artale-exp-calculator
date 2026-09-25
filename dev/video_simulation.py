"""Background video playback worker simulating live game capture from video files.

Complies with the Google Python Style Guide.
Lazy-imports cv2 on demand to prevent production dependencies.
"""

import os
import time
from PyQt6.QtCore import QThread, pyqtSignal

from core.engine import parse_frame


class VideoSimulationWorker(QThread):
  """Background worker simulating live hunting capture from a video file."""

  frame_parsed = pyqtSignal(int, float, float)
  status_changed = pyqtSignal(str, bool)

  def __init__(
      self,
      video_path: str,
      playback_speed: float = 1.0,
      loop: bool = True,
      continuous_exp: bool = True,
  ):
    super().__init__()
    self.video_path: str = video_path
    self.playback_speed: float = max(0.1, playback_speed)
    self.loop: bool = loop
    self.continuous_exp: bool = continuous_exp
    self.running: bool = True
    self.is_paused: bool = False

  def run(self) -> None:
    """Executes the video simulation playback loop."""
    try:
      import cv2
    except ImportError:
      self.status_changed.emit(
          "開發功能：請安裝 opencv-python 以使用影片模擬功能", False
      )
      return

    cap = cv2.VideoCapture(self.video_path)
    if not cap.isOpened():
      self.status_changed.emit(
          f"無法開啟影片: {os.path.basename(self.video_path)}", False
      )
      return

    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0 or fps != fps:
      fps = 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    video_name = os.path.basename(self.video_path)
    self.status_changed.emit(f"模擬影片中: {video_name}", True)

    frame_step = max(1, int(round(fps)))
    current_frame_idx = 0
    exp_offset = 0
    first_exp_in_loop = None
    last_exp_in_loop = None

    while self.running:
      if self.is_paused:
        time.sleep(0.1)
        continue

      cap.set(cv2.CAP_PROP_POS_FRAMES, current_frame_idx)
      ret, frame = cap.read()
      if not ret:
        if self.loop and total_frames > 0:
          current_frame_idx = 0
          if (
              self.continuous_exp
              and first_exp_in_loop is not None
              and last_exp_in_loop is not None
          ):
            loop_gain = max(0, last_exp_in_loop - first_exp_in_loop)
            exp_offset += loop_gain
          first_exp_in_loop = None
          last_exp_in_loop = None
          continue
        else:
          self.status_changed.emit(f"影片結束: {video_name}", False)
          break

      try:
        parsed = parse_frame(frame)
        if parsed:
          exp_val, pct, raw_str, dt_ms = parsed[:4]
          if first_exp_in_loop is None:
            first_exp_in_loop = exp_val
          last_exp_in_loop = exp_val

          simulated_exp = exp_val + exp_offset
          self.frame_parsed.emit(
              simulated_exp, pct if pct is not None else -1.0, dt_ms
          )
          self.status_changed.emit(f"模擬影片中: {video_name}", True)
        else:
          self.status_changed.emit(f"搜尋經驗條中 ({video_name})...", False)
      except Exception as e:
        self.status_changed.emit(f"解析異常: {e}", False)

      current_frame_idx += frame_step
      if current_frame_idx >= total_frames:
        if self.loop:
          current_frame_idx = 0
          if (
              self.continuous_exp
              and first_exp_in_loop is not None
              and last_exp_in_loop is not None
          ):
            loop_gain = max(0, last_exp_in_loop - first_exp_in_loop)
            exp_offset += loop_gain
          first_exp_in_loop = None
          last_exp_in_loop = None
        else:
          break

      sleep_time = max(0.01, 1.0 / self.playback_speed)
      chunk = 0.05
      elapsed = 0.0
      while elapsed < sleep_time and self.running:
        to_sleep = min(chunk, sleep_time - elapsed)
        time.sleep(to_sleep)
        elapsed += to_sleep

    cap.release()

  def toggle_pause(self) -> bool:
    """Toggles paused state and returns the new state."""
    self.is_paused = not self.is_paused
    return self.is_paused

  def set_playback_speed(self, speed: float) -> None:
    """Updates the playback speed multiplier."""
    self.playback_speed = max(0.1, speed)

  def stop(self) -> None:
    """Stops the playback loop."""
    self.running = False
    self.wait(1000)
