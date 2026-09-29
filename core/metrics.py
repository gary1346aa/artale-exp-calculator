"""Core measurement state and EXP metrics computation engine.

Complies with the Google Python Style Guide.
Tracks session initial EXP, rolling-window velocity (1m, 10m, 60m),
accumulated gains, and level-up time estimations in Traditional Chinese.
"""

from collections import deque
import enum
import time
from typing import Any, Dict, Optional, Tuple

from core.exp_table import (
    EXP_TO_NEXT_LEVEL,
    find_level_from_exp_and_pct,
    validate_sample,
)


class MeasurementState(enum.Enum):
  """Lifecycle states for active EXP hunting measurement."""

  IDLE = "IDLE"  # Measurement reset or not started yet
  RUNNING = "RUNNING"  # Actively measuring elapsed time and EXP yield
  PAUSED = "PAUSED"  # Suspended measurement; auto-start disarmed


class ExpSample:
  """Timestamped EXP reading snapshot."""

  __slots__ = ("timestamp", "exp_value", "exp_percent", "cum_exp", "cum_pct")

  def __init__(
      self,
      timestamp: float,
      exp_value: int,
      exp_percent: Optional[float],
      cum_exp: int = 0,
      cum_pct: float = 0.0,
  ):
    self.timestamp = timestamp
    self.exp_value = exp_value
    self.exp_percent = exp_percent
    self.cum_exp = cum_exp
    self.cum_pct = cum_pct


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
    self.auto_pause_enabled: bool = True
    self.auto_pause_seconds: int = 10

    # Timing
    self.measurement_start_time: Optional[float] = None
    self.pause_start_time: Optional[float] = None
    self.total_paused_duration: float = 0.0

    # Snapshot at pause start for excluding EXP/level-ups gained while paused
    self._pause_start_sample: Optional[ExpSample] = None
    self._pause_start_level: Optional[int] = None

    # Cumulative gains for current measurement
    self.total_gained_exp: int = 0
    self.total_gained_pct: float = 0.0

    # Level tracking and carryover across level-ups
    self.current_level: Optional[int] = None
    self.level_up_carry_exp: int = 0
    self.level_up_carry_pct: float = 0.0
    self._level_up_rollback: Optional[Dict[str, Any]] = None
    self._resync_candidate_level: Optional[int] = None
    self._resync_streak: int = 0
    self._resync_last_exp: int = -1

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

  def set_auto_pause(self, enabled: bool, seconds: Optional[int] = None) -> None:
    """Configures auto-pause enabled status and inactivity threshold in seconds."""
    self.auto_pause_enabled = bool(enabled)
    if seconds is not None:
      self.auto_pause_seconds = max(1, int(seconds))

  def check_auto_pause(self, now: Optional[float] = None) -> bool:
    """Checks if measurement should auto-pause due to inactivity.

    Uses latest_sample.timestamp (or measurement_start_time if no sample yet)
    and freezes the timer at `now` while keeping auto_start_enabled intact.

    Args:
      now: Current epoch timestamp (defaults to time.time()).

    Returns:
      True if measurement transitioned from RUNNING to PAUSED.
    """
    if self.state != MeasurementState.RUNNING or not self.auto_pause_enabled:
      return False
    if self.auto_pause_seconds <= 0:
      return False

    now = now if now is not None else time.time()
    ref_time = (
        self.latest_sample.timestamp
        if self.latest_sample is not None
        else self.measurement_start_time
    )
    if ref_time is not None and (now - ref_time) >= self.auto_pause_seconds:
      self.pause_measurement(disable_auto_start=False, timestamp=now)
      return True
    return False

  def start_measurement(self, timestamp: Optional[float] = None) -> bool:
    """Starts or resumes measurement manually (F7) or automatically."""
    now = timestamp if timestamp is not None else time.time()
    if self.state == MeasurementState.RUNNING:
      return False

    if self.state == MeasurementState.PAUSED:
      paused_dt = 0.0
      if self.pause_start_time is not None:
        paused_dt = max(0.0, now - self.pause_start_time)
        self.total_paused_duration += paused_dt
        self.pause_start_time = None

      # Shift rolling window sample timestamps forward by paused duration so
      # active window calculations (1m, 10m, 60m) exclude paused time.
      if paused_dt > 0.0:
        for s in self.samples:
          s.timestamp += paused_dt

      self.state = MeasurementState.RUNNING
      if self.latest_sample is not None:
        # Exclude any EXP or level-ups gained while paused:
        if self._pause_start_sample is not None:
          leveled_up_while_paused = (
              (
                  self.current_level is not None
                  and self._pause_start_level is not None
                  and self.current_level != self._pause_start_level
              )
              or self.latest_sample.exp_value < self._pause_start_sample.exp_value
          )
          if leveled_up_while_paused:
            # Bank pre-pause active gains and anchor new level baseline at resume EXP
            self.level_up_carry_exp = self.total_gained_exp
            self.level_up_carry_pct = self.total_gained_pct
            self.baseline_exp = self.latest_sample.exp_value
            self.baseline_exp_percent = self.latest_sample.exp_percent
            self._level_up_rollback = None
          else:
            paused_d_exp = max(
                0,
                self.latest_sample.exp_value - self._pause_start_sample.exp_value,
            )
            paused_d_pct = (
                max(
                    0.0,
                    self.latest_sample.exp_percent
                    - self._pause_start_sample.exp_percent,
                )
                if (
                    self.latest_sample.exp_percent is not None
                    and self._pause_start_sample.exp_percent is not None
                )
                else 0.0
            )
            if paused_d_exp > 0 and self.baseline_exp is not None:
              self.baseline_exp += paused_d_exp
            if paused_d_pct > 0.0 and self.baseline_exp_percent is not None:
              self.baseline_exp_percent += paused_d_pct

        self.latest_sample = ExpSample(
            now,
            self.latest_sample.exp_value,
            self.latest_sample.exp_percent,
            cum_exp=self.total_gained_exp,
            cum_pct=self.total_gained_pct,
        )
      self._pause_start_sample = None
      self._pause_start_level = None
      return True

    # Starting from IDLE: set new baseline and start timer
    self.state = MeasurementState.RUNNING
    self.measurement_start_time = now
    self.total_paused_duration = 0.0
    self.pause_start_time = None
    self._pause_start_sample = None
    self._pause_start_level = None
    self.total_gained_exp = 0
    self.total_gained_pct = 0.0
    self.level_up_carry_exp = 0
    self.level_up_carry_pct = 0.0
    self._level_up_rollback = None
    self.samples.clear()

    if self.latest_sample is not None:
      self.baseline_exp = self.latest_sample.exp_value
      self.baseline_exp_percent = self.latest_sample.exp_percent
      self.baseline_timestamp = now
      self.latest_sample = ExpSample(
          now,
          self.latest_sample.exp_value,
          self.latest_sample.exp_percent,
          cum_exp=0,
          cum_pct=0.0,
      )
      self.samples.append(self.latest_sample)

    return True

  def pause_measurement(
      self, disable_auto_start: bool = True, timestamp: Optional[float] = None
  ) -> bool:
    """Pauses the measurement (F7 or Auto-Pause) without clearing current gains."""
    if self.state == MeasurementState.RUNNING:
      self.state = MeasurementState.PAUSED
      self.pause_start_time = (
          timestamp if timestamp is not None else time.time()
      )
      self._pause_start_sample = self.latest_sample
      self._pause_start_level = self.current_level

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
    self._pause_start_sample = None
    self._pause_start_level = None
    self.total_paused_duration = 0.0
    self.total_gained_exp = 0
    self.total_gained_pct = 0.0
    self.level_up_carry_exp = 0
    self.level_up_carry_pct = 0.0
    self._level_up_rollback = None
    self.samples.clear()

    if self.latest_sample is not None:
      self.baseline_exp = self.latest_sample.exp_value
      self.baseline_exp_percent = self.latest_sample.exp_percent
      self.baseline_timestamp = self.latest_sample.timestamp
      self.latest_sample = ExpSample(
          self.latest_sample.timestamp,
          self.latest_sample.exp_value,
          self.latest_sample.exp_percent,
          cum_exp=0,
          cum_pct=0.0,
      )
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
    auto-pause inactivity detection, mathematical cross-validation against
    the EXP table, and cumulative rate calculations.

    Args:
      exp_value: Total EXP points.
      exp_percent: EXP percentage (0.00 to 99.99%), or None.
      timestamp: Time of sample in epoch seconds (defaults to time.time()).

    Returns:
      True if sample was ingested.
    """
    if exp_value < 0:
      return False

    now = timestamp if timestamp is not None else time.time()
    prev_tracked_level = self.current_level

    # Mathematical cross-validation against EXP table
    is_valid, matched_level = validate_sample(
        exp_value, exp_percent, self.current_level
    )
    if not is_valid and self._level_up_rollback is not None:
      rb = self._level_up_rollback
      rb_valid, rb_lvl = validate_sample(
          exp_value, exp_percent, rb["prev_level"]
      )
      if (
          rb_valid
          and rb_lvl == rb["prev_level"]
          and exp_value >= rb["prev_latest_sample"].exp_value
      ):
        self.current_level = rb["prev_level"]
        prev_tracked_level = rb["prev_level"]
        self.level_up_carry_exp = rb["prev_carry_exp"]
        self.level_up_carry_pct = rb["prev_carry_pct"]
        self.baseline_exp = rb["prev_baseline_exp"]
        self.baseline_exp_percent = rb["prev_baseline_pct"]
        self.total_gained_exp = rb["prev_total_gained_exp"]
        self.total_gained_pct = rb["prev_total_gained_pct"]
        self.latest_sample = rb["prev_latest_sample"]
        if self.samples and self.samples[-1] is rb["level_up_sample"]:
          self.samples.pop()
        self._level_up_rollback = None
        is_valid = True
        matched_level = rb_lvl

    if not is_valid:
      alt_level = (
          find_level_from_exp_and_pct(exp_value, exp_percent)
          if exp_percent is not None
          else None
      )
      if alt_level is not None:
        if (
            alt_level == self._resync_candidate_level
            and exp_value >= self._resync_last_exp
        ):
          self._resync_streak += 1
          self._resync_last_exp = exp_value
        else:
          self._resync_candidate_level = alt_level
          self._resync_streak = 1
          self._resync_last_exp = exp_value

        if self._resync_streak >= 3:
          self.current_level = alt_level
          self._resync_candidate_level = None
          self._resync_streak = 0
          self._resync_last_exp = -1
          is_valid = True
          matched_level = alt_level
        else:
          return False
      else:
        self._resync_candidate_level = None
        self._resync_streak = 0
        self._resync_last_exp = -1
        return False
    else:
      self._resync_candidate_level = None
      self._resync_streak = 0
      self._resync_last_exp = -1

    sample = ExpSample(
        now,
        exp_value,
        exp_percent,
        cum_exp=self.total_gained_exp,
        cum_pct=self.total_gained_pct,
    )

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

    # 3. Check Auto-Start trigger when not running (IDLE or PAUSED)
    if self.state != MeasurementState.RUNNING:
      ref_exp = (
          self.latest_sample.exp_value
          if (
              self.state == MeasurementState.PAUSED
              and self.latest_sample is not None
          )
          else self.baseline_exp
      )
      ref_pct = (
          self.latest_sample.exp_percent
          if (
              self.state == MeasurementState.PAUSED
              and self.latest_sample is not None
          )
          else self.baseline_exp_percent
      )

      is_paused_level_up = False
      if (
          matched_level is not None
          and prev_tracked_level is not None
          and matched_level > prev_tracked_level
      ):
        is_paused_level_up = True
      elif (
          ref_pct is not None
          and exp_percent is not None
          and ref_pct >= (98.0 if exp_percent == 0.0 else 95.0)
          and exp_percent < 15.0
      ):
        is_paused_level_up = True

      is_increasing = False
      if is_paused_level_up:
        is_increasing = True
      elif ref_exp is not None and exp_value > ref_exp:
        is_increasing = True
      elif (
          ref_pct is not None
          and exp_percent is not None
          and exp_percent > ref_pct
      ):
        is_increasing = True

      if self.auto_start_enabled and is_increasing:
        self.start_measurement(timestamp=now)
      else:
        if self.state == MeasurementState.PAUSED and self.latest_sample is not None:
          if not is_paused_level_up and exp_value < self.latest_sample.exp_value:
            # Reject negative OCR drop while paused
            return False
          if is_paused_level_up:
            self._level_up_rollback = {
                "prev_level": prev_tracked_level,
                "prev_carry_exp": self.level_up_carry_exp,
                "prev_carry_pct": self.level_up_carry_pct,
                "prev_baseline_exp": self.baseline_exp,
                "prev_baseline_pct": self.baseline_exp_percent,
                "prev_total_gained_exp": self.total_gained_exp,
                "prev_total_gained_pct": self.total_gained_pct,
                "prev_latest_sample": self.latest_sample,
                "level_up_sample": sample,
            }
            if (
                matched_level is not None
                and prev_tracked_level is not None
                and matched_level > prev_tracked_level
            ):
              self.current_level = matched_level
            elif prev_tracked_level is not None:
              self.current_level = prev_tracked_level + 1
            elif matched_level is not None:
              self.current_level = matched_level
          else:
            if exp_value > self.latest_sample.exp_value or (
                exp_percent is not None
                and self.latest_sample.exp_percent is not None
                and exp_percent > self.latest_sample.exp_percent
            ):
              self._level_up_rollback = None
            if matched_level is not None:
              self.current_level = matched_level
        else:
          if self.state == MeasurementState.IDLE and not self.auto_start_enabled:
            self.baseline_exp = exp_value
            self.baseline_exp_percent = exp_percent
            self.baseline_timestamp = now
          if matched_level is not None:
            self.current_level = matched_level

        if (
            self.latest_sample is None
            or not self.auto_start_enabled
            or self.state == MeasurementState.IDLE
        ):
          self.latest_sample = sample
        return True

    # 4. Ingest sample if measurement is actively running
    if self.state == MeasurementState.RUNNING:
      if not self.samples:
        if matched_level is not None:
          self.current_level = matched_level
        sample.cum_exp = self.total_gained_exp
        sample.cum_pct = self.total_gained_pct
        self.samples.append(sample)
        self.latest_sample = sample
      else:
        prev = self.latest_sample if self.latest_sample else self.samples[-1]
        delta_exp = sample.exp_value - prev.exp_value
        delta_pct = (
            (sample.exp_percent - prev.exp_percent)
            if (sample.exp_percent is not None and prev.exp_percent is not None)
            else 0.0
        )
        dt = sample.timestamp - prev.timestamp

        # Level up detection:
        is_level_up = False
        prev_level = None
        if prev.exp_percent is not None and prev.exp_value > 0:
          prev_level = find_level_from_exp_and_pct(
              prev.exp_value, prev.exp_percent
          )
        if prev_level is None:
          prev_level = prev_tracked_level

        if (
            matched_level is not None
            and prev_level is not None
            and matched_level > prev_level
        ):
          is_level_up = True
        elif (
            prev.exp_percent is not None
            and sample.exp_percent is not None
            and prev.exp_percent >= (98.0 if sample.exp_percent == 0.0 else 95.0)
            and sample.exp_percent < 15.0
        ):
          is_level_up = True

        if is_level_up:
          self._level_up_rollback = {
              "prev_level": prev_tracked_level,
              "prev_carry_exp": self.level_up_carry_exp,
              "prev_carry_pct": self.level_up_carry_pct,
              "prev_baseline_exp": self.baseline_exp,
              "prev_baseline_pct": self.baseline_exp_percent,
              "prev_total_gained_exp": self.total_gained_exp,
              "prev_total_gained_pct": self.total_gained_pct,
              "prev_latest_sample": prev,
              "level_up_sample": sample,
          }
          ref_lvl = prev_level if prev_level is not None else prev_tracked_level
          req_exp = (
              EXP_TO_NEXT_LEVEL.get(ref_lvl) if ref_lvl is not None else None
          )
          if req_exp is not None and self.baseline_exp is not None:
            level_gain = max(0, req_exp - self.baseline_exp)
          else:
            level_gain = max(0, prev.exp_value)

          self.level_up_carry_exp += level_gain

          if prev.exp_percent is not None:
            self.level_up_carry_pct += max(
                0.0, 100.0 - (self.baseline_exp_percent or 0.0)
            )

          # Reset baseline for the new level
          self.baseline_exp = 0
          self.baseline_exp_percent = 0.0
          if (
              matched_level is not None
              and prev_level is not None
              and matched_level > prev_level
          ):
            self.current_level = matched_level
          elif prev_tracked_level is not None:
            self.current_level = prev_tracked_level + 1
          elif matched_level is not None:
            self.current_level = matched_level

        else:
          # Normal hunting within same level
          if delta_exp < 0:
            # Negative drop without level up is an OCR outlier! Discard.
            return False

          if dt > 0 and (delta_exp / dt) > 2_000_000 and delta_pct < 0.05:
            # Absurd single-second spike (> 2M/s without pct increase): Discard.
            return False

          if delta_exp > 0 or delta_pct > 0.0:
            self._level_up_rollback = None

          if matched_level is not None:
            self.current_level = matched_level

        # Cumulative gain from baseline and level-up carry:
        if self.baseline_exp is not None:
          self.total_gained_exp = self.level_up_carry_exp + max(
              0, sample.exp_value - self.baseline_exp
          )
        if (
            self.baseline_exp_percent is not None
            and sample.exp_percent is not None
        ):
          self.total_gained_pct = self.level_up_carry_pct + max(
              0.0, sample.exp_percent - self.baseline_exp_percent
          )

        sample.cum_exp = self.total_gained_exp
        sample.cum_pct = self.total_gained_pct

        has_gained = is_level_up or delta_exp > 0 or delta_pct > 0.0
        if has_gained:
          self.samples.append(sample)
          self.latest_sample = sample
        else:
          self.check_auto_pause(now=now)

      # Evict samples older than rolling window buffer while keeping at least 1 sample
      cutoff = now - self.window_seconds - 60
      while len(self.samples) > 1 and self.samples[0].timestamp < cutoff:
        self.samples.popleft()

    return True

  def _get_window_gain(
      self, window_sec: float, now: Optional[float] = None
  ) -> Tuple[int, float, float]:
    """Calculates (gained_exp, gained_pct, effective_seconds) within the last window_sec."""
    if not self.samples:
      return 0, 0.0, 0.0

    latest = self.latest_sample if self.latest_sample else self.samples[-1]
    if (
        self.state == MeasurementState.PAUSED
        and self.pause_start_time is not None
    ):
      ref_now = self.pause_start_time
    elif now is None:
      ref_now = latest.timestamp
    else:
      ref_now = max(latest.timestamp, now)

    cutoff = ref_now - window_sec

    oldest = None
    for s in self.samples:
      if s.timestamp >= cutoff:
        oldest = s
        break

    if oldest is None:
      return 0, 0.0, 0.0

    dt = ref_now - oldest.timestamp
    if dt <= 0:
      return 0, 0.0, 0.0

    d_exp = max(0, latest.cum_exp - oldest.cum_exp)
    d_pct = max(0.0, latest.cum_pct - oldest.cum_pct)
    return d_exp, d_pct, dt

  def get_metrics(self, now: Optional[float] = None) -> Dict[str, Any]:
    """Generates all user-facing metrics formatted in Traditional Chinese."""
    now = now if now is not None else time.time()

    # Check if inactivity threshold has been reached
    self.check_auto_pause(now=now)

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

    # 1. 1-minute rate metrics
    exp_1m, pct_1m, dt_1m = self._get_window_gain(60.0, now=now)
    if self.state == MeasurementState.IDLE or elapsed <= 0.0:
      rate_1m_exp = 0
      rate_1m_str = "0"
    elif dt_1m >= 5.0:
      rate_1m_exp = int(round((exp_1m / dt_1m) * 60.0))
      rate_1m_str = f"{rate_1m_exp:,d}"
    else:
      rate_1m_exp = int(round((self.total_gained_exp / elapsed) * 60.0))
      rate_1m_str = f"{rate_1m_exp:,d}"

    # 2. 10-minute metrics: 累積10分 & 預估10分
    # Cumulative actual gained within 10-min horizon:
    if elapsed >= 600.0:
      exp_10m_actual, _, _ = self._get_window_gain(600.0, now=now)
      accum_10m_exp = exp_10m_actual
    else:
      accum_10m_exp = self.total_gained_exp

    if self.state == MeasurementState.IDLE or elapsed <= 0.0:
      accum_10m_str = "0"
      proj_10m_exp = 0
      proj_10m_str = "0"
    elif elapsed >= 600.0:
      # At or past 10 minutes: projection equals 10-minute accumulated actual
      accum_10m_str = f"{accum_10m_exp:,d}"
      proj_10m_exp = accum_10m_exp
      proj_10m_str = f"{proj_10m_exp:,d}"
    else:
      # First 10 minutes: project via cumulative session average rate, converging into actual
      accum_10m_str = f"{accum_10m_exp:,d}"
      session_rate = self.total_gained_exp / elapsed
      proj_10m_exp = int(round(session_rate * 600.0))
      proj_10m_str = f"{proj_10m_exp:,d}"

    # 3. 60-minute metrics: 累積60分 & 預估60分 (時薪)
    # Cumulative actual gained within 60-min horizon:
    if elapsed >= 3600.0:
      exp_60m_actual, _, _ = self._get_window_gain(3600.0, now=now)
      accum_60m_exp = exp_60m_actual
    else:
      accum_60m_exp = self.total_gained_exp

    if self.state == MeasurementState.IDLE or elapsed <= 0.0:
      accum_60m_str = "0"
      proj_60m_exp = 0
      proj_60m_str = "0"
    elif elapsed >= 3600.0:
      # At or past 60 minutes: projection equals 60-minute accumulated actual
      accum_60m_str = f"{accum_60m_exp:,d}"
      proj_60m_exp = accum_60m_exp
      proj_60m_str = f"{proj_60m_exp:,d}"
    else:
      # Before 60 minutes: project via cumulative session average rate, converging into actual
      accum_60m_str = f"{accum_60m_exp:,d}"
      session_rate = self.total_gained_exp / elapsed
      proj_60m_exp = int(round(session_rate * 3600.0))
      proj_60m_str = f"{proj_60m_exp:,d}"

    # 4. Level up ETA
    eta_str = "-"
    if self.state == MeasurementState.RUNNING and elapsed > 0.0:
      if cur_pct is not None:
        if cur_pct >= 100.0:
          eta_str = "已滿級"
        else:
          if elapsed >= 600.0:
            _, pct_10m, dt_10m = self._get_window_gain(600.0, now=now)
            rate_pct_sec = (
                pct_10m / dt_10m
                if dt_10m > 30.0
                else self.total_gained_pct / elapsed
            )
          else:
            rate_pct_sec = self.total_gained_pct / elapsed

          if rate_pct_sec > 1e-6:
            rem_pct = 100.0 - cur_pct
            sec_to_lvl = rem_pct / rate_pct_sec
            eta_hrs = int(sec_to_lvl // 3600)
            eta_mins = int((sec_to_lvl % 3600) // 60)
            if eta_hrs > 99:
              eta_str = ">99小時"
            elif eta_hrs > 0:
              eta_str = f"{eta_hrs}小時{eta_mins:02d}分"
            else:
              eta_secs = int(sec_to_lvl % 60)
              eta_str = f"{eta_mins}分{eta_secs:02d}秒"
          else:
            eta_str = "經驗無變動"
    elif self.state == MeasurementState.PAUSED:
      eta_str = "已暫停"

    return {
        "state": self.state.value,
        "is_running": self.is_running,
        "is_paused": self.is_paused,
        "is_idle": self.is_idle,
        "auto_start_enabled": self.auto_start_enabled,
        "auto_pause_enabled": self.auto_pause_enabled,
        "auto_pause_seconds": self.auto_pause_seconds,
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
        "rate_1m_exp": rate_1m_exp,
        "accum_10m_exp": accum_10m_exp,
        "accum_60m_exp": accum_60m_exp,
        "current_level": self.current_level,
        "current_level_str": (
            f"Lv. {self.current_level}"
            if self.current_level is not None
            else "--"
        ),
        "remaining_exp": (
            max(0, EXP_TO_NEXT_LEVEL[self.current_level] - cur_val)
            if (
                self.current_level is not None
                and self.current_level in EXP_TO_NEXT_LEVEL
                and cur_val > 0
            )
            else None
        ),
        "remaining_exp_str": (
            f"{max(0, EXP_TO_NEXT_LEVEL[self.current_level] - cur_val):,d}"
            if (
                self.current_level is not None
                and self.current_level in EXP_TO_NEXT_LEVEL
                and cur_val > 0
            )
            else "--"
        ),
    }
