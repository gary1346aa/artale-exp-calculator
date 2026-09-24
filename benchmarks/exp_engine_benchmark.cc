// Copyright 2026 Artale Exp Project. All rights reserved.
// Google C++ Style Guide compliant.
// Reference: https://github.com/google/benchmark

#include <windows.h>

#include <cmath>
#include <cstdint>
#include <cstdio>
#include <string>
#include <vector>

#include "benchmark/benchmark.h"
#include "src/cpp/src/exp_engine.h"
#include "src/cpp/src/pristine_font_protos.h"

namespace artale {
namespace exp {
namespace {

// =========================================================================
// Dynamic Python Runtime Harness for Google Benchmark Comparison
// =========================================================================
class PythonHarness {
 public:
  typedef void (*Py_Initialize_t)();
  typedef int (*PyRun_SimpleString_t)(const char*);
  typedef void* (*PyImport_AddModule_t)(const char*);
  typedef void* (*PyObject_GetAttrString_t)(void*, const char*);
  typedef void* (*PyObject_CallNoArgs_t)(void*);
  typedef void (*Py_DecRef_t)(void*);
  typedef void (*Py_Finalize_t)();

  static PythonHarness& Get() {
    static PythonHarness instance;
    return instance;
  }

  bool IsAvailable() const { return initialized_; }

  void RunResize() {
    if (fn_resize_ && py_call_no_args_) {
      void* res = py_call_no_args_(fn_resize_);
      if (res && py_decref_) py_decref_(res);
    }
  }

  void RunNcc() {
    if (fn_ncc_ && py_call_no_args_) {
      void* res = py_call_no_args_(fn_ncc_);
      if (res && py_decref_) py_decref_(res);
    }
  }

  void RunParseCrop() {
    if (fn_parse_crop_ && py_call_no_args_) {
      void* res = py_call_no_args_(fn_parse_crop_);
      if (res && py_decref_) py_decref_(res);
    }
  }

 private:
  PythonHarness() {
    const char* dll_names[] = {
        "python314.dll",
        "python312.dll",
        "python311.dll",
        "python3.dll",
        "C:"
        "\\Users\\gary1\\AppData\\Local\\Programs\\Python\\Python314\\python314"
        ".dll",
    };

    HMODULE h_mod = nullptr;
    for (const char* name : dll_names) {
      h_mod = LoadLibraryA(name);
      if (h_mod) break;
    }
    if (!h_mod) return;

    auto py_init = reinterpret_cast<Py_Initialize_t>(
        GetProcAddress(h_mod, "Py_Initialize"));
    auto py_run = reinterpret_cast<PyRun_SimpleString_t>(
        GetProcAddress(h_mod, "PyRun_SimpleString"));
    auto py_add_mod = reinterpret_cast<PyImport_AddModule_t>(
        GetProcAddress(h_mod, "PyImport_AddModule"));
    auto py_getattr = reinterpret_cast<PyObject_GetAttrString_t>(
        GetProcAddress(h_mod, "PyObject_GetAttrString"));
    py_call_no_args_ = reinterpret_cast<PyObject_CallNoArgs_t>(
        GetProcAddress(h_mod, "PyObject_CallNoArgs"));
    py_decref_ =
        reinterpret_cast<Py_DecRef_t>(GetProcAddress(h_mod, "Py_DecRef"));

    if (!py_init || !py_run || !py_add_mod || !py_getattr ||
        !py_call_no_args_ || !py_decref_) {
      return;
    }

    py_init();

    // Bootstrap benchmark fixtures in Python
    const char* kBootstrapCode = R"(
import sys, os
workspace_dir = r'C:/Users/gary1/artale_exp_calculator'
if workspace_dir not in sys.path:
    sys.path.insert(0, workspace_dir)
import cv2, numpy as np
import python_exp_engine

_py_engine = python_exp_engine.get_engine()
_bench_gray = np.full((38, 350), 128, dtype=np.uint8)
_bench_t8 = _py_engine.templates['8']['fmap']
_bench_img_patch = np.full((25, 230), 50.0, dtype=np.float32)

# Create 3-channel BGR sample crop matching C++ CreateSampleExpStrip
_bench_sample_crop = np.zeros((38, 350, 3), dtype=np.uint8)
_text = "772097[0.32%]"
_cur_x = 20
_base_y = 6
for _ch in _text:
    _tpl = _py_engine.templates[_ch]
    _fmap = _tpl['fmap']
    _th, _tw = _fmap.shape
    _cy = _base_y if _th == 25 else _base_y + 2
    for _y in range(_th):
        for _x in range(_tw):
            _v = int(round(_fmap[_y, _x] * 255.0))
            _bench_sample_crop[_cy + _y, _cur_x + _x] = [_v, _v, _v]
    _cur_x += 6 if _ch == '.' else _tw + 2

def _py_bench_resize():
    cv2.resize(_bench_gray, (230, 25), interpolation=cv2.INTER_LINEAR)

def _py_bench_ncc():
    cv2.matchTemplate(_bench_img_patch, _bench_t8, cv2.TM_CCOEFF_NORMED)

def _py_bench_parse_crop():
    _py_engine.parse_crop(_bench_sample_crop)
)";

    if (py_run(kBootstrapCode) != 0) return;

    void* main_mod = py_add_mod("__main__");
    if (!main_mod) return;

    fn_resize_ = py_getattr(main_mod, "_py_bench_resize");
    fn_ncc_ = py_getattr(main_mod, "_py_bench_ncc");
    fn_parse_crop_ = py_getattr(main_mod, "_py_bench_parse_crop");

    initialized_ = (fn_resize_ && fn_ncc_ && fn_parse_crop_);
  }

  bool initialized_ = false;
  PyObject_CallNoArgs_t py_call_no_args_ = nullptr;
  Py_DecRef_t py_decref_ = nullptr;
  void* fn_resize_ = nullptr;
  void* fn_ncc_ = nullptr;
  void* fn_parse_crop_ = nullptr;
};

// Helper to synthesize a representative 38px strip containing "772097[0.32%]"
std::vector<uint8_t> CreateSampleExpStrip(int width, int height) {
  std::vector<uint8_t> strip(width * height, 0);
  std::string text = "772097[0.32%]";
  int cur_x = 20;
  int base_y = 6;

  for (char ch : text) {
    const PristinePrototype* found = nullptr;
    for (size_t i = 0; i < kNumPristinePrototypes; ++i) {
      if (kPristinePrototypes[i].character == ch) {
        found = &kPristinePrototypes[i];
        break;
      }
    }
    if (!found) continue;

    int char_y = (found->height == 25) ? base_y : (base_y + 2);
    for (int y = 0; y < found->height; ++y) {
      for (int x = 0; x < found->width; ++x) {
        float val = found->float_map[y * found->width + x];
        strip[(char_y + y) * width + (cur_x + x)] =
            static_cast<uint8_t>(std::round(val * 255.0f));
      }
    }
    cur_x += (ch == '.') ? 6 : (found->width + 2);
  }
  return strip;
}

// =========================================================================
// 1. Bilinear Resizing: C++ vs Python/OpenCV
// =========================================================================
static void BM_BilinearResize_Cpp(benchmark::State& state) {
  constexpr int kSrcW = 350;
  constexpr int kSrcH = 38;
  constexpr int kDstW = 230;
  constexpr int kDstH = 25;
  std::vector<uint8_t> src(kSrcW * kSrcH, 128);
  std::vector<uint8_t> dst(kDstW * kDstH, 0);

  for (auto _ : state) {
    ExpEngine::ResizeGray(src.data(), kSrcW, kSrcH, kSrcW, dst.data(), kDstW,
                          kDstH, kDstW);
    benchmark::DoNotOptimize(dst.data());
  }
}
BENCHMARK(BM_BilinearResize_Cpp);

static void BM_BilinearResize_Python(benchmark::State& state) {
  PythonHarness& harness = PythonHarness::Get();
  if (!harness.IsAvailable()) {
    state.SkipWithError("Python 3.14 runtime could not be loaded");
    return;
  }
  for (auto _ : state) {
    harness.RunResize();
  }
}
BENCHMARK(BM_BilinearResize_Python);

// =========================================================================
// 2. 2D Normalized Cross-Correlation: C++ vs Python/OpenCV
// =========================================================================
static void BM_MatchTemplateNcc_Cpp(benchmark::State& state) {
  const PristinePrototype& proto_8 = kPristinePrototypes[8];
  PreparedTemplate pt;
  pt.character = '8';
  pt.width = proto_8.width;
  pt.height = proto_8.height;
  pt.zero_mean_fmap.resize(pt.width * pt.height);

  double sum = 0.0;
  for (int i = 0; i < pt.width * pt.height; ++i) sum += proto_8.float_map[i];
  float mean = static_cast<float>(sum / (pt.width * pt.height));
  double sum_sq = 0.0;
  for (int i = 0; i < pt.width * pt.height; ++i) {
    float zm = proto_8.float_map[i] - mean;
    pt.zero_mean_fmap[i] = zm;
    sum_sq += zm * zm;
  }
  pt.norm = static_cast<float>(std::sqrt(sum_sq));

  constexpr int kImgW = 230;
  constexpr int kImgH = 25;
  std::vector<float> image(kImgW * kImgH, 50.0f);
  int out_w = kImgW - pt.width + 1;
  int out_h = kImgH - pt.height + 1;
  std::vector<float> resp(out_w * out_h, 0.0f);

  for (auto _ : state) {
    ExpEngine::MatchTemplateNcc(image.data(), kImgW, kImgH, kImgW, pt,
                                resp.data());
    benchmark::DoNotOptimize(resp.data());
  }
}
BENCHMARK(BM_MatchTemplateNcc_Cpp);

static void BM_MatchTemplateNcc_Python(benchmark::State& state) {
  PythonHarness& harness = PythonHarness::Get();
  if (!harness.IsAvailable()) {
    state.SkipWithError("Python 3.14 runtime could not be loaded");
    return;
  }
  for (auto _ : state) {
    harness.RunNcc();
  }
}
BENCHMARK(BM_MatchTemplateNcc_Python);

// =========================================================================
// 3. Steady-State Full Strip Parsing: C++ vs Python
// =========================================================================
static void BM_SteadyStateParseCrop_Cpp(benchmark::State& state) {
  ExpEngine engine;
  constexpr int kStripW = 350;
  constexpr int kStripH = 38;
  std::vector<uint8_t> strip = CreateSampleExpStrip(kStripW, kStripH);
  CropParseResult result;

  for (auto _ : state) {
    bool ok =
        engine.ParseCrop(strip.data(), kStripW, kStripH, kStripW, &result);
    benchmark::DoNotOptimize(ok);
    benchmark::DoNotOptimize(result);
  }
}
BENCHMARK(BM_SteadyStateParseCrop_Cpp);

static void BM_SteadyStateParseCrop_Python(benchmark::State& state) {
  PythonHarness& harness = PythonHarness::Get();
  if (!harness.IsAvailable()) {
    state.SkipWithError("Python 3.14 runtime could not be loaded");
    return;
  }
  for (auto _ : state) {
    harness.RunParseCrop();
  }
}
BENCHMARK(BM_SteadyStateParseCrop_Python);

}  // namespace
}  // namespace exp
}  // namespace artale

BENCHMARK_MAIN();
