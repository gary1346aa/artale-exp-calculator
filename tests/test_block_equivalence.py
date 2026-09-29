"""Unit tests validating core C++ modules against reference Python/OpenCV implementations.

This test suite isolates each individual algorithmic building block:
1. Grayscale Conversion: Test_ExtractGraySubRect vs cv2.cvtColor
2. Bilinear Interpolation: Test_ResizeGray vs cv2.resize(..., INTER_LINEAR)
3. Normalized Cross-Correlation: Test_MatchTemplateNcc vs cv2.matchTemplate(..., TM_CCOEFF_NORMED)
4. Multi-Scale Dual-Template Search: Bracket + Digit '8' scale selection
5. Grammar-Constrained DP Decoder: Dynamic programming beam search

Compliant with Google Python Style Guide.
"""

import ctypes
import os
import sys
import unittest
import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import python_engine
from scripts.run_equivalence_suite import CppExpResult, load_cpp_library


class BlockEquivalenceTest(unittest.TestCase):
  """Validates each individual computational block of C++ engine against OpenCV/Python."""

  @classmethod
  def setUpClass(cls) -> None:
    cls.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cls.cpp_lib = load_cpp_library(cls.base_dir)
    cls.py_engine = python_engine.get_engine()

    # Configure ctypes argtypes for diagnostic functions
    cls.cpp_lib.Test_ExtractGraySubRect.argtypes = [
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_char_p,
    ]
    cls.cpp_lib.Test_ExtractGraySubRect.restype = None

    cls.cpp_lib.Test_ResizeGray.argtypes = [
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
    ]
    cls.cpp_lib.Test_ResizeGray.restype = None

    cls.cpp_lib.Test_MatchTemplateNcc.argtypes = [
        ctypes.POINTER(ctypes.c_float),
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_char,
        ctypes.POINTER(ctypes.c_float),
    ]
    cls.cpp_lib.Test_MatchTemplateNcc.restype = ctypes.c_int

  def test_extract_gray_exact_match_opencv(self) -> None:
    """Tests that C++ BGR2GRAY matches OpenCV cv2.cvtColor."""
    # Test 1: Synthetic color gradient ramp
    h, w = 120, 200
    ramp = np.zeros((h, w, 3), dtype=np.uint8)
    for y in range(h):
      for x in range(w):
        ramp[y, x] = [x % 256, (y * 2) % 256, (x + y) % 256]

    cv_gray = cv2.cvtColor(ramp, cv2.COLOR_BGR2GRAY)
    cpp_gray = np.zeros((h, w), dtype=np.uint8)
    self.cpp_lib.Test_ExtractGraySubRect(
        ramp.tobytes(), w, h, w * 3, 3, 0, 0, w, h, cpp_gray.ctypes.data_as(ctypes.c_char_p)
    )

    diff = np.abs(cv_gray.astype(int) - cpp_gray.astype(int))
    max_diff = int(np.max(diff))
    mismatches = int(np.count_nonzero(diff))
    self.assertEqual(max_diff, 0, f'Grayscale mismatch on synthetic ramp: max_diff={max_diff}')
    self.assertEqual(mismatches, 0, f'Grayscale mismatches: {mismatches} pixels')

    # Test 2: Authentic crop image from dataset
    crop_path = os.path.join(self.base_dir, 'debug_crops', 'crop_3840x2160.png')
    if os.path.exists(crop_path):
      img = cv2.imread(crop_path)
      ih, iw = img.shape[:2]
      cv_img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
      cpp_img_gray = np.zeros((ih, iw), dtype=np.uint8)
      self.cpp_lib.Test_ExtractGraySubRect(
          img.tobytes(), iw, ih, iw * 3, 3, 0, 0, iw, ih,
          cpp_img_gray.ctypes.data_as(ctypes.c_char_p)
      )
      diff = np.abs(cv_img_gray.astype(int) - cpp_img_gray.astype(int))
      self.assertEqual(int(np.max(diff)), 0)

  def test_bilinear_resize_vs_opencv(self) -> None:
    """Tests that C++ scalar bilinear resize correlates > 0.999 with OpenCV INTER_LINEAR."""
    # Test across multiple resizing geometries
    scales = [(200, 38, 300, 25), (350, 14, 750, 30), (541, 57, 887, 25)]
    np.random.seed(42)

    for sw, sh, dw, dh in scales:
      src = np.random.randint(0, 256, (sh, sw), dtype=np.uint8)
      cv_resized = cv2.resize(src, (dw, dh), interpolation=cv2.INTER_LINEAR)
      cpp_resized = np.zeros((dh, dw), dtype=np.uint8)

      self.cpp_lib.Test_ResizeGray(
          src.tobytes(), sw, sh, sw,
          cpp_resized.ctypes.data_as(ctypes.c_char_p), dw, dh, dw
      )

      diff = np.abs(cv_resized.astype(int) - cpp_resized.astype(int))
      max_diff = int(np.max(diff))
      mismatches = int(np.count_nonzero(diff))

      self.assertEqual(max_diff, 0, f'Resize ({sw}x{sh}->{dw}x{dh}) max_diff != 0: {max_diff}')
      self.assertEqual(mismatches, 0, f'Resize ({sw}x{sh}->{dw}x{dh}) mismatches != 0: {mismatches}')

  @staticmethod
  def _render_canonical_bgr_strip(
      engine: python_engine.PythonExpEngine,
      text: str,
      width: int = 420,
      height: int = 38,
  ) -> np.ndarray:
    """Renders a 3-channel BGR strip at canonical 38px height."""
    strip = np.zeros((height, width, 3), dtype=np.uint8)
    cur_x = 20
    base_y = 6
    for ch in text:
      tpl = engine.templates[ch]
      w, h, fmap = tpl['w'], tpl['h'], tpl['fmap']
      cy = base_y if h == 25 else base_y + 2
      patch = np.round(fmap * 255.0).astype(np.uint8)
      strip[cy : cy + h, cur_x : cur_x + w, 0] = patch
      strip[cy : cy + h, cur_x : cur_x + w, 1] = patch
      strip[cy : cy + h, cur_x : cur_x + w, 2] = patch
      cur_x += 6 if ch == '.' else (8 if ch in '[]' else max(w, 11) + 2)
    return strip

  def test_bilinear_resize_authentic_crop_exact_match(self) -> None:
    """Tests that C++ ResizeGray matches cv2.resize across game strip scales."""
    crop_path = os.path.join(self.base_dir, 'debug_crops', 'crop_3840x2160.png')
    if os.path.exists(crop_path):
      crops = [cv2.imread(crop_path, cv2.IMREAD_GRAYSCALE)]
    else:
      bgr = self._render_canonical_bgr_strip(self.py_engine, '444444442[44.44%]')
      gray_38 = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
      crops = [
          cv2.resize(gray_38, (210, 19), interpolation=cv2.INTER_LINEAR),
          gray_38,
          cv2.resize(gray_38, (630, 57), interpolation=cv2.INTER_LINEAR),
      ]

    for img in crops:
      sh, sw = img.shape
      dw = int(round(sw * (38.0 / sh)))
      dh = int(round(sh * (38.0 / sh)))

      cv_resized = cv2.resize(img, (dw, dh), interpolation=cv2.INTER_LINEAR)
      cpp_resized = np.zeros((dh, dw), dtype=np.uint8)

      self.cpp_lib.Test_ResizeGray(
          img.tobytes(), sw, sh, sw,
          cpp_resized.ctypes.data_as(ctypes.c_char_p), dw, dh, dw
      )

      diff = np.abs(cv_resized.astype(int) - cpp_resized.astype(int))
      mismatches = int(np.count_nonzero(diff))
      max_diff = int(np.max(diff))
      self.assertEqual(
          mismatches, 0,
          f'Crop ({sw}x{sh}->{dw}x{dh}) resize had {mismatches} mismatches vs cv2.resize, max_diff={max_diff}'
      )

  def test_match_template_ncc_vs_opencv(self) -> None:
    """Tests that C++ MatchTemplateNcc matches cv2.matchTemplate within 1e-4 across all 15 chars."""
    img_w = 200
    img_h = 25
    test_chars = sorted(self.py_engine.templates.keys())

    # Synthesize realistic background with characters
    np.random.seed(123)
    synth_img = np.random.uniform(20.0, 80.0, (img_h, img_w)).astype(np.float32)

    for ch in test_chars:
      t_info = self.py_engine.templates[ch]
      tpl = t_info['fmap']
      tw = t_info['w']
      th = t_info['h']
      out_w = img_w - tw + 1
      out_h = img_h - th + 1

      cv_ncc = cv2.matchTemplate(synth_img, tpl, cv2.TM_CCOEFF_NORMED)

      cpp_resp = np.zeros(out_w * out_h, dtype=np.float32)
      ret = self.cpp_lib.Test_MatchTemplateNcc(
          synth_img.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
          img_w, img_h, img_w,
          ch.encode('ascii'),
          cpp_resp.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
      )
      self.assertEqual(ret, 0, f'Test_MatchTemplateNcc failed for char {ch}')

      cpp_ncc = cpp_resp.reshape((out_h, out_w))
      diff = np.abs(cv_ncc - cpp_ncc)
      max_diff = float(np.max(diff))
      self.assertLess(
          max_diff, 1e-4,
          f'Template NCC mismatch for \'{ch}\': max_diff={max_diff:.6e}'
      )

  def test_grammar_dp_decoder_complete_equivalence(self) -> None:
    """Tests that C++ and Python engines decode identical EXP strings across scales and strings."""
    test_strings = [
        '772097[0.32%]',
        '772097[0.3%]',
        '444444442[44.44%]',
        '242424242[24.24%]',
        '19896792[41.90%]',
        '19896792[41.9%]',
        '100[0.00%]',
        '100[0.0%]',
        '999999999[99.99%]',
    ]
    target_heights = [14, 16, 19, 25, 38, 57]

    for text in test_strings:
      canonical = self._render_canonical_bgr_strip(self.py_engine, text)
      ch_orig, cw_orig = canonical.shape[:2]
      for target_h in target_heights:
        target_w = int(round(cw_orig * (target_h / float(ch_orig))))
        img = cv2.resize(
            canonical, (target_w, target_h), interpolation=cv2.INTER_LINEAR
        )
        h, w = img.shape[:2]

        py_res = self.py_engine.parse_crop(img)
        self.assertIsNotNone(py_res, f'Python failed on {text} at h={target_h}')
        py_val, py_pct, py_str, _, _ = py_res

        cpp_res = CppExpResult()
        ret = self.cpp_lib.ParseExpFromBuffer(
            img.tobytes(), w, h, w * 3, 3, ctypes.byref(cpp_res)
        )
        self.assertEqual(ret, 0)
        self.assertEqual(cpp_res.success, 1, f'C++ failed on {text} at h={target_h}')

        cpp_str = cpp_res.exp_string.decode('utf-8')
        self.assertEqual(cpp_str, py_str)
        self.assertEqual(cpp_str, text)
        self.assertEqual(cpp_res.exp_value, py_val)
        self.assertAlmostEqual(cpp_res.exp_percent, py_pct, places=4)


if __name__ == '__main__':
  unittest.main()
