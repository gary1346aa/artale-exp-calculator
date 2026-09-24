"""Performance benchmark for the Python EXP recognition engine.

Compliant with Google Python Style Guide.
Matches Google Benchmark's reporting metrics.
"""

import os
import sys
import time
from typing import Dict, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2
import numpy as np
import python_exp_engine


def create_sample_exp_strip(width: int = 350, height: int = 38) -> np.ndarray:
  """Creates a sample 3-channel strip containing '772097[0.32%]'."""
  engine = python_exp_engine.get_engine()
  strip = np.zeros((height, width, 3), dtype=np.uint8)
  text = '772097[0.32%]'
  cur_x = 20
  base_y = 6

  for ch in text:
    tpl = engine.templates[ch]
    w, h, fmap = tpl['w'], tpl['h'], tpl['fmap']
    char_y = base_y if h == 25 else (base_y + 2)
    char_patch = (fmap * 255.0).astype(np.uint8)

    strip[char_y:char_y + h, cur_x:cur_x + w, 0] = char_patch
    strip[char_y:char_y + h, cur_x:cur_x + w, 1] = char_patch
    strip[char_y:char_y + h, cur_x:cur_x + w, 2] = char_patch

    cur_x += 6 if ch == '.' else (w + 2)
  return strip


def benchmark_bilinear_resize(iterations: int = 5000) -> float:
  """Benchmarks cv2.resize on a 350x38 strip to 230x25.

  Returns:
    Mean latency per operation in nanoseconds.
  """
  src = np.full((38, 350), 128, dtype=np.uint8)
  # Warmup
  for _ in range(50):
    _ = cv2.resize(src, (230, 25), interpolation=cv2.INTER_LINEAR)

  t0 = time.perf_counter_ns()
  for _ in range(iterations):
    _ = cv2.resize(src, (230, 25), interpolation=cv2.INTER_LINEAR)
  t1 = time.perf_counter_ns()
  return (t1 - t0) / iterations


def benchmark_match_template_ncc(iterations: int = 2000) -> float:
  """Benchmarks cv2.matchTemplate on digit '8'.

  Returns:
    Mean latency per operation in nanoseconds.
  """
  engine = python_exp_engine.get_engine()
  image = np.full((25, 230), 50.0, dtype=np.float32)
  t8 = engine.templates['8']['fmap']

  # Warmup
  for _ in range(20):
    _ = cv2.matchTemplate(image, t8, cv2.TM_CCOEFF_NORMED)

  t0 = time.perf_counter_ns()
  for _ in range(iterations):
    _ = cv2.matchTemplate(image, t8, cv2.TM_CCOEFF_NORMED)
  t1 = time.perf_counter_ns()
  return (t1 - t0) / iterations


def benchmark_steady_state_crop(iterations: int = 50) -> float:
  """Benchmarks full Python parse_crop on a synthesized strip.

  Returns:
    Mean latency per operation in nanoseconds.
  """
  engine = python_exp_engine.get_engine()
  strip = create_sample_exp_strip()

  # Warmup
  for _ in range(5):
    _ = engine.parse_crop(strip)

  t0 = time.perf_counter_ns()
  for _ in range(iterations):
    _ = engine.parse_crop(strip)
  t1 = time.perf_counter_ns()
  return (t1 - t0) / iterations


def main() -> None:
  print('Running Python EXP Engine Benchmarks...')
  print('-' * 60)
  print(f'{"Benchmark":<30} {"Time (ns)":>15} {"Time (ms)":>12}')
  print('-' * 60)

  t_resize = benchmark_bilinear_resize()
  print(f'{"BM_BilinearResize (Python)":<30} {t_resize:>15.0f} {t_resize / 1e6:>12.3f}')

  t_ncc = benchmark_match_template_ncc()
  print(f'{"BM_MatchTemplateNcc (Python)":<30} {t_ncc:>15.0f} {t_ncc / 1e6:>12.3f}')

  t_parse = benchmark_steady_state_crop()
  print(f'{"BM_SteadyStateParseCrop (Python)":<30} {t_parse:>15.0f} {t_parse / 1e6:>12.3f}')
  print('-' * 60)


if __name__ == '__main__':
  main()
