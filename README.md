# Artale EXP Calculator

An EXP tracker and floating HUD overlay for **MapleStory Worlds - Artale** on Windows and macOS.

---

## Architecture & Features

1. **CPU-Based Recognition Pipeline**
   - OCR and image processing run on the CPU at a 1 FPS sampling interval.
   - Static-frame skipping avoids redundant multi-scale template searches when the bottom HUD strip has not changed.

2. **SIMD Vectorized Engine (AVX2 / ARM NEON)**
   - Core recognition engine written in C++ with x86-64 AVX2/FMA and Apple Silicon ARM NEON implementations, plus a reference Python/NumPy fallback.
   - Fixed-point bilinear resizing (`ResizeGray`) matching `cv2.INTER_LINEAR`.
   - Vectorized sliding-window Normalized Cross-Correlation (`MatchTemplateNcc`) with rolling column sums.
   - Grammar-constrained dynamic programming beam search (`^\d+\[\d{1,2}\.\d{1,2}%\]$`) with character contiguity enforcement.

3. **Mathematical Validation & Measurement Engine**
   - Cross-validates OCR readings against the Artale Level 1–200 EXP table (`core/exp_table.py`) to filter single-frame OCR misreads.
   - Supports level-up carryover, 1-frame false level-up rollback, and 3-frame level resynchronization when switching characters.
   - Excludes EXP and level-ups gained while paused so active hunting rates and cumulative metrics reflect only measured time.
   - Configurable **Auto-Start** (starts or resumes when EXP increases) and **Auto-Pause** (pauses after N seconds without EXP gain).

4. **Cross-Platform Window Capture**
   - **Windows**: Captures the target window via **Windows Graphics Capture (WGC)** with fallback to Win32 GDI (`PrintWindow` / `BitBlt`).
   - **macOS**: Captures the target window via **CoreGraphics** (`CGWindowListCreateImage`) using `ctypes`.
   - Supports window resolutions from 720p to 4K without reading game process memory or modifying game files.

5. **Three-Mode Floating HUD Overlay & Customization**
   - Built with PyQt6 and bundled `Google Sans` (Latin/digits) + `PingFang TC` (Traditional Chinese) fonts.
   - **Left Double-Click on the HUD** cycles through the three display modes:
     - **Full Mode (`完整模式`)**: Displays all 10 metrics, header controls, status indicator, EXP progress bar, and footer.
     - **Game Mode (`遊戲模式`)**: Displays a user-selected subset of metrics and hides the header bar and sliders when unfocused.
     - **Minimal Mode (`極簡模式`)**: Horizontal capsule displaying status indicator, `時長` (Duration), `10分` (10m Est.), and `累積` (Accumulated EXP) in `萬`/`億` units, with hover/focus action buttons.
   - Customizable metric display order, UI scale (`50%`–`200%`), background transparency (`0%`–`80%`), HUD width (`235`–`340 px`), row spacing (`0`–`6 px`), and font weight (`400`–`700`).
   - Built-in GitHub Releases update checker and in-place updater (`AboutDialog` / `core/updater.py`).

---

## Metrics Tracked

| Metric (UI Label) | Minimal Mode Label | Description |
| :--- | :---: | :--- |
| **1. 練功時長** (Session Duration) | `時長` | Active measured hunting time (`HH:MM:SS`), excluding paused intervals |
| **2. 1分鐘經驗** (1-Minute Rate) | — | Rolling 60-second EXP gain rate |
| **3. 預估10分** (10m Projected) | `10分` | Projected 10-minute EXP gain based on current active rate |
| **4. 累積10分** (10m Actual) | — | Actual EXP gained over the last 10 active minutes |
| **5. 預估60分** (60m Projected) | — | Projected hourly EXP rate based on current active rate |
| **6. 累積60分** (60m Actual) | — | Actual EXP gained over the last 60 active minutes |
| **7. 累計經驗** (Accumulated EXP) | `累積` | Total active EXP and percentage gained since current baseline (7-tier color coding) |
| **8. 當前經驗** (Current EXP) | — | Current EXP value and percentage (1–2 decimal places, e.g. `686,615,140 (44.57%)`) |
| **9. 升級預估時間** (ETA to Level Up) | — | Estimated remaining time to reach the next level based on current rate |
| **10. EXP 進度條** (EXP Progress Bar) | — | 0%–100% progress bar showing current level completion percentage |

---

## Mouse & Keyboard Controls

**Mouse Controls on the HUD:**
- **Left Double-Click**: Cycle display mode (**Full Mode** $\to$ **Game Mode** $\to$ **Minimal Mode**)
- **Left Click & Drag**: Move HUD position (saved automatically)
- **Right Click**: Open context menu (switch mode, open Settings, Hotkeys submenu, About/Update)
- **Ctrl + Mouse Wheel**: Adjust UI scale (`50%`–`200%`)
- **Shift / Alt + Mouse Wheel**: Adjust background transparency (`0%`–`80%`)

**Global Keyboard Shortcuts** (work while the game window is focused):

| Action | Windows | macOS | Description |
| :--- | :---: | :---: | :--- |
| **Auto-Start Toggle** | `F6` | `⌃6` | Enable or disable automatic measurement start/resume on EXP gain |
| **Start / Pause** | `F7` | `⌃7` | Start or pause active EXP measurement |
| **Reset Measurement** | `F8` | `⌃8` | Reset elapsed time, cumulative gains, and baseline to current EXP |
| **Switch HUD Mode** | `F9` | `⌃9` | Cycle through **Full Mode** $\to$ **Game Mode** $\to$ **Minimal Mode** (same as Left Double-Click) |

---

## Getting Started

### 1. Requirements & Dependencies (Python 3.10+)

```bash
pip install -r requirements.txt
```

### 2. Building the C++ Engine (Optional)

Precompiled shared libraries (`artale_exp_core.dll` / `libartale_exp_core.dylib`) are loaded automatically when present. To rebuild from source:

- **Using Bazel**:
  ```bash
  bazel build //src/cpp:artale_exp_core_dll -c opt
  ```

- **Using Clang++ on Windows (x86_64 AVX2)**:
  ```powershell
  clang++ -O3 -mavx2 -mfma -shared -static -std=c++17 -DARTALE_EXP_EXPORTS -Isrc/cpp/include -I. src/cpp/src/exp_engine.cc src/cpp/src/artale_exp_core.cc -o artale_exp_core.dll
  ```

- **Using Clang++ on macOS (Apple Silicon / Intel)**:
  ```bash
  clang++ -O3 -std=c++17 -dynamiclib -fPIC -Isrc/cpp/include -I. src/cpp/src/exp_engine.cc src/cpp/src/artale_exp_core.cc -o libartale_exp_core.dylib
  ```

- **Running Tests & Verification**:
  ```bash
  python -m unittest discover -s tests
  bazel test //tests:exp_engine_test -c opt
  python scripts/run_equivalence_suite.py
  ```

### 3. Launching the Application

- **Floating HUD Overlay Mode (Default)**:
  ```bash
  python main.py
  ```

- **Developer Mode (enables Target Window Picker, Video Simulation, and Debug Crop Dumper)**:
  ```bash
  python main.py --dev
  ```

- **Terminal CLI Mode**:
  ```bash
  python main.py --cli
  ```

- **Offline Video Simulation Mode**:
  ```bash
  python main.py --dev -v /path/to/gameplay.mp4 -s 2.0
  ```

---

## Project Structure

```text
artale_exp_calculator/
├── config.py                         # Global constants, font definitions, and formatting helpers
├── main.py                           # Application entrypoint & CLI argument parser
├── core/
│   ├── capture.py                    # Windows Graphics Capture & Win32 GDI fallback worker
│   ├── capture_macos.py              # macOS CoreGraphics window enumeration & capture
│   ├── engine.py                     # Native C++ SIMD ctypes bridge & fallback dispatcher
│   ├── exp_table.py                  # Levels 1–200 EXP table & mathematical cross-validation
│   ├── metrics.py                    # Measurement state machine, rolling windows, and ETA engine
│   ├── python_engine.py              # Reference Python/NumPy recognition engine
│   └── updater.py                    # GitHub Releases update checker & in-place auto-updater
├── ui/
│   ├── components.py                 # Custom vector-rendered widgets, badges, buttons, and icons
│   ├── dialogs.py                    # Settings dialog (GameModeSettingsDialog) & About/Update dialog
│   ├── hotkeys.py                    # Global hotkey listeners (Win32 RegisterHotKey & macOS Carbon)
│   └── overlay.py                    # Main PyQt6 floating HUD overlay (Full, Game, and Minimal modes)
├── dev/
│   ├── cli_tracker.py                # Terminal live tracking loop (--cli)
│   ├── debug_dumper.py               # Annotated OCR crop exporter (--dev)
│   ├── video_simulation.py           # Offline video playback simulation worker (-v)
│   └── window_picker.py              # Target window selection dialog (--dev)
├── src/
│   └── cpp/
│       ├── include/
│       │   └── artale_exp_core.h     # C-ABI export interface
│       ├── src/
│       │   ├── artale_exp_core.cc    # Grayscale extraction, ROI caching, and C API bridge
│       │   ├── exp_engine.cc         # AVX2/NEON/Scalar bilinear resize, NCC, and DP beam search
│       │   ├── exp_engine.h          # ExpEngine class declaration
│       │   ├── pristine_font_protos.h# Embedded character prototype maps
│       │   └── real_exp_logo_data.h  # Embedded EXP logo anchor template
│       ├── BUILD.bazel               # Bazel build targets
│       └── CMakeLists.txt            # CMake build configuration
├── assets/
│   ├── fonts/                        # Bundled Google Sans and PingFang TC fonts
│   ├── icon.ico                      # Windows application icon
│   └── icon.icns                     # macOS application icon
├── data/
│   ├── pristine_font_protos.json     # Character prototype definitions
│   └── real_exp_logo.png             # Reference EXP logo template
├── scripts/
│   ├── build_app.py                  # Cross-platform native + PyInstaller build script
│   ├── build_macos.sh                # macOS standalone bundle build script
│   ├── generate_cpp_headers.py       # Generates C++ headers from JSON/PNG data
│   └── run_equivalence_suite.py      # C++ vs. Python equivalence test runner
└── tests/
    ├── BUILD.bazel                   # Bazel C++ test target definitions
    ├── code_integrity_test.cc        # C++ code integrity tests
    ├── exp_engine_test.cc            # GoogleTest suite (AVX2, NEON, Scalar, and DP grammar)
    ├── test_block_equivalence.py     # Block-level C++ vs. OpenCV equivalence tests
    ├── test_code_integrity.py        # Python import & eager type-annotation verification
    ├── test_metrics_engine.py        # Measurement state machine & level-up/pause unit tests
    ├── test_overlay_hud.py           # PyQt6 HUD modes, dialogs, hotkeys, and persistence tests
    ├── test_python_exp_engine.py     # Reference Python recognition engine unit tests
    └── test_updater.py               # Auto-updater version parsing & swap script unit tests
```
