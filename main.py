"""Artale EXP Calculator - Main Launcher.

Usage:
    python main.py          # Launches the floating gaming HUD overlay
    python main.py --cli    # Runs in pure terminal mode
"""

import sys
import argparse

def main():
    parser = argparse.ArgumentParser(description="Artale Desktop Zero-GPU EXP Calculator")
    parser.add_argument("--cli", action="store_true", help="Run in terminal CLI mode without GUI overlay")
    args = parser.parse_args()

    if args.cli:
        import live_tracker
        live_tracker.main()
    else:
        import overlay_hud
        overlay_hud.main()

if __name__ == "__main__":
    main()
