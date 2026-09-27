"""Unit tests for upgraded ExpMetricsEngine.

Validates:
1. Initial EXP is set once on first sample and persists across measurement resets.
2. Baseline EXP is established per measurement.
3. Auto-start automatically starts measurement when EXP increases.
4. F7 stops/pauses and disables auto-start once.
5. F8 resets measurement to IDLE and disables auto-start once.
6. F7 or auto-start resumes measurement.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.metrics import ExpMetricsEngine, MeasurementState


class TestExpMetricsEngine(unittest.TestCase):

  def test_initial_exp_persists_across_resets(self):
    engine = ExpMetricsEngine()
    self.assertIsNone(engine.initial_exp)

    # First sample: 1,000,000 EXP (10.0%)
    engine.add_sample(1000000, 10.0, timestamp=100.0)
    self.assertEqual(engine.initial_exp, 1000000)
    self.assertEqual(engine.initial_exp_percent, 10.0)

    # Start measurement, gain some EXP
    engine.start_measurement()
    engine.add_sample(1050000, 10.5, timestamp=110.0)
    self.assertEqual(engine.total_gained_exp, 50000)

    # Reset measurement (F8)
    engine.reset_measurement(disable_auto_start=True)
    self.assertEqual(engine.state, MeasurementState.IDLE)
    self.assertEqual(engine.total_gained_exp, 0)

    # Initial EXP MUST still be 1,000,000!
    self.assertEqual(engine.initial_exp, 1000000)
    self.assertEqual(engine.initial_exp_percent, 10.0)

    # Baseline should be the latest EXP (1,050,000)
    self.assertEqual(engine.baseline_exp, 1050000)
    self.assertEqual(engine.baseline_exp_percent, 10.5)

  def test_auto_start_triggers_on_exp_increase(self):
    engine = ExpMetricsEngine()
    engine.set_auto_start(True)

    # Initial sample arrived
    engine.add_sample(2000000, 20.0, timestamp=100.0)
    self.assertEqual(engine.state, MeasurementState.IDLE)

    # EXP unchanged -> remains IDLE
    engine.add_sample(2000000, 20.0, timestamp=101.0)
    self.assertEqual(engine.state, MeasurementState.IDLE)

    # EXP increases -> auto-start triggers!
    engine.add_sample(2005000, 20.05, timestamp=102.0)
    self.assertEqual(engine.state, MeasurementState.RUNNING)
    self.assertEqual(engine.total_gained_exp, 5000)

  def test_f7_pause_disables_auto_start_once(self):
    engine = ExpMetricsEngine()
    engine.set_auto_start(True)
    engine.add_sample(1000000, 10.0, timestamp=100.0)
    engine.add_sample(1010000, 10.1, timestamp=105.0)  # triggers auto-start
    self.assertEqual(engine.state, MeasurementState.RUNNING)
    self.assertTrue(engine.auto_start_enabled)

    # User presses F7 to pause/stop
    engine.toggle_start_stop()
    self.assertEqual(engine.state, MeasurementState.PAUSED)
    # Auto-start is disabled once!
    self.assertFalse(engine.auto_start_enabled)

    # EXP increases while paused -> does NOT auto-resume because auto-start was disabled
    engine.add_sample(1020000, 10.2, timestamp=110.0)
    self.assertEqual(engine.state, MeasurementState.PAUSED)

    # User re-enables auto-start ("autostart to resume")
    engine.set_auto_start(True)
    engine.add_sample(1030000, 10.3, timestamp=115.0)
    self.assertEqual(engine.state, MeasurementState.RUNNING)

  def test_f8_reset_disables_auto_start_once(self):
    engine = ExpMetricsEngine()
    engine.set_auto_start(True)
    engine.add_sample(1000000, 10.0, timestamp=100.0)
    engine.add_sample(1010000, 10.1, timestamp=105.0)
    self.assertEqual(engine.state, MeasurementState.RUNNING)

    # User presses F8 to reset
    engine.reset_measurement(disable_auto_start=True)
    self.assertEqual(engine.state, MeasurementState.IDLE)
    self.assertFalse(engine.auto_start_enabled)
    self.assertEqual(engine.total_gained_exp, 0)
    self.assertEqual(engine.baseline_exp, 1010000)

    # Manual F7 starts new measurement with new baseline
    engine.toggle_start_stop()
    self.assertEqual(engine.state, MeasurementState.RUNNING)
    engine.add_sample(1015000, 10.15, timestamp=110.0)
    self.assertEqual(engine.total_gained_exp, 5000)

  def test_gains_formatting_without_percentage(self):
    engine = ExpMetricsEngine()
    engine.add_sample(1000000, 10.0, timestamp=100.0)
    engine.start_measurement(timestamp=100.0)
    engine.add_sample(1050000, 10.5, timestamp=160.0)

    m = engine.get_metrics(now=160.0)
    self.assertIn("累計經驗", m)
    self.assertEqual(m["累計經驗"], "50,000")
    # Verify no percentages and no plus signs in any gain/rate fields
    for key in [
        "累計經驗",
        "總獲得經驗",
        "1分鐘經驗",
        "預估10分",
        "累積10分",
        "預估60分",
        "累積60分",
    ]:
      self.assertNotIn("%", m[key], f"Key {key} should not contain '%'")
      self.assertNotIn("+", m[key], f"Key {key} should not contain '+'")

  def test_immediate_prediction_without_warmup(self):
    engine = ExpMetricsEngine()
    engine.add_sample(1000000, 10.0, timestamp=100.0)
    engine.start_measurement(timestamp=100.0)
    engine.add_sample(1005000, 10.05, timestamp=105.0)

    # At t = 105s (elapsed = 5s), calculates immediately without warmup delay
    m = engine.get_metrics(now=105.0)
    self.assertNotEqual(m["預估10分"], "計算中...")
    self.assertEqual(m["預估10分"], "600,000")  # 5,000 / 5s * 600s
    self.assertEqual(m["預估60分"], "3,600,000")  # 5,000 / 5s * 3600s
    self.assertNotEqual(m["升級預估時間"], "計算中...")

  def test_progressive_convergence_at_10m_and_60m(self):
    engine = ExpMetricsEngine()
    # Baseline at t=0
    engine.add_sample(10000000, 50.0, timestamp=0.0)
    engine.start_measurement(timestamp=0.0)

    # 1. At 60 seconds (1 minute): gain 100,000 EXP
    engine.add_sample(10100000, 50.5, timestamp=60.0)
    m_1m = engine.get_metrics(now=60.0)
    # Session pace = 100,000 / 60s -> 10m prediction = 1,000,000; 60m prediction = 6,000,000
    self.assertEqual(m_1m["預估10分"], "1,000,000")
    self.assertEqual(m_1m["預估60分"], "6,000,000")
    self.assertEqual(m_1m["累積10分"], "100,000")
    self.assertEqual(m_1m["累積60分"], "100,000")

    # 2. Simulate consistent grinding up to 600s (10 minutes): total 1,000,000 EXP gained
    for t in range(120, 601, 60):
      engine.add_sample(
          10000000 + (t // 60) * 100000, 50.0 + (t / 60) * 0.5, timestamp=float(t)
      )

    m_10m = engine.get_metrics(now=600.0)
    # At exactly 10 minutes: 預估10分 MUST EQUAL 累積10分!
    self.assertEqual(m_10m["預估10分"], "1,000,000")
    self.assertEqual(m_10m["累積10分"], "1,000,000")
    self.assertEqual(m_10m["預估10分"], m_10m["累積10分"])
    self.assertEqual(m_10m["預估60分"], "6,000,000")

    # 3. Simulate consistent grinding up to 3600s (60 minutes): total 6,000,000 EXP gained
    for t in range(720, 3601, 120):
      engine.add_sample(
          10000000 + (t // 60) * 100000, 50.0 + (t / 60) * 0.5, timestamp=float(t)
      )

    m_60m = engine.get_metrics(now=3600.0)
    # At exactly 60 minutes: 預估60分 MUST EQUAL 累積60分!
    self.assertEqual(m_60m["預估60分"], "6,000,000")
    self.assertEqual(m_60m["累積60分"], "6,000,000")
    self.assertEqual(m_60m["預估60分"], m_60m["累積60分"])

  def test_level_estimation_from_real_screenshot(self):
    engine = ExpMetricsEngine()
    # Real sample from screenshot: 686,615,140 (44.57%)
    accepted = engine.add_sample(686615140, 44.57, timestamp=100.0)
    self.assertTrue(accepted)
    self.assertEqual(engine.current_level, 194)

    m = engine.get_metrics(now=100.0)
    self.assertEqual(m["current_level"], 194)
    self.assertEqual(m["current_level_str"], "Lv. 194")
    # Level 194 required EXP is 1,540,197,871
    expected_remaining = 1540197871 - 686615140
    self.assertEqual(m["remaining_exp"], expected_remaining)

  def test_outlier_rejection_for_digit_drop_glitch(self):
    """Simulates friend's exact glitch: OCR dropping a digit (60M vs 686M)."""
    engine = ExpMetricsEngine()
    engine.add_sample(686615140, 44.57, timestamp=100.0)
    engine.start_measurement(timestamp=100.0)

    # Glitched frame: OCR drops a digit and reads 8 digits instead of 9
    corrupted_accepted = engine.add_sample(60010233, 44.57, timestamp=101.0)
    # MUST BE REJECTED by mathematical table validation!
    self.assertFalse(corrupted_accepted)
    # latest_sample must NOT be corrupted
    self.assertEqual(engine.latest_sample.exp_value, 686615140)
    self.assertEqual(engine.total_gained_exp, 0)

    # Next frame recovers to normal 9-digit hunting
    recovery_accepted = engine.add_sample(686620000, 44.57, timestamp=102.0)
    self.assertTrue(recovery_accepted)
    self.assertEqual(engine.latest_sample.exp_value, 686620000)
    # Accumulated gain must be exactly 4,860 - NOT a 626M spike!
    self.assertEqual(engine.total_gained_exp, 4860)

    m = engine.get_metrics(now=102.0)
    self.assertEqual(m["累計經驗"], "4,860")
    self.assertNotIn("626", m["累計經驗"])

  def test_exact_level_up_carryover(self):
    """Verifies that leveling up uses exact EXP table values across boundaries."""
    engine = ExpMetricsEngine()
    # Start near end of Level 194: 1,540,100,000 (99.99%)
    engine.add_sample(1540100000, 99.99, timestamp=100.0)
    engine.start_measurement(timestamp=100.0)
    self.assertEqual(engine.current_level, 194)

    # Level up to 195! EXP wraps to 5,000 (0.00%)
    accepted = engine.add_sample(5000, 0.00, timestamp=110.0)
    self.assertTrue(accepted)
    self.assertEqual(engine.current_level, 195)

    # Level 194 total cap is 1,540,197,871
    # Gained in Lv 194: 1,540,197,871 - 1,540,100,000 = 97,871
    # Gained in Lv 195: 5,000
    # Total gained across level up: 97,871 + 5,000 = 102,871
    self.assertEqual(engine.total_gained_exp, 102871)

    # Gain more EXP in Level 195
    engine.add_sample(15000, 0.00, timestamp=120.0)
    self.assertEqual(engine.total_gained_exp, 112871)

  def test_auto_pause_triggers_after_timeout_and_auto_resumes(self):
    """Verifies that Auto-Pause triggers after N seconds of no EXP gain, preserves auto_start_enabled, and resumes on EXP gain."""
    engine = ExpMetricsEngine()
    engine.set_auto_start(True)
    self.assertTrue(engine.auto_pause_enabled)
    self.assertEqual(engine.auto_pause_seconds, 10)

    # First sample at t=100s
    engine.add_sample(1000000, 10.0, timestamp=100.0)
    # EXP gain at t=102s triggers auto-start
    engine.add_sample(1005000, 10.05, timestamp=102.0)
    self.assertEqual(engine.state, MeasurementState.RUNNING)
    self.assertEqual(len(engine.samples), 2)

    # Flat EXP samples at t=105s, 110s (< 10s since t=102s): still RUNNING, no duplicate samples appended
    engine.add_sample(1005000, 10.05, timestamp=105.0)
    engine.add_sample(1005000, 10.05, timestamp=111.9)
    self.assertEqual(engine.state, MeasurementState.RUNNING)
    self.assertEqual(len(engine.samples), 2)
    self.assertEqual(engine.latest_sample.timestamp, 102.0)

    # At t=112.0s (exactly 10s since last EXP gain at t=102s): Auto-Pause triggers!
    engine.add_sample(1005000, 10.05, timestamp=112.0)
    self.assertEqual(engine.state, MeasurementState.PAUSED)
    # Auto-start MUST remain enabled so hunting resumes automatically
    self.assertTrue(engine.auto_start_enabled)
    # Elapsed time is frozen at t=112.0s (10.0s total elapsed since t=102.0s)
    self.assertEqual(engine.get_metrics(now=120.0)["練功時長"], "00:00:10")

    # Flat EXP while paused at t=115s must NOT falsely resume measurement
    engine.add_sample(1005000, 10.05, timestamp=115.0)
    self.assertEqual(engine.state, MeasurementState.PAUSED)

    # EXP increases at t=120s -> Auto-Start resumes measurement!
    engine.add_sample(1010000, 10.10, timestamp=120.0)
    self.assertEqual(engine.state, MeasurementState.RUNNING)
    self.assertEqual(engine.total_gained_exp, 10000)
    self.assertEqual(engine.latest_sample.timestamp, 120.0)

  def test_auto_pause_via_get_metrics_and_custom_settings(self):
    """Verifies that get_metrics(now) also triggers Auto-Pause when no new samples arrive, and respects custom settings."""
    engine = ExpMetricsEngine()
    engine.set_auto_pause(True, 15)
    self.assertTrue(engine.auto_pause_enabled)
    self.assertEqual(engine.auto_pause_seconds, 15)

    engine.add_sample(1000000, 10.0, timestamp=100.0)
    engine.start_measurement(timestamp=105.0)
    # start_measurement refreshes latest_sample.timestamp to 105.0
    self.assertEqual(engine.latest_sample.timestamp, 105.0)

    # At t=119s (14s without gain): still RUNNING
    m1 = engine.get_metrics(now=119.0)
    self.assertEqual(engine.state, MeasurementState.RUNNING)
    self.assertEqual(m1["state"], MeasurementState.RUNNING.value)

    # At t=120s (15s without gain): get_metrics triggers Auto-Pause
    m2 = engine.get_metrics(now=120.0)
    self.assertEqual(engine.state, MeasurementState.PAUSED)
    self.assertEqual(m2["state"], MeasurementState.PAUSED.value)
    self.assertEqual(m2["練功時長"], "00:00:15")

    # When auto_pause_enabled is False, it never auto-pauses
    engine.set_auto_pause(False, 15)
    engine.start_measurement(timestamp=200.0)
    engine.get_metrics(now=300.0)
    self.assertEqual(engine.state, MeasurementState.RUNNING)

  def test_samples_eviction_retains_at_least_one_sample(self):
    """Verifies sliding window eviction removes samples > 1hr old while retaining at least 1 sample."""
    engine = ExpMetricsEngine()
    engine.set_auto_pause(False, 10)
    engine.add_sample(1000000, 10.0, timestamp=0.0)
    engine.start_measurement(timestamp=0.0)

    for t in range(60, 4000, 60):
      exp_val = 1000000 + t * 100
      exp_pct = exp_val / 100000.0
      engine.add_sample(exp_val, exp_pct, timestamp=float(t))

    # Samples older than 3960 - 3660 = 300s should be evicted
    self.assertGreaterEqual(engine.samples[0].timestamp, 3960.0 - 3660.0)
    self.assertLessEqual(len(engine.samples), 62)


if __name__ == "__main__":
  unittest.main()

