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


if __name__ == "__main__":
  unittest.main()
