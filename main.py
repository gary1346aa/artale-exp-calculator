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
import sys

import config


def main() -> None:
  """Parses command line arguments and launches the application."""
  parser = argparse.ArgumentParser(
      description="Artale Desktop EXP Calculator - Real-time Gaming Overlay"
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
