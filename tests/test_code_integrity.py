"""Comprehensive code integrity and type-annotation tests.

Complies with the Google Python Style Guide.
Guarantees that:
1. All modules can be imported without runtime or circular dependency errors.
2. All type annotations across functions, methods, and classes evaluate eagerly
   without NameError or unresolved references (guarding against PEP 649 deferred
   evaluation blind spots across Python 3.10-3.14+).
3. Application CLI entrypoints boot cleanly with --help.
"""

import importlib
import inspect
import os
import subprocess
import sys
import typing
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestCodeIntegrity(unittest.TestCase):
  """Validates type annotation correctness and module importability."""

  MODULE_NAMES = [
      "config",
      "main",
      "core.capture",
      "core.capture_macos",
      "core.engine",
      "core.metrics",
      "core.python_engine",
      "core.updater",
      "ui.components",
      "ui.dialogs",
      "ui.hotkeys",
      "ui.overlay",
      "dev.cli_tracker",
      "dev.debug_dumper",
      "dev.video_simulation",
      "dev.window_picker",
  ]

  def test_all_modules_import_cleanly(self):
    """Verifies that all first-party modules import without exceptions."""
    for mod_name in self.MODULE_NAMES:
      with self.subTest(module=mod_name):
        mod = importlib.import_module(mod_name)
        self.assertIsNotNone(mod, f"Failed to import {mod_name}")

  def test_eager_type_annotations_are_valid(self):
    """Eagerly evaluates all type annotations across all classes and functions.

    Catches missing typing imports (such as Optional, Union, Tuple, List, Dict)
    regardless of whether the host Python interpreter evaluates annotations
    eagerly (<= 3.13) or deferred (3.14+ PEP 649).
    """
    annotation_errors = []

    for mod_name in self.MODULE_NAMES:
      mod = importlib.import_module(mod_name)
      for name, obj in inspect.getmembers(mod):
        # Inspect top-level functions and classes defined within the module
        if inspect.isfunction(obj) and getattr(obj, "__module__", None) == mod_name:
          try:
            typing.get_type_hints(obj)
          except Exception as e:
            annotation_errors.append(f"{mod_name}.{name}: {e}")

        elif inspect.isclass(obj) and getattr(obj, "__module__", None) == mod_name:
          try:
            typing.get_type_hints(obj)
          except Exception as e:
            annotation_errors.append(f"{mod_name}.{name} (class): {e}")

          # Inspect member functions/methods of the class
          for member_name, member_obj in inspect.getmembers(obj):
            if inspect.isfunction(member_obj) or inspect.ismethod(member_obj):
              try:
                typing.get_type_hints(member_obj)
              except Exception as e:
                annotation_errors.append(f"{mod_name}.{name}.{member_name}: {e}")

    self.assertEqual(
        annotation_errors,
        [],
        f"Found unresolved type annotations:\n" + "\n".join(annotation_errors),
    )

  def test_cli_help_smoke_test(self):
    """Verifies that main.py --help executes cleanly with zero return code."""
    proc = subprocess.run(
        [sys.executable, "main.py", "--help"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    self.assertEqual(proc.returncode, 0, f"main.py --help failed: {proc.stderr}")
    self.assertIn("Artale Desktop EXP Calculator", proc.stdout)

  def test_macos_carbon_hotkeys_ctypes_signatures(self):
    """Verifies that MacOSCarbonHotkeys sets explicit 64-bit ctypes signatures."""
    import ctypes
    from unittest.mock import MagicMock, patch
    from ui.hotkeys import MacOSCarbonHotkeys

    mock_lib = MagicMock()
    mock_lib.GetApplicationEventTarget = MagicMock(return_value=0x100000000)
    mock_lib.InstallEventHandler = MagicMock(return_value=0)
    mock_lib.RegisterEventHotKey = MagicMock(return_value=0)

    with patch("ctypes.cdll.LoadLibrary", return_value=mock_lib), patch(
        "sys.platform", "darwin"
    ):
      hk = MacOSCarbonHotkeys(lambda x: None)
      self.assertEqual(mock_lib.GetApplicationEventTarget.restype, ctypes.c_void_p)
      self.assertEqual(mock_lib.InstallEventHandler.restype, ctypes.c_int32)
      self.assertEqual(len(mock_lib.InstallEventHandler.argtypes), 6)
      self.assertEqual(mock_lib.RegisterEventHotKey.restype, ctypes.c_int32)
      self.assertEqual(len(mock_lib.RegisterEventHotKey.argtypes), 6)
      hk.cleanup()


if __name__ == "__main__":
  unittest.main()
