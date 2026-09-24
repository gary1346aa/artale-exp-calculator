"""Artale EXP Calculator - Main Launcher.

Usage:
    python main.py                     # Launches the floating gaming HUD overlay
    python main.py --cli               # Runs in pure terminal mode
    python main.py -v /path/to/vid.mp4 # Simulates measurement from a recorded video
    python main.py -s 2.0              # 2x simulation speed
    python main.py -w "VLC"            # Tracks a specific window by title
"""

import sys
import argparse

def main():
    parser = argparse.ArgumentParser(description="Artale Desktop EXP Calculator")
    parser.add_argument("--cli", action="store_true", help="Run in terminal CLI mode without GUI overlay")
    parser.add_argument("-v", "--video", type=str, nargs="?", const="prompt", default=None,
                        help="Simulate measurement from video file path (or prompt if omitted)")
    parser.add_argument("-s", "--speed", type=float, default=1.0,
                        help="Playback speed multiplier for video simulation (default: 1.0)")
    parser.add_argument("-w", "--window", type=str, default=None,
                        help="Target window title to track (default: 'MapleStory Worlds-Artale')")
    args = parser.parse_args()

    if args.cli:
        import live_tracker
        live_tracker.main()
    else:
        import overlay_hud
        overlay_hud.main(video_path=args.video, speed=args.speed, window_name=args.window)

if __name__ == "__main__":
    main()
