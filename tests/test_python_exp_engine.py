"""Unit tests for the Python EXP recognition engine.

Compliant with Google Python Style Guide.
"""

import os
import sys
import unittest
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import python_engine


class PythonExpEngineTest(unittest.TestCase):
  """Validates the behavior and accuracy of the Python reference engine."""

  def setUp(self) -> None:
    super().setUp()
    self.engine = python_engine.get_engine()

  def test_templates_loaded(self) -> None:
    """Verifies that all 15 pristine character prototypes are loaded."""
    expected_chars = set('0123456789.[]%/')
    loaded_chars = set(self.engine.templates.keys())
    self.assertTrue(expected_chars.issubset(loaded_chars))

  def test_rejects_empty_or_small_crop(self) -> None:
    """Verifies that tiny or blank crops return None."""
    tiny_crop = np.zeros((10, 10, 3), dtype=np.uint8)
    res = self.engine.parse_crop(tiny_crop)
    self.assertIsNone(res)

  def test_synthesized_exp_strip(self) -> None:
    """Verifies recognition on a synthesized canonical strip."""
    text = "772097[0.32%]"
    strip_h = 38
    strip_w = 350
    strip = np.zeros((strip_h, strip_w, 3), dtype=np.uint8)

    cur_x = 20
    base_y = 6

    for ch in text:
      tpl = self.engine.templates[ch]
      w = tpl['w']
      h = tpl['h']
      fmap = tpl['fmap']
      char_y = base_y if h == 25 else (base_y + 2)
      char_patch = (fmap * 255.0).astype(np.uint8)

      strip[char_y:char_y + h, cur_x:cur_x + w, 0] = char_patch
      strip[char_y:char_y + h, cur_x:cur_x + w, 1] = char_patch
      strip[char_y:char_y + h, cur_x:cur_x + w, 2] = char_patch

      cur_x += 6 if ch == '.' else (w + 2)

    res = self.engine.parse_crop(strip)
    self.assertIsNotNone(res)
    exp_val, pct_val, raw_str, _, _ = res
    self.assertEqual(exp_val, 772097)
    self.assertAlmostEqual(pct_val, 0.32, places=3)
    self.assertEqual(raw_str, "772097[0.32%]")

  def test_bgra_zero_copy_and_static_skip_equivalence(self) -> None:
    """Verifies 4-channel BGRA zero-copy buffer parsing and static-frame cold skip."""
    from core import engine as main_engine

    text = "772097[0.32%]"
    strip_h = 38
    strip_w = 350
    strip_bgr = np.zeros((strip_h, strip_w, 3), dtype=np.uint8)
    strip_bgra = np.zeros((strip_h, strip_w, 4), dtype=np.uint8)
    strip_bgra[:, :, 3] = 255

    cur_x = 20
    base_y = 6
    for ch in text:
      tpl = self.engine.templates[ch]
      w = tpl['w']
      h = tpl['h']
      fmap = tpl['fmap']
      char_y = base_y if h == 25 else (base_y + 2)
      char_patch = (fmap * 255.0).astype(np.uint8)
      for c in range(3):
        strip_bgr[char_y:char_y + h, cur_x:cur_x + w, c] = char_patch
        strip_bgra[char_y:char_y + h, cur_x:cur_x + w, c] = char_patch
      cur_x += 6 if ch == '.' else (w + 2)

    res_bgr = main_engine.parse_frame(strip_bgr)
    res_bgra = main_engine.parse_frame(strip_bgra)
    self.assertIsNotNone(res_bgr)
    self.assertIsNotNone(res_bgra)
    self.assertEqual(res_bgr.exp_value, res_bgra.exp_value)
    self.assertAlmostEqual(res_bgr.exp_percent, res_bgra.exp_percent, places=3)
    self.assertEqual(res_bgr.raw_string, res_bgra.raw_string)

  def _render_strip(self, text: str, gap_after_idx: int = -1, extra_gap: int = 0) -> np.ndarray:
    """Helper to synthesize a canonical 38px height BGR strip for a given string."""
    strip = np.zeros((38, 420, 3), dtype=np.uint8)
    cur_x = 20
    base_y = 6
    for idx, ch in enumerate(text):
      tpl = self.engine.templates[ch]
      w, h = tpl['w'], tpl['h']
      char_y = base_y if h == 25 else (base_y + 2)
      char_patch = np.round(tpl['fmap'] * 255.0).astype(np.uint8)
      for c in range(3):
        strip[char_y:char_y + h, cur_x:cur_x + w, c] = char_patch
      cur_x += 6 if ch == '.' else (w + 2)
      if idx == gap_after_idx:
        cur_x += extra_gap
    return strip

  def test_low_res_high_ratio_without_digit_8_cpp_and_python(self) -> None:
    """Verifies 1920x720 (19px crop height) recognition when EXP has no digit '8'."""
    import cv2
    from core import engine as main_engine

    text = "444444442[44.44%]"
    canonical = self._render_strip(text)
    # Downscale to 19px height (matching 1920x720 HUD crop height)
    low_res_crop = cv2.resize(canonical, (210, 19), interpolation=cv2.INTER_LINEAR)

    py_res = self.engine.parse_crop(low_res_crop)
    self.assertIsNotNone(py_res)
    self.assertEqual(py_res[0], 444444442)
    self.assertAlmostEqual(py_res[1], 44.44, places=2)
    self.assertEqual(py_res[2], text)

    cpp_res = main_engine.parse_frame(low_res_crop)
    self.assertIsNotNone(cpp_res)
    self.assertEqual(cpp_res.exp_value, 444444442)
    self.assertAlmostEqual(cpp_res.exp_percent, 44.44, places=2)
    self.assertEqual(cpp_res.raw_string, text)

  def test_rejects_malformed_grammar_and_occluded_gaps(self) -> None:
    """Verifies 1-2 decimal digits are accepted and malformed percentage strings/occluded gaps are rejected."""
    from core import engine as main_engine

    # 1-decimal-digit percentage string should be accepted by both Python and C++
    one_dec_strip = self._render_strip("12345[84.9%]")
    py_one = self.engine.parse_crop(one_dec_strip)
    self.assertIsNotNone(py_one)
    self.assertEqual(py_one[0], 12345)
    self.assertAlmostEqual(py_one[1], 84.9, places=2)
    self.assertEqual(py_one[2], "12345[84.9%]")

    cpp_one = main_engine.parse_frame(one_dec_strip)
    self.assertIsNotNone(cpp_one)
    self.assertEqual(cpp_one.exp_value, 12345)
    self.assertAlmostEqual(cpp_one.exp_percent, 84.9, places=2)
    self.assertEqual(cpp_one.raw_string, "12345[84.9%]")

    for malformed in ["6[%]", "[84.99%]", "12345[84%]", "12345[84.999%]", "12345[.99%]"]:
      strip = self._render_strip(malformed)
      self.assertIsNone(self.engine.parse_crop(strip), f"Should reject {malformed}")
      self.assertIsNone(main_engine.parse_frame(strip), f"C++ should reject {malformed}")

    # Synthesize a valid string but with a 50px occluded blank gap after the first digit '6'
    gapped_strip = self._render_strip("6[0.00%]", gap_after_idx=0, extra_gap=50)
    self.assertIsNone(self.engine.parse_crop(gapped_strip))
    self.assertIsNone(main_engine.parse_frame(gapped_strip))


if __name__ == '__main__':
  unittest.main()
