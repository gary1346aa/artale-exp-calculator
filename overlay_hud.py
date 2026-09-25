"""Artale EXP Calculator - Modern Floating HUD Overlay.

Backward-compatibility facade module re-exporting from config, core, ui, and dev.
Complies with the Google Python Style Guide.
"""

from config import (
    ALL_METRIC_KEYS,
    CONFIG_FILE,
    DEFAULT_GAME_MODE_KEYS,
    DEFAULT_SIMPLE_MODE_KEYS,
    FONT_FAMILY,
    SIMPLE_METRIC_CONFIG,
    format_chinese_exp,
    get_accum_exp_color,
    get_status_indicator_dot,
)
from core.capture import CaptureWorker, find_window_by_title_safe
from core.metrics import ExpMetricsEngine, MeasurementState
from dev.video_simulation import VideoSimulationWorker
from dev.window_picker import SelectWindowDialog, get_visible_windows
from ui.components import (
    MetricRow,
    SimpleMetricItem,
    SimpleProgressBarItem,
    SmoothButton,
    SmoothCard,
)
from ui.dialogs import GameModeSettingsDialog
from ui.hotkeys import HotkeyWorker
from ui.overlay import ArtaleExpOverlay, main

__all__ = [
    "ALL_METRIC_KEYS",
    "CONFIG_FILE",
    "DEFAULT_GAME_MODE_KEYS",
    "DEFAULT_SIMPLE_MODE_KEYS",
    "FONT_FAMILY",
    "SIMPLE_METRIC_CONFIG",
    "format_chinese_exp",
    "get_accum_exp_color",
    "get_status_indicator_dot",
    "CaptureWorker",
    "find_window_by_title_safe",
    "ExpMetricsEngine",
    "MeasurementState",
    "VideoSimulationWorker",
    "SelectWindowDialog",
    "get_visible_windows",
    "MetricRow",
    "SimpleMetricItem",
    "SimpleProgressBarItem",
    "SmoothButton",
    "SmoothCard",
    "GameModeSettingsDialog",
    "HotkeyWorker",
    "ArtaleExpOverlay",
    "main",
]

if __name__ == "__main__":
  main()
