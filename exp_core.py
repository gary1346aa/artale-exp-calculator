"""Artale EXP Core interface.

Backward-compatibility facade module re-exporting from core.engine and dev.debug_dumper.
Complies with the Google Python Style Guide.
"""

from core.engine import (
    ExpResult,
    ParsedFrame,
    _core_dll,
    _use_cpp,
    is_cpp_active,
    parse_frame,
)
from dev.debug_dumper import save_crop_debug

__all__ = [
    "ExpResult",
    "ParsedFrame",
    "parse_frame",
    "save_crop_debug",
    "is_cpp_active",
    "_core_dll",
    "_use_cpp",
]
