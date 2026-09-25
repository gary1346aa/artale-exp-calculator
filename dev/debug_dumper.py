"""Debug image exporter for visual inspection of OCR and template matching.

Complies with the Google Python Style Guide.
Gated strictly behind config.IS_DEV; lazy-imports cv2 on demand.
"""

import os
from typing import Optional, Tuple
import numpy as np

import config
from core.engine import ParsedFrame


def save_crop_debug(
    bgr_img: Optional[np.ndarray],
    parsed: Optional[ParsedFrame],
    output_dir: Optional[str] = None,
) -> Optional[Tuple[str, str]]:
  """Saves cropped text box and annotated bounding box strip for debugging.

  Only executes if config.IS_DEV is True. Safely handles missing cv2.

  Args:
    bgr_img: Full raw BGR/BGRA numpy image buffer.
    parsed: ParsedFrame containing detected crop_box and logo_box coordinates.
    output_dir: Target directory (defaults to config.DEBUG_OUTPUT_DIR).

  Returns:
    Tuple of (crop_file_path, annotated_strip_file_path), or None.
  """
  if not config.IS_DEV or bgr_img is None or parsed is None:
    return None

  try:
    import cv2
  except ImportError:
    return None

  out_dir = output_dir if output_dir is not None else config.DEBUG_OUTPUT_DIR
  os.makedirs(out_dir, exist_ok=True)

  h, w = bgr_img.shape[:2]
  cx, cy, cw, ch = parsed.crop_box
  lx, ly, lw, lh = parsed.logo_box

  # 1. Save text crop
  crop_file = os.path.join(out_dir, f"crop_{w}x{h}.png")
  if cw > 0 and ch > 0 and cy + ch <= h and cx + cw <= w:
    crop_img = bgr_img[cy : cy + ch, cx : cx + cw]
    cv2.imwrite(crop_file, crop_img)

  # 2. Save raw bottom strip
  strip_h = min(h, max(80, int(h * 0.15)))
  strip_y = max(0, h - strip_h)
  raw_strip = bgr_img[strip_y : strip_y + strip_h, :].copy()
  raw_strip_file = os.path.join(out_dir, f"raw_strip_{w}x{h}.png")
  cv2.imwrite(raw_strip_file, raw_strip)

  # 3. Save raw logo crop
  raw_logo_file = os.path.join(out_dir, f"raw_logo_{w}x{h}.png")
  if lw > 0 and lh > 0 and ly + lh <= h and lx + lw <= w:
    cv2.imwrite(raw_logo_file, bgr_img[ly : ly + lh, lx : lx + lw])

  # 4. Save annotated strip with colored bounding boxes
  strip_file = os.path.join(out_dir, f"annotated_strip_{w}x{h}.png")
  annotated = raw_strip.copy()

  rel_ly = ly - strip_y
  cv2.rectangle(
      annotated, (lx, rel_ly), (lx + lw, rel_ly + lh), (0, 0, 255), 1
  )
  cv2.putText(
      annotated,
      "EXP Logo",
      (lx, max(10, rel_ly - 3)),
      cv2.FONT_HERSHEY_SIMPLEX,
      0.35,
      (0, 0, 255),
      1,
  )

  rel_cy = cy - strip_y
  cv2.rectangle(
      annotated, (cx, rel_cy), (cx + cw, rel_cy + ch), (0, 255, 0), 1
  )
  cv2.putText(
      annotated,
      f"Text: {parsed.raw_string}",
      (cx, max(10, rel_cy - 3)),
      cv2.FONT_HERSHEY_SIMPLEX,
      0.35,
      (0, 255, 0),
      1,
  )

  cv2.imwrite(strip_file, annotated)
  return crop_file, strip_file
