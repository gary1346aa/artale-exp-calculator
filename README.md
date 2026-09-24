# Artale EXP Calculator

A non-invasive real-time EXP tracker and floating HUD overlay designed for **MapleStory Worlds - Artale**.

---

## Architecture & Features

1. **CPU-Based Recognition Pipeline**
   - OCR and image processing execute entirely on CPU without consuming GPU 3D or Tensor compute resources.
   - Throttled 1 FPS sampling rate.

2. **SIMD Vectorized Engine (AVX2 / ARM NEON)**
   - Core engine written in C++ with AVX2/FMA and ARM NEON support.
   - Bit-exact OpenCV-compliant bilinear resizing (`ResizeGray`).
   - Vectorized sliding-window Normalized Cross-Correlation (`MatchTemplateNcc`) with rolling column sums and multi-register unrolling.
   - Grammar-constrained dynamic programming beam search for character classification and bracket disambiguation.

3. **Non-Invasive Screen Capture (Windows Graphics Capture)**
   - Utilizes Windows 10/11 native **Windows Graphics Capture (WGC)** APIs via Desktop Window Manager (DWM).
   - Reads directly from the DirectX swapchain without DLL injection or process memory access.
   - Adapts to obscured windows, resolution changes, and multi-monitor setups (supporting 720p to 4K).

4. **Translucent Gaming HUD Overlay**
   - Built with PyQt6: frameless, dark translucent theme, always-on-top, draggable.
   - Supports compact mode toggle, window position persistence, pause/resume, and session reset.
   - Display localized in Traditional Chinese.

---

## Metrics Tracked

| Metric | Description |
| :--- | :--- |
| **Session Duration** | Elapsed hunting / training time (`HH:MM:SS`) |
| **Current EXP** | Real-time EXP value and percentage (e.g. `822,784,172 (81.85%)`) |
| **Total EXP Gained** | Total accumulated EXP and percentage gain in the current session |
| **1-Minute Rate** | Estimated EXP rate based on the past 1 minute |
| **10-Minute Projection / Actual** | Projected 10-minute rate vs. actual EXP gained in the last 10 minutes |
| **60-Minute Projection / Actual** | Projected hourly rate (EXP/h) vs. actual EXP gained in the last 60 minutes |
| **ETA to Level Up** | Estimated time remaining to reach the next level based on current rate |

---

## Getting Started

### 1. Requirements & Dependencies (Python 3.10+)

```bash
pip install -r requirements.txt
```

### 2. Building the C++ Engine (Optional)

Precompiled binaries are provided. To rebuild from source:

- **Using Bazel (Recommended)**:
  ```bash
  bazel build //src/cpp:artale_exp_core_dll -c opt
  ```

- **Using Clang++ on Windows**:
  ```powershell
  clang++ -O3 -mavx2 -mfma -shared -static -std=c++17 -DARTALE_EXP_EXPORTS -Isrc/cpp/include -I. src/cpp/src/exp_engine.cc src/cpp/src/artale_exp_core.cc -o artale_exp_core.dll
  ```

- **Running Tests & Verification**:
  ```bash
  bazel test //tests:exp_engine_test -c opt
  python scripts/run_equivalence_suite.py
  ```

### 3. Launching the Tracker

- **Floating HUD Overlay Mode (Default)**:
  ```bash
  python main.py
  ```

- **Terminal CLI Mode**:
  ```bash
  python main.py --cli
  ```

---

## Project Structure

```
artale_exp_calculator/
├── src/
│   └── cpp/
│       ├── include/
│       │   └── artale_exp_core.h     # C-ABI export interface
│       ├── src/
│       │   ├── artale_exp_core.cc    # Preprocessing, caching, and C API bridge
│       │   ├── exp_engine.cc         # SIMD bilinear resize, NCC matching, and DP decoder
│       │   ├── exp_engine.h          # ExpEngine class definition
│       │   ├── pristine_font_protos.h# Canonical font prototypes
│       │   └── real_exp_logo.png     # Logo template data
│       ├── BUILD.bazel               # Bazel build definitions
│       └── CMakeLists.txt            # CMake build definitions
├── data/
│   ├── desktop_font_protos.json      # Raw prototype font definitions
│   └── real_exp_logo.png             # Reference anchor template
├── exp_core.py                       # Python ctypes binding layer with automatic fallback
├── metrics_engine.py                 # Sliding-window rate engine & ETA calculation
├── overlay_hud.py                    # PyQt6 floating HUD overlay
├── live_tracker.py                   # WGC screen capture loop & frame dispatch
├── main.py                           # Application entrypoint
├── scripts/
│   ├── generate_cpp_headers.py       # Header generator from JSON prototypes
│   └── run_equivalence_suite.py      # Regression equivalence test suite
├── tests/
│   ├── BUILD.bazel                   # Bazel test target definitions
│   ├── exp_engine_test.cc            # C++ Google Test test suite
│   ├── test_block_equivalence.py     # Component-level C++ vs. OpenCV verification
│   └── test_python_exp_engine.py     # Python engine unit tests
├── benchmarks/
│   ├── BUILD.bazel                   # Benchmark target definitions
│   └── exp_engine_benchmark.cc       # Google Benchmark performance harness
├── MODULE.bazel                      # Bazel dependencies configuration
└── requirements.txt                  # Python dependencies
```
