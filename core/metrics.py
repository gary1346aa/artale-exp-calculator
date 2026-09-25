"""Core measurement state and EXP metrics computation engine.

Complies with the Google Python Style Guide.
Tracks session initial EXP, rolling-window velocity (1m, 10m, 60m),
accumulated gains, and level-up time estimations in Traditional Chinese.
"""

from collections import deque
import enum
import time
from typing import Any, Dict, Optional, Tuple


class MeasurementState(enum.Enum):
  """Lifecycle states for active EXP hunting measurement."""

  IDLE = "IDLE"  # Measurement reset or not started yet
  RUNNING = "RUNNING"  # Actively measuring elapsed time and EXP yield
  PAUSED = "PAUSED"  # Suspended measurement; auto-start disarmed


class ExpSample:
  """Timestamped EXP reading snapshot."""

  __slots__ = ("timestamp", "exp_value", "exp_percent")

  def __init__(
      self,
      timestamp: float,
      exp_value: int,
      exp_percent: Optional[float],
  ):
    self.timestamp = timestamp
    self.exp_value = exp_value
    self.exp_percent = exp_percent


class ExpMetricsEngine:
  """Metrics engine tracking measurement baselines, velocities, and session totals."""

  def __init__(self, window_seconds: int = 3600):
    self.window_seconds = window_seconds

    # Session initial EXP (captured once when app starts, preserved across resets)
    self.initial_exp: Optional[int] = None
    self.initial_exp_percent: Optional[float] = None
    self.initial_timestamp: Optional[float] = None

    # Current measurement baseline reference
    self.baseline_exp: Optional[int] = None
    self.baseline_exp_percent: Optional[float] = None
    self.baseline_timestamp: Optional[float] = None

    # Measurement state
    self.state: MeasurementState = MeasurementState.IDLE
    self.auto_start_enabled: bool = False

    # Timing
    self.measurement_start_time: Optional[float] = None
    self.pause_start_time: Optional[float] = None
    self.total_paused_duration: float = 0.0

    # Cumulative gains for current measurement
    self.total_gained_exp: int = 0
    self.total_gained_pct: float = 0.0

    # Samples buffer for rolling window rate calculations (1m, 10m, 60m)
    self.samples: deque[ExpSample] = deque()
    self.latest_sample: Optional[ExpSample] = None

  @property
  def is_running(self) -> bool:
    return self.state == MeasurementState.RUNNING

  @property
  def is_paused(self) -> bool:
    return self.state == MeasurementState.PAUSED

  @property
  def is_idle(self) -> bool:
    return self.state == MeasurementState.IDLE

  def set_auto_start(self, enabled: bool) -> None:
    """Sets the auto-start armed status."""
    self.auto_start_enabled = enabled

  def toggle_auto_start(self) -> bool:
    """Toggles auto-start between enabled and disabled."""
    self.auto_start_enabled = not self.auto_start_enabled
    return self.auto_start_enabled

  def start_measurement(self, timestamp: Optional[float] = None) -> bool:
    """Starts or resumes measurement manually (F7) or automatically."""
    now = timestamp if timestamp is not None else time.time()
    if self.state == MeasurementState.RUNNING:
      return False

    if self.state == MeasurementState.PAUSED:
      if self.pause_start_time is not None:
        self.total_paused_duration += now - self.pause_start_time
        self.pause_start_time = None
      self.state = MeasurementState.RUNNING
      return True

    # Starting from IDLE: set new baseline and start timer
    self.state = MeasurementState.RUNNING
    self.measurement_start_time = now
    self.total_paused_duration = 0.0
    self.pause_start_time = None
    self.total_gained_exp = 0
    self.total_gained_pct = 0.0
    self.samples.clear()

    if self.latest_sample is not None:
      self.baseline_exp = self.latest_sample.exp_value
      self.baseline_exp_percent = self.latest_sample.exp_percent
      self.baseline_timestamp = self.latest_sample.timestamp
      self.samples.append(self.latest_sample)

    return True

  def pause_measurement(
      self, disable_auto_start: bool = True, timestamp: Optional[float] = None
  ) -> bool:
    """Pauses the measurement (F7) without clearing current gains."""
    if self.state == MeasurementState.RUNNING:
      self.state = MeasurementState.PAUSED
      self.pause_start_time = (
          timestamp if timestamp is not None else time.time()
      )

    if disable_auto_start:
      self.auto_start_enabled = False

    return True

  def toggle_start_stop(self) -> str:
    """Toggles between active measurement and paused state (F7)."""
    if self.state == MeasurementState.RUNNING:
      self.pause_measurement(disable_auto_start=True)
      return "PAUSED"
    self.start_measurement()
    return "RUNNING"

  def reset_measurement(self, disable_auto_start: bool = True) -> None:
    """Resets current measurement baseline and timer without starting (F8).

    Initial session EXP is preserved.
    """
    self.state = MeasurementState.IDLE
    self.measurement_start_time = None
    self.pause_start_time = None
    self.total_paused_duration = 0.0
    self.total_gained_exp = 0
    self.total_gained_pct = 0.0
    self.samples.clear()

    if self.latest_sample is not None:
      self.baseline_exp = self.latest_sample.exp_value
      self.baseline_exp_percent = self.latest_sample.exp_percent
      self.baseline_timestamp = self.latest_sample.timestamp
      self.samples.append(self.latest_sample)

    if disable_auto_start:
      self.auto_start_enabled = False

  def reset_session(self) -> None:
    """Backward compatibility alias for reset_measurement."""
    self.reset_measurement(disable_auto_start=True)

  def toggle_pause(self) -> None:
    """Backward compatibility alias for toggle_start_stop."""
    self.toggle_start_stop()

  def add_sample(
      self,
      exp_value: int,
      exp_percent: Optional[float],
      timestamp: Optional[float] = None,
  ) -> bool:
    """Ingests a newly recognized EXP sample from OCR.

    Handles initial EXP capture, baseline tracking, auto-start triggering,
    and cumulative rate calculation.

    Args:
      exp_value: Total EXP points.
      exp_percent: EXP percentage (0.00 to 99.99%), or None.
      timestamp: Time of sample in epoch seconds (defaults to time.time()).

    Returns:
      True if sample was ingested.
    """
    now = timestamp if timestamp is not None else time.time()
    sample = ExpSample(now, exp_value, exp_percent)

    # 1. Capture session initial EXP once on launch
    if self.initial_exp is None:
      self.initial_exp = exp_value
      self.initial_exp_percent = exp_percent
      self.initial_timestamp = now

    # 2. Maintain baseline EXP if none set yet
    if self.baseline_exp is None:
      self.baseline_exp = exp_value
      self.baseline_exp_percent = exp_percent
      self.baseline_timestamp = now

    # 3. Check Auto-Start trigger when not running
    if self.state != MeasurementState.RUNNING:
      is_increasing = False
      if self.baseline_exp is not None and exp_value > self.baseline_exp:
        is_increasing = True
      elif (
          self.baseline_exp_percent is not None
          and exp_percent is not None
          and exp_percent > self.baseline_exp_percent
      ):
        is_increasing = True

      if self.auto_start_enabled and is_increasing:
        self.start_measurement()
      elif self.state == MeasurementState.IDLE and not self.auto_start_enabled:
        self.baseline_exp = exp_value
        self.baseline_exp_percent = exp_percent
        self.baseline_timestamp = now

    # 4. Ingest sample if measurement is actively running
    if self.state == MeasurementState.RUNNING:
      if not self.samples:
        self.samples.append(sample)
      else:
        prev = self.latest_sample if self.latest_sample else self.samples[-1]
        delta_exp = sample.exp_value - prev.exp_value
        delta_pct = (
            (sample.exp_percent - prev.exp_percent)
            if (sample.exp_percent is not None and prev.exp_percent is not None)
            else 0.0
        )

        # Level up detection: percent wrapped from near 100% to near 0%
        if (
            prev.exp_percent is not None
            and sample.exp_percent is not None
            and prev.exp_percent > 85.0
            and sample.exp_percent < 15.0
        ):
          wrap_pct = (100.0 - prev.exp_percent) + sample.exp_percent
          self.total_gained_pct += wrap_pct
          self.total_gained_exp += max(0, sample.exp_value)
        elif delta_exp >= 0:
          self.total_gained_exp += delta_exp
          if delta_pct > 0:
            self.total_gained_pct += delta_pct

        self.samples.append(sample)

      # Evict samples older than rolling window buffer
      cutoff = now - self.window_seconds - 60
      while self.samples and self.samples[0].timestamp < cutoff:
        self.samples.popleft()

    self.latest_sample = sample
    return True

  def _get_window_gain(self, window_sec: float) -> Tuple[int, float, float]:
    """Calculates (gained_exp, gained_pct, effective_seconds) within the last window_sec."""
    if not self.samples or len(self.samples) < 2:
      return 0, 0.0, 0.0

    now = self.samples[-1].timestamp
    cutoff = now - window_sec

    oldest = None
    for s in self.samples:
      if s.timestamp >= cutoff:
        oldest = s
        break

    if oldest is None or oldest == self.samples[-1]:
      oldest = self.samples[0]

    latest = self.samples[-1]
    dt = latest.timestamp - oldest.timestamp
    if dt <= 0:
      return 0, 0.0, 0.0

    d_exp = max(0, latest.exp_value - oldest.exp_value)
    d_pct = 0.0
    if latest.exp_percent is not None and oldest.exp_percent is not None:
      if latest.exp_percent >= oldest.exp_percent:
        d_pct = latest.exp_percent - oldest.exp_percent
      else:
        d_pct = (100.0 - oldest.exp_percent) + latest.exp_percent

    return d_exp, d_pct, dt

  def get_metrics(self, now: Optional[float] = None) -> Dict[str, Any]:
    """Generates all user-facing metrics formatted in Traditional Chinese."""
    now = now if now is not None else time.time()

    # Active measurement duration
    if (
        self.state == MeasurementState.IDLE
        or self.measurement_start_time is None
    ):
      elapsed = 0.0
    else:
      elapsed = now - self.measurement_start_time - self.total_paused_duration
      if (
          self.state == MeasurementState.PAUSED
          and self.pause_start_time is not None
      ):
        elapsed -= now - self.pause_start_time
      elapsed = max(0.0, elapsed)

    hrs = int(elapsed // 3600)
    mins = int((elapsed % 3600) // 60)
    secs = int(elapsed % 60)
    duration_str = f"{hrs:02d}:{mins:02d}:{secs:02d}"

    # Current EXP
    if self.latest_sample is not None:
      cur_val = self.latest_sample.exp_value
      cur_pct = self.latest_sample.exp_percent
      cur_pct_str = f"{cur_pct:.2f}%" if cur_pct is not None else "--"
      current_exp_str = f"{cur_val:,d} ({cur_pct_str})"
    else:
      cur_val = 0
      cur_pct = None
      current_exp_str = "無資料"

    # Initial EXP string
    if self.initial_exp is not None:
      init_pct_str = (
          f"{self.initial_exp_percent:.2f}%"
          if self.initial_exp_percent is not None
          else "--"
      )
      initial_exp_str = f"{self.initial_exp:,d} ({init_pct_str})"
    else:
      initial_exp_str = "無資料"

    # Baseline EXP string
    if self.baseline_exp is not None:
      base_pct_str = (
          f"{self.baseline_exp_percent:.2f}%"
          if self.baseline_exp_percent is not None
          else "--"
      )
      baseline_exp_str = f"{self.baseline_exp:,d} ({base_pct_str})"
    else:
      baseline_exp_str = "無資料"

    # Cumulative Gained EXP
    accum_exp_str = f"{self.total_gained_exp:,d}"
    total_gained_str = accum_exp_str

    # 1-minute rate metrics
    exp_1m, pct_1m, dt_1m = self._get_window_gain(60.0)
    rate_exp_per_sec = (
        (exp_1m / dt_1m)
        if dt_1m > 5.0
        else (self.total_gained_exp / elapsed if elapsed > 5.0 else 0.0)
    )
    rate_pct_per_sec = (
        (pct_1m / dt_1m)
        if dt_1m > 5.0
        else (self.total_gained_pct / elapsed if elapsed > 5.0 else 0.0)
    )

    rate_1m_exp = int(rate_exp_per_sec * 60)
    rate_1m_str = f"{rate_1m_exp:,d}"

    # 10-minute projection & actual
    exp_10m_actual, _, _ = self._get_window_gain(600.0)
    accum_10m_str = f"{exp_10m_actual:,d}"
    proj_10m_exp = int(rate_exp_per_sec * 600)
    proj_10m_str = f"{proj_10m_exp:,d}"

    # 60-minute projection & actual
    exp_60m_actual, _, _ = self._get_window_gain(3600.0)
    accum_60m_str = f"{exp_60m_actual:,d}"
    proj_60m_exp = int(rate_exp_per_sec * 3600)
    proj_60m_str = f"{proj_60m_exp:,d}"

    # Level up ETA
    eta_str = "-"
    if self.state == MeasurementState.RUNNING:
      if cur_pct is not None:
        if cur_pct >= 100.0:
          eta_str = "已滿級"
        elif rate_pct_per_sec > 1e-6:
          rem_pct = 100.0 - cur_pct
          sec_to_lvl = rem_pct / rate_pct_per_sec
          eta_hrs = int(sec_to_lvl // 3600)
          eta_mins = int((sec_to_lvl % 3600) // 60)
          if eta_hrs > 99:
            eta_str = ">99小時"
          elif eta_hrs > 0:
            eta_str = f"{eta_hrs}小時{eta_mins:02d}分"
          else:
            eta_secs = int(sec_to_lvl % 60)
            eta_str = f"{eta_mins}分{eta_secs:02d}秒"
        elif elapsed > 20.0:
          eta_str = "經驗無變動"
        else:
          eta_str = "計算中..."
    elif self.state == MeasurementState.PAUSED:
      eta_str = "已暫停"

    return {
        "state": self.state.value,
        "is_running": self.is_running,
        "is_paused": self.is_paused,
        "is_idle": self.is_idle,
        "auto_start_enabled": self.auto_start_enabled,
        "練功時長": duration_str,
        "當前經驗": current_exp_str,
        "啟動初始": initial_exp_str,
        "本次基準": baseline_exp_str,
        "累計經驗": accum_exp_str,
        "總獲得經驗": total_gained_str,
        "1分鐘經驗": rate_1m_str,
        "預估10分": proj_10m_str,
        "累積10分": accum_10m_str,
        "預估60分": proj_60m_str,
        "累積60分": accum_60m_str,
        "升級預估時間": eta_str,
        "raw_exp": cur_val,
        "raw_pct": cur_pct,
        "initial_exp": self.initial_exp,
        "initial_exp_percent": self.initial_exp_percent,
        "baseline_exp": self.baseline_exp,
        "baseline_exp_percent": self.baseline_exp_percent,
        "total_gained_exp": self.total_gained_exp,
        "total_gained_pct": self.total_gained_pct,
        "hourly_exp_rate": proj_60m_exp,
        "proj_10m_exp": proj_10m_exp,
    }
