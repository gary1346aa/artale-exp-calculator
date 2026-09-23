# Artale EXP Calculator (楓之谷世界 Artale 零GPU極速經驗計算機)

專為 **MapleStory Worlds - Artale** 打造的極致輕量、零 GPU 開銷、非侵入式即時經驗計算機與懸浮 HUD。

---

## 🌟 核心特色 (Key Features)

1. **極致輕量，零 GPU 佔用 (Zero GPU, Ultra-Low CPU)**
   - 全程運算皆在純 CPU 執行，完全不佔用顯卡 3D / Tensor 算力，不影響遊戲幀率。
   - 採 1 FPS 節流取樣，單次光學字元辨識僅耗時 **~75ms**，其餘 925ms 處於完全休眠狀態。

2. **手刻向量化 SIMD 核心 (AVX2 / ARM NEON)**
   - 核心以 C++20 編寫，實作 AVX2/FMA (x86_64) 與 NEON (Apple Silicon) 向量內聯指令 (Intrinsics)。
   - 內建積分圖 (Integral Images / SAT)，以 $O(1)$ 複雜度完成多尺度 `EXP.` Logo 模板匹配。
   - 像素點對點與標準 16x24 規範字形進行正規化互相關 (NCC) 比對。

3. **非侵入式背景擷取 (Non-Invasive DWM DirectX Capture)**
   - 採用 Windows 10/11 原生 **Windows Graphics Capture (WGC)** API。
   - 從桌面視窗管理員 (DWM) 交換鏈直接讀取遊戲畫面，**不注入任何 DLL、不讀寫遊戲記憶體、零被封號風險**。
   - 支援遊戲視窗被其他視窗遮擋、最小化邊界或動態縮放 (支援 720p 至 4K 全解析度)。

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
│       │   ├── artale_exp_core.cpp   # AVX2/NEON SIMD、積分圖、正規化字形匹配核心
│       │   └── digit_prototypes.h    # 規範化 16x24 字形特徵矩陣
│       └── CMakeLists.txt            # 跨平台 CMake 建置腳本
├── data/
│   ├── desktop_font_protos.json      # 原始字形點陣庫
│   └── real_exp_logo.png             # 42x14 EXP. 標誌錨點模板
├── artale_exp_core.dll               # AVX2 預編譯靜態動態鏈結庫
├── exp_core.py                       # CTypes 高效能橋接層 (自動 fallback)
├── metrics_engine.py                 # 滑動視窗速率與升級預估引擎 (繁中)
├── overlay_hud.py                    # PyQt6 現代無邊框毛玻璃懸浮窗
├── live_tracker.py                   # WGC 1 FPS 背景截圖監聽器
├── main.py                           # 統一啟動入口
└── requirements.txt                  # Python 相依清單
```
