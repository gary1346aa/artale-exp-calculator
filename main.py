"""Artale EXP Calculator - Main Application Entrypoint.

Complies with the Google Python Style Guide.
Usage:
    python main.py                       # Launch floating gaming HUD overlay
    python main.py --dev                 # Launch in developer mode (adds dev menus)
    python main.py --cli                 # Run in terminal console mode
    python main.py -v /path/to/vid.mp4   # Offline video simulation mode
    python main.py -s 2.0                # 2x simulation playback speed
    python main.py -w "VLC"              # Track specific window title
"""

import argparse
import os
import logging
import sys

import config


def setup_logging() -> None:
  """Configures dual console and file logging to user config directory."""
  log_file = os.path.join(config.USER_CONFIG_DIR, "artale_app.log")
  handlers = [logging.StreamHandler(sys.stdout)]
  try:
    os.makedirs(config.USER_CONFIG_DIR, exist_ok=True)
    handlers.append(logging.FileHandler(log_file, encoding="utf-8", mode="w"))
  except Exception:
    pass

  logging.basicConfig(
      level=logging.INFO,
      format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
      handlers=handlers,
  )
  logging.info(
      "Starting %s %s on %s (%s)",
      config.APP_NAME,
      config.get_full_version_string(),
      sys.platform,
      config.get_isa_display_name(),
  )
  logging.info("Log file location: %s", log_file)


def init_windows_stdio() -> None:
  """Ensures stdout/stderr exist in frozen GUI processes on Windows."""
  if sys.platform == "win32":
    import ctypes
    # Attach to parent console if invoked from terminal
    if ctypes.windll.kernel32.AttachConsole(-1):
      try:
        sys.stdout = open("CONOUT$", "w", encoding="utf-8", errors="replace")
        sys.stderr = open("CONOUT$", "w", encoding="utf-8", errors="replace")
      except Exception:
        pass
    if sys.stdout is None:
      sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
      sys.stderr = open(os.devnull, "w", encoding="utf-8")


def main() -> None:
  """Parses command line arguments and launches the application."""
  init_windows_stdio()
  setup_logging()
  parser = argparse.ArgumentParser(
      description="Artale Desktop EXP Calculator - Real-time Gaming Overlay"
  )
  parser.add_argument(
      "--version",
      action="version",
      version=f"{config.APP_NAME} {config.get_full_version_string()}",
  )
  parser.add_argument(
      "--dev",
      action="store_true",
      help="Enable developer mode (exposes offline simulation and window picker)",
  )
  parser.add_argument(
      "--cli",
      action="store_true",
      help="Run in terminal CLI mode without GUI overlay",
  )
  parser.add_argument(
      "-v",
      "--video",
      type=str,
      nargs="?",
      const="prompt",
      default=None,
      help="Simulate measurement from a recorded video file path",
  )
  parser.add_argument(
      "-s",
      "--speed",
      type=float,
      default=1.0,
      help="Playback speed multiplier for video simulation (default: 1.0)",
  )
  parser.add_argument(
      "-w",
      "--window",
      type=str,
      default=None,
      help=(
          "Target window title to track (default:"
          f" '{config.DEFAULT_TARGET_WINDOW}')"
      ),
  )
  args = parser.parse_args()

  if args.dev:
    os.environ["ARTALE_DEV"] = "1"
    config.IS_DEV = True

  if args.cli:
    from dev.cli_tracker import run_cli_tracker
    run_cli_tracker(window_name=args.window or config.DEFAULT_TARGET_WINDOW)
  else:
    from ui.overlay import main as run_overlay
    run_overlay(
        video_path=args.video,
        speed=args.speed,
        window_name=args.window,
    )


if __name__ == "__main__":
  main()
