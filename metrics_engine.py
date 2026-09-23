"""Artale EXP Metrics Engine.

Computes real-time EXP acquisition metrics, rolling-window rates (1m, 10m, 60m),
accumulated gains, and level-up ETA calculations in Traditional Chinese (繁體中文).
Handles level-up wrap-around, death penalties, and session pause/reset.
"""

from collections import deque
import time
from typing import Optional, Dict, Any, Tuple


class ExpSample:
    __slots__ = ("timestamp", "exp_value", "exp_percent")

    def __init__(self, timestamp: float, exp_value: int, exp_percent: Optional[float]):
        self.timestamp = timestamp
        self.exp_value = exp_value
        self.exp_percent = exp_percent


class ExpMetricsEngine:
    def __init__(self, window_seconds: int = 3600):
        self.window_seconds = window_seconds
        self.samples: deque[ExpSample] = deque()

        # Session tracking
        self.session_start_time: Optional[float] = None
        self.first_sample: Optional[ExpSample] = None
        self.latest_sample: Optional[ExpSample] = None

        # Cumulative tracking (handles level-ups where exp_value resets)
        self.total_gained_exp: int = 0
        self.total_gained_pct: float = 0.0

        # State flags
        self.is_paused: bool = False
        self.pause_start_time: Optional[float] = None
        self.total_paused_duration: float = 0.0

    def reset_session(self):
        """Resets all metrics and starts a fresh session."""
        self.samples.clear()
        self.session_start_time = None
        self.first_sample = None
        self.latest_sample = None
        self.total_gained_exp = 0
        self.total_gained_pct = 0.0
        self.is_paused = False
        self.pause_start_time = None
        self.total_paused_duration = 0.0

    def toggle_pause(self):
        """Toggles session pause / resume."""
        now = time.time()
        if not self.is_paused:
            self.is_paused = True
            self.pause_start_time = now
        else:
            self.is_paused = False
            if self.pause_start_time is not None:
                self.total_paused_duration += (now - self.pause_start_time)
                self.pause_start_time = None

    def add_sample(self, exp_value: int, exp_percent: Optional[float], timestamp: Optional[float] = None) -> bool:
        """Adds a newly recognized EXP sample from OCR.

        Returns True if the sample was successfully ingested.
        """
        if self.is_paused:
            return False

        now = timestamp if timestamp is not None else time.time()
        sample = ExpSample(now, exp_value, exp_percent)

        if self.first_sample is None:
            self.session_start_time = now
            self.first_sample = sample
            self.latest_sample = sample
            self.samples.append(sample)
            return True

        prev = self.latest_sample
        if prev is not None:
            # Detect delta
            delta_exp = sample.exp_value - prev.exp_value
            delta_pct = (sample.exp_percent - prev.exp_percent) if (sample.exp_percent is not None and prev.exp_percent is not None) else 0.0

            # Level up detection: exp_percent wrapped from near 100% to near 0%, or exp_value dropped
            if (prev.exp_percent is not None and sample.exp_percent is not None and
                    prev.exp_percent > 85.0 and sample.exp_percent < 15.0):
                # Wrapped level-up!
                wrap_pct = (100.0 - prev.exp_percent) + sample.exp_percent
                self.total_gained_pct += wrap_pct
                # For integer EXP, if max exp is unknown, use sample.exp_value as gain in new level
                self.total_gained_exp += max(0, sample.exp_value)
            elif delta_exp >= 0:
                self.total_gained_exp += delta_exp
                if delta_pct > 0:
                    self.total_gained_pct += delta_pct
            else:
                # EXP decreased without percentage wrap -> Death penalty or character relog
                # We record the sample but do not subtract from gained totals unless desired
                pass

        self.latest_sample = sample
        self.samples.append(sample)

        # Evict samples older than rolling buffer capacity
        cutoff = now - self.window_seconds - 60
        while self.samples and self.samples[0].timestamp < cutoff:
            self.samples.popleft()

        return True

    def _get_window_gain(self, window_sec: float) -> Tuple[int, float, float]:
        """Calculates (gained_exp, gained_pct, effective_seconds) within the last window_sec."""
        if not self.samples or len(self.samples) < 2:
            return 0, 0.0, 0.0

        now = self.samples[-1].timestamp
        cutoff = now - window_sec

        # Find the oldest sample in window
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
                # Level up in window
                d_pct = (100.0 - oldest.exp_percent) + latest.exp_percent

        return d_exp, d_pct, dt

    def get_metrics(self) -> Dict[str, Any]:
        """Generates all user-facing metrics formatted in Traditional Chinese."""
        now = time.time()
        if self.session_start_time is None or self.latest_sample is None:
            return {
                "練功時長": "00:00:00",
                "當前經驗": "無資料",
                "總獲得經驗": "0 (0.00%)",
                "1分鐘經驗": "0 (0.00%)",
                "預估10分": "0 (0.00%)",
                "累積10分": "0 (0.00%)",
                "預估60分": "0 (0.00%)",
                "累積60分": "0 (0.00%)",
                "升級預估時間": "尚未開始",
                "is_paused": self.is_paused,
            }

        # Active session duration
        elapsed = now - self.session_start_time - self.total_paused_duration
        if self.is_paused and self.pause_start_time is not None:
            elapsed -= (now - self.pause_start_time)
        elapsed = max(0.0, elapsed)

        hrs = int(elapsed // 3600)
        mins = int((elapsed % 3600) // 60)
        secs = int(elapsed % 60)
        duration_str = f"{hrs:02d}:{mins:02d}:{secs:02d}"

        # Current EXP
        cur_val = self.latest_sample.exp_value
        cur_pct = self.latest_sample.exp_percent
        cur_pct_str = f"{cur_pct:.2f}%" if cur_pct is not None else "--"
        current_exp_str = f"{cur_val:,d} ({cur_pct_str})"

        # Total Gained EXP
        total_gained_str = f"+{self.total_gained_exp:,d} (+{self.total_gained_pct:.2f}%)"

        # 1-minute window metrics
        exp_1m, pct_1m, dt_1m = self._get_window_gain(60.0)
        rate_exp_per_sec = (exp_1m / dt_1m) if dt_1m > 5.0 else (self.total_gained_exp / elapsed if elapsed > 5.0 else 0.0)
        rate_pct_per_sec = (pct_1m / dt_1m) if dt_1m > 5.0 else (self.total_gained_pct / elapsed if elapsed > 5.0 else 0.0)

        rate_1m_exp = int(rate_exp_per_sec * 60)
        rate_1m_pct = rate_pct_per_sec * 60
        rate_1m_str = f"+{rate_1m_exp:,d} (+{rate_1m_pct:.2f}%)"

        # 10-minute window metrics
        exp_10m_actual, pct_10m_actual, _ = self._get_window_gain(600.0)
        accum_10m_str = f"+{exp_10m_actual:,d} (+{pct_10m_actual:.2f}%)"

        proj_10m_exp = int(rate_exp_per_sec * 600)
        proj_10m_pct = rate_pct_per_sec * 600
        proj_10m_str = f"+{proj_10m_exp:,d} (+{proj_10m_pct:.2f}%)"

        # 60-minute window metrics
        exp_60m_actual, pct_60m_actual, _ = self._get_window_gain(3600.0)
        accum_60m_str = f"+{exp_60m_actual:,d} (+{pct_60m_actual:.2f}%)"

        proj_60m_exp = int(rate_exp_per_sec * 3600)
        proj_60m_pct = rate_pct_per_sec * 3600
        proj_60m_str = f"+{proj_60m_exp:,d} (+{proj_60m_pct:.2f}%)"

        # Level up ETA calculation
        eta_str = "計算中..."
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
            elif elapsed > 30.0:
                eta_str = "經驗無變動"

        return {
            "練功時長": duration_str,
            "當前經驗": current_exp_str,
            "總獲得經驗": total_gained_str,
            "1分鐘經驗": rate_1m_str,
            "預估10分": proj_10m_str,
            "累積10分": accum_10m_str,
            "預估60分": proj_60m_str,
            "累積60分": accum_60m_str,
            "升級預估時間": eta_str,
            "is_paused": self.is_paused,
            "raw_exp": cur_val,
            "raw_pct": cur_pct,
        }
