"""Artale EXP Calculator - Reference Pure Python Recognition Engine.

Provides the reference template-matching OCR engine used for verification,
benchmarking, and parity testing against the native C++ SIMD engine.
Complies with the Google Python Style Guide.
"""

import json
import os
import time
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

import config

# Load pristine 25px / 21px prototypes from package data
PROTOS_PATH = config.get_resource_path(
    os.path.join("data", "pristine_font_protos.json")
)


class PythonExpEngine:
  """Reference template-matching engine implemented in pure Python/NumPy."""

  def __init__(self, protos_path: str = PROTOS_PATH) -> None:
    """Initializes templates from JSON font prototypes."""
    with open(protos_path, "r", encoding="utf-8") as f:
      data = json.load(f)

    self.templates: Dict[str, Dict[str, Any]] = {}
    for ch, v in data.items():
      self.templates[ch] = {
          "fmap": np.array(v["float_map"], dtype=np.float32),
          "w": v["width"],
          "h": v["height"],
      }
    self.t_bracket = self.templates["["]["fmap"]

  def parse_crop(
      self, crop_bgr: np.ndarray
  ) -> Optional[Tuple[int, float, str, float, List[Tuple[int, str, float]]]]:
    """Parses an EXP crop (height ~20 to 50 px, containing EXP and [XX.XX%]).

    Args:
      crop_bgr: BGR image crop containing the EXP gauge and text area.

    Returns:
      A tuple of (exp_value, percent_value, raw_string, elapsed_ms, glyph_list)
      if successfully parsed; otherwise None.
    """
    t0 = time.perf_counter()
    gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
    height, width = gray.shape

    # 1 & 2. Robust multi-scale search using bracket and digit '8'
    best_combo = -1.0
    best_cs = 1.0
    best_by = 0
    t8 = self.templates["8"]["fmap"]

    expected_s = 38.0 / float(height) if height > 0 else 1.0
    s_min = max(0.35, expected_s * 0.65)
    s_max = min(2.50, expected_s * 1.45)
    scales = np.linspace(s_min, s_max, 18)

    for cs in scales:
      wn = int(round(width * cs))
      hn = int(round(height * cs))
      if hn < 25 or wn < 30:
        continue
      work = cv2.resize(gray, (wn, hn), interpolation=cv2.INTER_LINEAR)
      res_b = cv2.matchTemplate(
          work.astype(np.float32), self.t_bracket, cv2.TM_CCOEFF_NORMED
      )
      res_8 = cv2.matchTemplate(
          work.astype(np.float32), t8, cv2.TM_CCOEFF_NORMED
      )
      vb = float(np.max(res_b))
      v8 = float(np.max(res_8))
      combo = vb + v8
      if combo > best_combo:
        best_combo = combo
        best_cs = cs
        best_by = int(np.unravel_index(np.argmax(res_b), res_b.shape)[0])

    if best_combo < 1.10:
      return None

    # Build work image at the winning scale
    wn = int(round(width * best_cs))
    hn = int(round(height * best_cs))
    work_gray = cv2.resize(gray, (wn, hn), interpolation=cv2.INTER_LINEAR)
    strip = work_gray[best_by : best_by + 25, :]
    strip_w = strip.shape[1]

    # 3. Sliding-window NCC responses
    responses: Dict[str, np.ndarray] = {}
    for ch, t in self.templates.items():
      if t["h"] == 25:
        sub_y = strip[:25, :]
        responses[ch] = cv2.matchTemplate(
            sub_y.astype(np.float32), t["fmap"], cv2.TM_CCOEFF_NORMED
        )[0]
      else:
        # Vertical jitter of +/-1px to maximize alignment across scales
        r_list = [
            cv2.matchTemplate(
                strip[1 + dy : 22 + dy, :].astype(np.float32),
                t["fmap"],
                cv2.TM_CCOEFF_NORMED,
            )[0]
            for dy in [-1, 0, 1]
        ]
        responses[ch] = np.maximum.reduce(r_list)

    # 4. Grammar-aware dynamic programming beam search across pixel columns x
    # States:
    # 0: EXP digits (0-9) or '['
    # 1: inside brackets (0-9, '.') or '%'
    # 2: after '%', expecting ']'
    # 3: completed string
    dp: Dict[
        Tuple[int, int],
        Tuple[
            float,
            Optional[int],
            Optional[int],
            Optional[str],
            float,
        ],
    ] = {(0, 0): (0.0, None, None, None, 0.0)}

    for x in range(strip_w):
      for st in [0, 1, 2, 3]:
        if (x, st) not in dp:
          continue
        score, _, _, _, _ = dp[(x, st)]

        # Skip blank / background pixel
        if (x + 1, st) not in dp or dp[(x + 1, st)][0] < score:
          dp[(x + 1, st)] = (score, x, st, None, 0.0)

        # Allowed transitions based on grammar
        if st == 0:
          allowed = [(ch, 0) for ch in "0123456789"] + [("[", 1)]
        elif st == 1:
          allowed = [(ch, 1) for ch in "0123456789."] + [("%", 2)]
        elif st == 2:
          allowed = [("]", 3)]
        else:
          continue

        for ch, next_st in allowed:
          t = self.templates[ch]
          w = t["w"]
          min_ncc = 0.65 if ch in "1]" else 0.55
          min_adv = 4 if ch == "." else (6 if ch in "[]" else max(w, 11))
          if x + w <= strip_w and x < len(responses[ch]):
            ncc = float(responses[ch][x])
            if ncc >= min_ncc:
              # Width-weighted excess correlation with character penalty
              gain = ((ncc - 0.45) ** 2) * max(w, 11) - 0.20
              cand_score = score + gain
              next_key = (x + min_adv, next_st)
              if next_key not in dp or dp[next_key][0] < cand_score:
                dp[next_key] = (cand_score, x, st, ch, ncc)

    # Select best terminal state in state 3 (completed grammar)
    best_k = None
    best_s = -1.0
    for (x, st), val in dp.items():
      if st == 3 and val[0] > best_s:
        best_s = val[0]
        best_k = (x, st)

    # Require completed grammar (state 3 reached with closing bracket)
    if best_k is None:
      return None

    curr = best_k
    result_chars: List[Tuple[int, str, float]] = []
    while curr is not None and dp[curr][1] is not None:
      _, px, pst, ch, ncc = dp[curr]
      if ch is not None and px is not None:
        result_chars.append((px, ch, ncc))
      if px is not None and pst is not None:
        curr = (px, pst)
      else:
        break

    result_chars.reverse()
    raw_str = "".join(r[1] for r in result_chars)
    t1 = time.perf_counter()
    dt_ms = (t1 - t0) * 1000.0

    # Parse EXP value and percentage
    if "[" in raw_str:
      parts = raw_str.split("[", 1)
      exp_digits = "".join(c for c in parts[0] if c.isdigit())
      pct_part = parts[1].split("]")[0].rstrip("%")
      try:
        exp_val = int(exp_digits) if exp_digits else 0
      except ValueError:
        exp_val = 0
      try:
        pct_val = float(pct_part) if pct_part else 0.0
      except ValueError:
        pct_val = 0.0
      return exp_val, pct_val, raw_str, dt_ms, result_chars

    return None


_engine_instance: Optional[PythonExpEngine] = None


def get_engine() -> PythonExpEngine:
  """Returns a singleton instance of PythonExpEngine."""
  global _engine_instance
  if _engine_instance is None:
    _engine_instance = PythonExpEngine()
  return _engine_instance
