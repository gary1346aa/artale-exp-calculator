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


if __name__ == '__main__':
  unittest.main()
