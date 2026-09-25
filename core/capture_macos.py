"""macOS window and display capture utilizing CoreGraphics via ctypes.

Complies with the Google Python Style Guide.
Zero external package dependencies; uses native macOS frameworks.
"""

import ctypes
import sys
from typing import List, Optional, Tuple
import cv2
import numpy as np


class CGPoint(ctypes.Structure):
  _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


class CGSize(ctypes.Structure):
  _fields_ = [("width", ctypes.c_double), ("height", ctypes.c_double)]


class CGRect(ctypes.Structure):
  _fields_ = [("origin", CGPoint), ("size", CGSize)]


def check_and_request_macos_screen_recording_permission() -> bool:
  """Checks and prompts for Screen Recording permission on macOS.

  Returns:
    True if permission is currently granted, False if missing.
  """
  if sys.platform != "darwin":
    return True
  try:
    cg = ctypes.cdll.LoadLibrary(
        "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"
    )
    if hasattr(cg, "CGPreflightScreenCaptureAccess"):
      cg.CGPreflightScreenCaptureAccess.restype = ctypes.c_bool
      has_perm = cg.CGPreflightScreenCaptureAccess()
      if not has_perm and hasattr(cg, "CGRequestScreenCaptureAccess"):
        cg.CGRequestScreenCaptureAccess.restype = ctypes.c_bool
        cg.CGRequestScreenCaptureAccess()
      return has_perm
  except Exception:
    pass
  return True


def find_macos_window_by_title(target_title: str) -> Optional[int]:
  """Finds the window ID (kCGWindowNumber) matching target_title on macOS.

  Matches both window titles and application owner names (e.g. 'MapleStory Worlds'
  and 'MapleStory Worlds-Artale'). Prioritizes the main game window by area and layer.

  Args:
    target_title: Substring of the window owner or window title.

  Returns:
    Window ID integer if found, otherwise None.
  """
  if not target_title or sys.platform != "darwin":
    return None

  try:
    cg = ctypes.cdll.LoadLibrary(
        "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"
    )
    cf = ctypes.cdll.LoadLibrary(
        "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
    )

    cg.CGWindowListCopyWindowInfo.restype = ctypes.c_void_p
    cg.CGWindowListCopyWindowInfo.argtypes = [ctypes.c_uint32, ctypes.c_uint32]

    cf.CFArrayGetCount.restype = ctypes.c_long
    cf.CFArrayGetCount.argtypes = [ctypes.c_void_p]
    cf.CFArrayGetValueAtIndex.restype = ctypes.c_void_p
    cf.CFArrayGetValueAtIndex.argtypes = [ctypes.c_void_p, ctypes.c_long]

    cf.CFDictionaryGetValue.restype = ctypes.c_void_p
    cf.CFDictionaryGetValue.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

    cf.CFStringCreateWithCString.restype = ctypes.c_void_p
    cf.CFStringCreateWithCString.argtypes = [
        ctypes.c_void_p,
        ctypes.c_char_p,
        ctypes.c_uint32,
    ]

    cf.CFStringGetCString.restype = ctypes.c_bool
    cf.CFStringGetCString.argtypes = [
        ctypes.c_void_p,
        ctypes.c_char_p,
        ctypes.c_long,
        ctypes.c_uint32,
    ]

    cf.CFNumberGetValue.restype = ctypes.c_bool
    cf.CFNumberGetValue.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
    ]

    cg.CGRectMakeWithDictionaryRepresentation.restype = ctypes.c_bool
    cg.CGRectMakeWithDictionaryRepresentation.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(CGRect),
    ]

    cf.CFRelease.restype = None
    cf.CFRelease.argtypes = [ctypes.c_void_p]

    kCFStringEncodingUTF8 = 0x08000100
    kCGWindowListExcludeDesktopElements = 16

    key_owner = cf.CFStringCreateWithCString(
        None, b"kCGWindowOwnerName", kCFStringEncodingUTF8
    )
    key_name = cf.CFStringCreateWithCString(
        None, b"kCGWindowName", kCFStringEncodingUTF8
    )
    key_num = cf.CFStringCreateWithCString(
        None, b"kCGWindowNumber", kCFStringEncodingUTF8
    )
    key_bounds = cf.CFStringCreateWithCString(
        None, b"kCGWindowBounds", kCFStringEncodingUTF8
    )
    key_layer = cf.CFStringCreateWithCString(
        None, b"kCGWindowLayer", kCFStringEncodingUTF8
    )

    target_lower = target_title.lower()
    buf = ctypes.create_string_buffer(512)
    candidates: List[Tuple[bool, float, int]] = []

    # Query window list (try non-desktop first, fallback to all windows)
    for opt in [kCGWindowListExcludeDesktopElements, 0]:
      win_list = cg.CGWindowListCopyWindowInfo(opt, 0)
      if not win_list:
        continue

      count = cf.CFArrayGetCount(win_list)
      for i in range(count):
        d = cf.CFArrayGetValueAtIndex(win_list, i)
        owner_str = ""
        name_str = ""

        owner_val = cf.CFDictionaryGetValue(d, key_owner)
        if owner_val and cf.CFStringGetCString(
            owner_val, buf, 512, kCFStringEncodingUTF8
        ):
          owner_str = buf.value.decode("utf-8", errors="replace").strip()

        name_val = cf.CFDictionaryGetValue(d, key_name)
        if name_val and cf.CFStringGetCString(
            name_val, buf, 512, kCFStringEncodingUTF8
        ):
          name_str = buf.value.decode("utf-8", errors="replace").strip()

        owner_lower = owner_str.lower()
        name_lower = name_str.lower()
        combined = f"{owner_str} {name_str}".lower()

        # Robust substring matching across owner name, window title, and game aliases
        matches = False
        if (
            target_lower in owner_lower
            or target_lower in name_lower
            or target_lower in combined
        ):
          matches = True
        elif name_lower and (name_lower in target_lower or target_lower in name_lower):
          matches = True
        elif owner_lower and (owner_lower in target_lower or target_lower in owner_lower):
          matches = True
        elif "maplestory" in owner_lower or "maplestory" in name_lower or "maplestory" in combined:
          matches = True
        elif "artale" in owner_lower or "artale" in name_lower or "artale" in combined:
          matches = True

        if matches:
          num_val = cf.CFDictionaryGetValue(d, key_num)
          if num_val:
            wid = ctypes.c_uint32()
            kCFNumberSInt32Type = 3
            if cf.CFNumberGetValue(
                num_val, kCFNumberSInt32Type, ctypes.byref(wid)
            ):
              area = 1.0
              bounds_val = cf.CFDictionaryGetValue(d, key_bounds)
              if bounds_val:
                r = CGRect()
                if cg.CGRectMakeWithDictionaryRepresentation(
                    bounds_val, ctypes.byref(r)
                ):
                  area = r.size.width * r.size.height

              layer = 0
              layer_val = cf.CFDictionaryGetValue(d, key_layer)
              if layer_val:
                layer_int = ctypes.c_int32()
                if cf.CFNumberGetValue(
                    layer_val, kCFNumberSInt32Type, ctypes.byref(layer_int)
                ):
                  layer = layer_int.value

              candidates.append((layer == 0, area, wid.value))

      cf.CFRelease(win_list)
      if candidates:
        break

    cf.CFRelease(key_owner)
    cf.CFRelease(key_name)
    cf.CFRelease(key_num)
    cf.CFRelease(key_bounds)
    cf.CFRelease(key_layer)

    if not candidates:
      return None

    # Prioritize layer 0 (standard windows) and largest window area (actual game canvas)
    candidates.sort(key=lambda c: (c[0], c[1]), reverse=True)
    return candidates[0][2]
  except Exception:
    return None


def get_macos_visible_windows() -> List[Tuple[int, str]]:
  """Enumerates visible macOS windows for window pickers and debuggers."""
  if sys.platform != "darwin":
    return []

  results: List[Tuple[int, str]] = []
  try:
    cg = ctypes.cdll.LoadLibrary(
        "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"
    )
    cf = ctypes.cdll.LoadLibrary(
        "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
    )

    cg.CGWindowListCopyWindowInfo.restype = ctypes.c_void_p
    cg.CGWindowListCopyWindowInfo.argtypes = [ctypes.c_uint32, ctypes.c_uint32]

    cf.CFArrayGetCount.restype = ctypes.c_long
    cf.CFArrayGetCount.argtypes = [ctypes.c_void_p]
    cf.CFArrayGetValueAtIndex.restype = ctypes.c_void_p
    cf.CFArrayGetValueAtIndex.argtypes = [ctypes.c_void_p, ctypes.c_long]

    cf.CFDictionaryGetValue.restype = ctypes.c_void_p
    cf.CFDictionaryGetValue.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

    cf.CFStringCreateWithCString.restype = ctypes.c_void_p
    cf.CFStringCreateWithCString.argtypes = [
        ctypes.c_void_p,
        ctypes.c_char_p,
        ctypes.c_uint32,
    ]

    cf.CFStringGetCString.restype = ctypes.c_bool
    cf.CFStringGetCString.argtypes = [
        ctypes.c_void_p,
        ctypes.c_char_p,
        ctypes.c_long,
        ctypes.c_uint32,
    ]

    cf.CFNumberGetValue.restype = ctypes.c_bool
    cf.CFNumberGetValue.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
    ]

    cf.CFRelease.restype = None
    cf.CFRelease.argtypes = [ctypes.c_void_p]

    kCFStringEncodingUTF8 = 0x08000100
    kCGWindowListExcludeDesktopElements = 16

    win_list = cg.CGWindowListCopyWindowInfo(
        kCGWindowListExcludeDesktopElements, 0
    )
    if not win_list:
      return []

    count = cf.CFArrayGetCount(win_list)
    key_owner = cf.CFStringCreateWithCString(
        None, b"kCGWindowOwnerName", kCFStringEncodingUTF8
    )
    key_name = cf.CFStringCreateWithCString(
        None, b"kCGWindowName", kCFStringEncodingUTF8
    )
    key_num = cf.CFStringCreateWithCString(
        None, b"kCGWindowNumber", kCFStringEncodingUTF8
    )
    buf = ctypes.create_string_buffer(512)

    for i in range(count):
      d = cf.CFArrayGetValueAtIndex(win_list, i)
      owner_str = ""
      name_str = ""

      owner_val = cf.CFDictionaryGetValue(d, key_owner)
      if owner_val and cf.CFStringGetCString(
          owner_val, buf, 512, kCFStringEncodingUTF8
      ):
        owner_str = buf.value.decode("utf-8", errors="replace").strip()

      name_val = cf.CFDictionaryGetValue(d, key_name)
      if name_val and cf.CFStringGetCString(
          name_val, buf, 512, kCFStringEncodingUTF8
      ):
        name_str = buf.value.decode("utf-8", errors="replace").strip()

      disp_name = (
          f"{owner_str}: {name_str}"
          if (owner_str and name_str)
          else (owner_str or name_str)
      )
      if not disp_name:
        continue

      num_val = cf.CFDictionaryGetValue(d, key_num)
      if num_val:
        wid = ctypes.c_uint32()
        kCFNumberSInt32Type = 3
        if cf.CFNumberGetValue(
            num_val, kCFNumberSInt32Type, ctypes.byref(wid)
        ):
          results.append((wid.value, disp_name))

    cf.CFRelease(key_owner)
    cf.CFRelease(key_name)
    cf.CFRelease(key_num)
    cf.CFRelease(win_list)
  except Exception:
    pass

  return results


def capture_macos_window(window_id: int) -> Optional[np.ndarray]:
  """Captures an on-screen window image on macOS and returns a BGR numpy array.

  Args:
    window_id: Target macOS window number (kCGWindowNumber).

  Returns:
    BGR numpy array representing the frame if successful, otherwise None.
  """
  if sys.platform != "darwin":
    return None

  try:
    cg = ctypes.cdll.LoadLibrary(
        "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"
    )
    cf = ctypes.cdll.LoadLibrary(
        "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
    )

    cg.CGWindowListCreateImage.restype = ctypes.c_void_p
    cg.CGWindowListCreateImage.argtypes = [
        CGRect,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_uint32,
    ]

    cg.CGImageGetWidth.restype = ctypes.c_size_t
    cg.CGImageGetWidth.argtypes = [ctypes.c_void_p]

    cg.CGImageGetHeight.restype = ctypes.c_size_t
    cg.CGImageGetHeight.argtypes = [ctypes.c_void_p]

    cg.CGImageGetBytesPerRow.restype = ctypes.c_size_t
    cg.CGImageGetBytesPerRow.argtypes = [ctypes.c_void_p]

    cg.CGImageGetDataProvider.restype = ctypes.c_void_p
    cg.CGImageGetDataProvider.argtypes = [ctypes.c_void_p]

    cg.CGDataProviderCopyData.restype = ctypes.c_void_p
    cg.CGDataProviderCopyData.argtypes = [ctypes.c_void_p]

    cf.CFDataGetBytePtr.restype = ctypes.c_void_p
    cf.CFDataGetBytePtr.argtypes = [ctypes.c_void_p]

    cf.CFDataGetLength.restype = ctypes.c_long
    cf.CFDataGetLength.argtypes = [ctypes.c_void_p]

    cf.CFRelease.restype = None
    cf.CFRelease.argtypes = [ctypes.c_void_p]

    try:
      null_rect = CGRect.in_dll(cg, "CGRectNull")
    except Exception:
      null_rect = CGRect(CGPoint(float("inf"), float("inf")), CGSize(0, 0))

    kCGWindowListOptionIncludingWindow = 8
    kCGWindowImageBoundsIgnoreFraming = 1

    img_ref = cg.CGWindowListCreateImage(
        null_rect,
        kCGWindowListOptionIncludingWindow,
        window_id,
        kCGWindowImageBoundsIgnoreFraming,
    )
    if not img_ref:
      return None

    width = cg.CGImageGetWidth(img_ref)
    height = cg.CGImageGetHeight(img_ref)
    bytes_per_row = cg.CGImageGetBytesPerRow(img_ref)

    provider = cg.CGImageGetDataProvider(img_ref)
    if not provider:
      cf.CFRelease(img_ref)
      return None

    data_ref = cg.CGDataProviderCopyData(provider)
    if not data_ref:
      cf.CFRelease(img_ref)
      return None

    data_ptr = cf.CFDataGetBytePtr(data_ref)
    data_len = cf.CFDataGetLength(data_ref)
    raw_bytes = ctypes.string_at(data_ptr, data_len)

    cf.CFRelease(data_ref)
    cf.CFRelease(img_ref)

    if not raw_bytes or width <= 0 or height <= 0:
      return None

    arr = np.frombuffer(raw_bytes, dtype=np.uint8)
    if len(arr) < bytes_per_row * height:
      return None

    arr = arr[: bytes_per_row * height].reshape((height, bytes_per_row))
    rgba = arr[:, : width * 4].reshape((height, width, 4))
    bgr = cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGR)
    return bgr
  except Exception:
    return None
