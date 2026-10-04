# Artale EXP Calculator

An EXP tracker and floating HUD overlay for **MapleStory Worlds - Artale** on Windows and macOS.

---

## Downloads

Official release archives and files are available on the [GitHub Releases](https://github.com/gary1346aa/artale-exp-calculator/releases/latest) page:

- **Windows (x64)**: [`ArtaleExpCalculator-win-x64.zip`](https://github.com/gary1346aa/artale-exp-calculator/releases/latest/download/ArtaleExpCalculator-win-x64.zip)
- **macOS (Apple Silicon arm64)**: [`ArtaleExpCalculator-mac-arm64.zip`](https://github.com/gary1346aa/artale-exp-calculator/releases/latest/download/ArtaleExpCalculator-mac-arm64.zip)
- **User Manual (Traditional Chinese)**: [`Artale_EXP_Calculator_Manual_TC.pdf`](Artale_EXP_Calculator_Manual_TC.pdf)

---

## Quick Start Guide

1. **Download & Extract**: Download the zip package for your operating system from the link above and extract the files to a local folder.
2. **Launch MapleStory Worlds**: Open the game client and log into your character in Artale.
3. **Run the Calculator**:
   - **Windows**: Run `ArtaleExpCalculator.exe`.
   - **macOS**: Open `ArtaleExpCalculator.app`. On first launch, grant **Screen Recording** and **Accessibility** permissions under macOS *System Settings > Privacy & Security*.
4. **Target Window**: Ensure the target window title matches `MapleStory Worlds-Artale` (Windows) or `MapleStory Worlds` (macOS). The status indicator will turn **Green** when target recognition succeeds.

---

## Controls

### Primary Mouse Gestures on the Floating HUD

| Gesture | Action |
| :--- | :--- |
| **Left Double-Click** | **Cycle Display Modes**: Switches between Full Mode (`完整模式`), Game Mode (`遊戲模式`), and Minimal Mode (`極簡模式`). |
| **Left Click & Drag** | Move the floating HUD window across screens (position automatically saved). |
| **Right-Click** | Open context menu (Display modes, Settings, Hunting History & Characters, About & Update, Quit). |
| **Ctrl + Wheel** | Adjust HUD scaling (50%–200%). |
| **Shift/Alt + Wheel** | Adjust HUD background transparency (0%–80%). |

### Global Keyboard Shortcuts (Usable While in Game)

| Shortcut (Windows) | Shortcut (macOS) | Action |
| :--- | :---: | :--- |
| `F6` | `⌃6` | Toggle Auto-Start timer mode |
| `F7` | `⌃7` | Start / Pause active measurement |
| `F8` | `⌃8` | Reset measurement baseline and finalize current hunting session |
| `F9` | `⌃9` | Cycle Display Modes (`完整` $\to$ `遊戲` $\to$ `極簡`) |

---

## Features

- **Pixel-Based Recognition**: Reads bottom HUD pixels at 1 FPS via Windows Graphics Capture (Windows) and CoreGraphics (macOS) without reading game memory or modifying game files.
- **Mathematical EXP Table Validation**: Verifies readings against the official Artale Level 1–200 EXP table to prevent single-frame misreads.
- **Auto-Start & Auto-Pause**: Automatically starts/resumes measurement upon EXP gain and pauses after a configurable idle threshold.
- **Three HUD Modes**:
  - **Full Mode (`完整模式`)**: Displays all 10 metrics, EXP progress bar, and controls.
  - **Game Mode (`遊戲模式`)**: Displays a customizable subset of metrics with auto-hidden header/controls.
  - **Minimal Mode (`極簡模式`)**: Horizontal compact capsule displaying duration, 10-minute projected rate, and accumulated EXP.
- **Hunting History & Multi-Character Management**:
  - Automatically records completed hunting sessions to a local SQLite database (`hunting_history.db`) in Write-Ahead Logging (WAL) mode.
  - **Multi-Character Support**: Reverse-calculates player level directly from EXP points and percentages. Supports manual character profile creation, customization (ID, job, level), and atomic character merge.
  - **Offline HTML Analytics Dashboard (`hunting_dashboard.html`)**: Interactive single-page report featuring monotone cubic spline charts, calendar filtering, and session telemetry breakdown.
- **Integrated In-Place Updater**: Checks for updates from GitHub Releases and updates directly within the application.

---

## Bug Reports & Feedback

If you encounter issues or have feature suggestions, please open an issue in the [GitHub Issues](https://github.com/gary1346aa/artale-exp-calculator/issues) tracker.
