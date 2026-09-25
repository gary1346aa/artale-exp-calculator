"""Global configuration, constants, and environment definitions for Artale EXP Calculator.

Complies with the Google Python Style Guide.
"""

import os
import sys
from typing import Any, Dict, List, Optional, Tuple, Union

# Developer mode flag: active if ARTALE_DEV=1 or --dev is passed in sys.argv.
IS_DEV: bool = os.environ.get("ARTALE_DEV", "0") == "1" or "--dev" in sys.argv

# Project directories and resource resolution (supports both dev and PyInstaller frozen bundles)
if getattr(sys, "frozen", False):
  APP_DIR: str = os.path.dirname(sys.executable)
  RESOURCE_DIR: str = getattr(sys, "_MEIPASS", APP_DIR)
else:
  APP_DIR = os.path.dirname(os.path.abspath(__file__))
  RESOURCE_DIR = APP_DIR

BASE_DIR: str = RESOURCE_DIR
CONFIG_FILE: str = os.path.join(APP_DIR, "hud_config.json")
DEBUG_OUTPUT_DIR: str = os.path.join(APP_DIR, "debug_output")


def get_resource_path(relative_path: str) -> str:
  """Resolves the absolute path to a bundled asset or data file."""
  return os.path.join(RESOURCE_DIR, relative_path)

# Target window title
DEFAULT_TARGET_WINDOW: str = "MapleStory Worlds-Artale"

# Typography and fonts
FONT_FAMILY: str = (
    "'Google Sans', 'Google Sans Medium', 'PingFang TC', 'PingFang HK',"
    " -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Microsoft JhengHei UI',"
    " 'Microsoft JhengHei', sans-serif"
)

# Metric identifiers
METRIC_DURATION: str = "練功時長"
METRIC_1MIN_RATE: str = "1分鐘經驗"
METRIC_EST_10MIN: str = "預估10分"
METRIC_ACC_10MIN: str = "累積10分"
METRIC_EST_60MIN: str = "預估60分"
METRIC_ACC_60MIN: str = "累積60分"
METRIC_TOTAL_EXP: str = "累計經驗"
METRIC_CURRENT_EXP: str = "當前經驗"
METRIC_TIME_TO_LEVEL: str = "升級預估時間"
METRIC_PROGRESS_BAR: str = "EXP 進度條"

ALL_METRIC_KEYS: List[str] = [
    METRIC_DURATION,
    METRIC_1MIN_RATE,
    METRIC_EST_10MIN,
    METRIC_ACC_10MIN,
    METRIC_EST_60MIN,
    METRIC_ACC_60MIN,
    METRIC_TOTAL_EXP,
    METRIC_CURRENT_EXP,
    METRIC_TIME_TO_LEVEL,
    METRIC_PROGRESS_BAR,
]

DEFAULT_GAME_MODE_KEYS: List[str] = [
    METRIC_DURATION,
    METRIC_EST_10MIN,
    METRIC_EST_60MIN,
    METRIC_TOTAL_EXP,
    METRIC_TIME_TO_LEVEL,
]

DEFAULT_SIMPLE_MODE_KEYS: List[str] = [
    METRIC_DURATION,
    METRIC_EST_10MIN,
    METRIC_TOTAL_EXP,
]

SIMPLE_METRIC_CONFIG: Dict[str, Dict[str, str]] = {
    METRIC_DURATION: {"label": "時長", "color": "#94a3b8"},
    METRIC_EST_10MIN: {"label": "10分", "color": "#38bdf8"},
    METRIC_TOTAL_EXP: {"label": "累積", "color": "#c084fc"},
    METRIC_1MIN_RATE: {"label": "1分", "color": "#38bdf8"},
    METRIC_ACC_10MIN: {"label": "累積10分", "color": "#818cf8"},
    METRIC_EST_60MIN: {"label": "預估60分", "color": "#60a5fa"},
    METRIC_ACC_60MIN: {"label": "累積60分", "color": "#818cf8"},
    METRIC_CURRENT_EXP: {"label": "當前", "color": "#fbbf24"},
    METRIC_TIME_TO_LEVEL: {"label": "升級預估", "color": "#34d399"},
}


def format_chinese_exp(val: Optional[Union[int, float]]) -> str:
  """Formats numerical EXP values into readable Traditional Chinese units.

  Formatting rules:
    - None:           '--'
    - < 10,000:       e.g. '0', '9,500'
    - 10,000 ~ 1億:   e.g. '123.4 萬'
    - >= 1億:         e.g. '1.23 億'

  Args:
    val: Integer or float number representing EXP points.

  Returns:
    Formatted string with space between digits and Chinese unit.
  """
  if val is None:
    return "--"
  sign = "-" if val < 0 else ""
  abs_val = abs(val)
  if abs_val >= 100_000_000:
    num = abs_val / 100_000_000.0
    return f"{sign}{num:.2f} 億"
  if abs_val >= 10_000:
    num = abs_val / 10_000.0
    return f"{sign}{num:.1f} 萬"
  return f"{sign}{int(abs_val):,d}"


def get_rate_color(val: Optional[Union[int, float]]) -> str:
  """Returns hex color code representing EXP acquisition rate thresholds."""
  if val is None or val < 0:
    return "#94a3b8"
  if val < 20_000_000:
    return "#FFFFFF"
  if val < 40_000_000:
    return "#FFCC00"
  if val < 60_000_000:
    return "#66CCFF"
  if val < 80_000_000:
    return "#FF80FF"
  if val < 100_000_000:
    return "#FFFF66"
  if val < 120_000_000:
    return "#66FF00"
  return "#FF66CC"


# Backward compatibility alias
get_accum_exp_color = get_rate_color


def get_status_indicator_dot(
    is_locked: bool, state: Any
) -> Tuple[str, str, str]:
  """Computes (char, color, tooltip) for the status indicator dot.

  States:
    1. Green hollow ('○', #4ade80): exp number not captured correctly (searching / minimized).
    2. Green solid ('●', #4ade80): ready / not measuring (reset or launched, window & exp locked).
    3. Red solid ('●', #ef4444): measuring (recording EXP like a camera REC button).
    4. Yellow solid ('●', #eab308): pause.
  """
  state_val = state.value if hasattr(state, "value") else str(state)
  if not is_locked:
    return "○", "#4ade80", "未鎖定經驗條 (搜尋中、視窗最小化或尚未找到遊戲視窗)"
  if state_val == "RUNNING":
    return "●", "#ef4444", "測量中 (視窗與經驗值正常擷取)"
  elif state_val == "PAUSED":
    return "●", "#eab308", "測量暫停中"
  else:  # IDLE
    return "●", "#4ade80", "已鎖定視窗與經驗值 (待命中，尚未開始測量)"


