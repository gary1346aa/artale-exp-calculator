# Artale EXP Calculator (楓之谷世界 Artale 經驗計算機)

專為 **MapleStory Worlds - Artale** 打造的非侵入式即時經驗計算機與懸浮 HUD。

---

## 核心架構 (Features)

1. **CPU 辨識架構**
   - 影像運算在 CPU 執行，不佔用顯卡 3D / Tensor 算力。
   - 採 1 FPS 取樣辨識。

2. **SIMD 運算核心 (AVX2 / ARM NEON)**
   - 核心以 C++ 編寫，提供 AVX2/FMA 與 NEON 向量指令支援。
   - 實作滑動視窗 NCC (Normalized Cross-Correlation) 模板比對與動態規劃字元解碼。

3. **非侵入式背景擷取 (Windows Graphics Capture)**
   - 採用 Windows 10/11 原生 **Windows Graphics Capture (WGC)** API。
   - 從桌面視窗管理員 (DWM) 交換鏈直接讀取畫面，不注入 DLL、不讀寫遊戲記憶體。
   - 支援遊戲視窗被其他視窗遮擋、邊界調整或動態縮放。

4. **現代半透明遊戲懸浮窗 (Modern Floating HUD Overlay)**
   - 採用 PyQt6 打造毛玻璃深色主題懸浮面板，置頂顯示 (Always-on-Top)、無邊框、任意拖曳移動。
   - 支援精簡模式切換、視窗位置自動記憶、暫停與重新統計功能。
   - 全介面繁體中文 (TC) 呈現。

---

## 📊 監控指標 (Metrics)

| 指標名稱 | 說明 |
| :--- | :--- |
| **練功時長** | 本次連線/打怪累積時間 (格式 `HH:MM:SS`) |
| **當前經驗** | 即時讀取之數值與百分比 (如 `822,784,172 (81.85%)`) |
| **總獲得經驗** | 本次統計累積獲得之經驗總值與累積百分比 |
| **1分鐘經驗** | 近 1 分鐘即時經驗獲得速率 |
| **預估10分 / 累積10分** | 依即時速率預估 10 分鐘獲取量 / 過去 10 分鐘實際獲得量 |
| **預估60分 / 累積60分** | 即時時薪預估 (EXP/h) / 過去 60 分鐘實際獲得量 |
| **升級預估時間** | 依當前速率預估達到 100% 之所需時間 (例如 `2小時15分`) |

---

## 🚀 快速啟動 (Getting Started)

### 1. 安裝環境依賴 (Python 3.10+)
```bash
pip install -r requirements.txt
```

### 2. 編譯 C++ SIMD 核心 (可選，已提供預編譯 DLL)
若欲自行編譯或修改 C++ 核心演算法：
- **Windows (Clang++ / MinGW-w64)**:
  ```powershell
  clang++ -O3 -mavx2 -mfma -shared -static -DARTALE_EXP_EXPORTS -Isrc/cpp/include -Isrc/cpp/src src/cpp/src/artale_exp_core.cpp -o artale_exp_core.dll
  ```
- **macOS (Apple Silicon NEON)**:
  ```bash
  clang++ -O3 -shared -std=c++20 -DARTALE_EXP_EXPORTS -Isrc/cpp/include -Isrc/cpp/src src/cpp/src/artale_exp_core.cpp -o libartale_exp_core.dylib
  ```

### 3. 啟動計算機
- **懸浮面板模式 (推薦)**:
  ```bash
  python main.py
  ```
- **終端機純文字模式 (CLI)**:
  ```bash
  python main.py --cli
  ```

---

## 📁 專案架構 (Project Structure)

```
artale_exp_calculator/
├── src/
│   └── cpp/
│       ├── include/
│       │   └── artale_exp_core.h     # C-ABI 跨語言導出介面
│       ├── src/
│       │   ├── artale_exp_core.cc    # 影像前處理與座標快取
│       │   ├── exp_engine.cc         # SIMD 雙線性插值與 NCC 字元辨識引擎
│       │   └── exp_engine.h          # ExpEngine 類別定義
│       └── CMakeLists.txt            # CMake 建置腳本
├── data/
│   ├── desktop_font_protos.json      # 原始字形點陣庫
│   └── real_exp_logo.png             # 標誌模板
├── exp_core.py                       # CTypes 橋接層 (自動 fallback)
├── metrics_engine.py                 # 滑動視窗速率與升級預估引擎 (繁中)
├── overlay_hud.py                    # PyQt6 現代無邊框毛玻璃懸浮窗
├── live_tracker.py                   # WGC 1 FPS 背景截圖監聽器
├── main.py                           # 統一啟動入口
└── requirements.txt                  # Python 相依清單
```
