// Copyright 2026 Artale Exp Project. All rights reserved.
// Google C++ Style Guide compliant.

#include "src/cpp/include/artale_exp_core.h"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <memory>
#include <mutex>
#include <vector>

#include "src/cpp/src/exp_engine.h"
#include "src/cpp/src/real_exp_logo_data.h"

namespace artale {
namespace exp {

namespace {

// Reference constants for 4K reference coordinate system where logo was
// captured.
constexpr float kRefDisplayWidth = 3840.0f;
constexpr float kRefDisplayHeight = 2160.0f;
constexpr float kMinLogoScale = 0.24f;
constexpr float kMaxLogoScale = 1.45f;
constexpr float kLogoMatchThreshold = 0.50f;
constexpr int kNumLogoScales = 16;

struct BoundingBox {
  int x = 0;
  int y = 0;
  int w = 0;
  int h = 0;
};

// Global state holding cached bounding boxes for steady-state parsing.
struct EngineState {
  std::mutex mutex;
  ExpEngine engine;
  int last_frame_width = 0;
  int last_frame_height = 0;
  bool has_cached_crop = false;
  BoundingBox cached_crop_box;
  BoundingBox cached_logo_box;
};

EngineState& GetEngineState() {
  static EngineState state;
  return state;
}

// Converts a BGR/BGRA frame into an 8-bit grayscale sub-rectangle.
void ExtractGraySubRect(const uint8_t* bgr_data, int width, int height,
                        int stride, int bytes_per_px, int rx, int ry, int rw,
                        int rh, uint8_t* out_gray) {
  for (int y = 0; y < rh; ++y) {
    int src_y = ry + y;
    if (src_y < 0 || src_y >= height) continue;
    const uint8_t* src_row = bgr_data + src_y * stride;
    uint8_t* dst_row = out_gray + y * rw;

    for (int x = 0; x < rw; ++x) {
      int src_x = rx + x;
      if (src_x < 0 || src_x >= width) continue;
      const uint8_t* px = src_row + src_x * bytes_per_px;
      // Exact OpenCV BGR2GRAY integer formula: (B*3735 + G*19235 + R*9798 +
      // 16384) >> 15
      uint32_t b = px[0];
      uint32_t g = px[1];
      uint32_t r = px[2];
      dst_row[x] =
          static_cast<uint8_t>((b * 3735 + g * 19235 + r * 9798 + 16384) >> 15);
    }
  }
}

// Locates the EXP logo in the bottom strip of the frame using multi-scale
// template matching.
bool LocateExpLogo(const uint8_t* bgr_data, int width, int height, int stride,
                   int bytes_per_px, BoundingBox* out_logo_box) {
  int strip_h =
      std::min(height, std::max(80, static_cast<int>(height * 0.15f)));
  int strip_y = std::max(0, height - strip_h);
  int strip_w = width;
  if (strip_w < 50 || strip_h < 20) return false;

  std::vector<uint8_t> strip_gray(strip_w * strip_h);
  ExtractGraySubRect(bgr_data, width, height, stride, bytes_per_px, 0, strip_y,
                     strip_w, strip_h, strip_gray.data());

  std::vector<float> strip_float(strip_w * strip_h);
  for (size_t i = 0; i < strip_gray.size(); ++i) {
    strip_float[i] = static_cast<float>(strip_gray[i]);
  }

  // Calculate resolution-guided center scale
  float s_center =
      std::min(width / kRefDisplayWidth, height / kRefDisplayHeight);
  float s_min = std::max(kMinLogoScale, s_center * 0.65f);
  float s_max = std::min(kMaxLogoScale, s_center * 1.35f);

  float best_score = -1.0f;
  int best_x = 0;
  int best_y = 0;
  int best_tw = 0;
  int best_th = 0;

  std::vector<uint8_t> tpl_resized_u8;
  std::vector<float> resp_buf;

  for (int s_idx = 0; s_idx < kNumLogoScales; ++s_idx) {
    float cs = s_min + (s_max - s_min) *
                           (static_cast<float>(s_idx) / (kNumLogoScales - 1));
    int tw = static_cast<int>(std::round(kExpLogoWidth * cs));
    int th = static_cast<int>(std::round(kExpLogoHeight * cs));
    if (tw <= 4 || th <= 4 || th >= strip_h || tw >= strip_w) continue;

    tpl_resized_u8.resize(tw * th);
    ExpEngine::ResizeGray(kExpLogoGrayData, kExpLogoWidth, kExpLogoHeight,
                          kExpLogoWidth, tpl_resized_u8.data(), tw, th, tw);

    PreparedTemplate pt;
    pt.character = 'L';
    pt.width = tw;
    pt.height = th;
    pt.zero_mean_fmap.resize(tw * th);

    double sum = 0.0;
    for (int j = 0; j < tw * th; ++j) sum += tpl_resized_u8[j];
    float mean = static_cast<float>(sum / (tw * th));

    double sum_sq = 0.0;
    for (int j = 0; j < tw * th; ++j) {
      float zm = tpl_resized_u8[j] - mean;
      pt.zero_mean_fmap[j] = zm;
      sum_sq += zm * zm;
    }
    pt.norm = static_cast<float>(std::sqrt(sum_sq));

    int out_w = strip_w - tw + 1;
    int out_h = strip_h - th + 1;
    if (out_w <= 0 || out_h <= 0) continue;
    resp_buf.resize(out_w * out_h);

    ExpEngine::MatchTemplateNcc(strip_float.data(), strip_w, strip_h, strip_w,
                                pt, resp_buf.data());

    for (int y = 0; y < out_h; ++y) {
      for (int x = 0; x < out_w; ++x) {
        float val = resp_buf[y * out_w + x];
        if (val > best_score) {
          best_score = val;
          best_x = x;
          best_y = strip_y + y;
          best_tw = tw;
          best_th = th;
        }
      }
    }
  }

  if (best_score < 0.65f) {
    return false;
  }

  out_logo_box->x = best_x;
  out_logo_box->y = best_y;
  out_logo_box->w = best_tw;
  out_logo_box->h = best_th;
  return true;
}

}  // namespace
}  // namespace exp
}  // namespace artale

extern "C" {

ARTALE_API int ParseExpFromBuffer(const uint8_t* bgr_data, int width,
                                  int height, int stride, int bytes_per_px,
                                  ExpResult* out_result) {
  if (bgr_data == nullptr || width <= 0 || height <= 0 || stride <= 0 ||
      out_result == nullptr) {
    return -1;
  }

  auto t_start = std::chrono::steady_clock::now();
  std::memset(out_result, 0, sizeof(ExpResult));
  out_result->exp_percent = -1.0;

  auto& state = artale::exp::GetEngineState();
  std::lock_guard<std::mutex> lock(state.mutex);

  // If the input buffer is already a tight crop (height <= 60), parse directly
  if (height <= 60) {
    std::vector<uint8_t> crop_gray(width * height);
    artale::exp::ExtractGraySubRect(bgr_data, width, height, stride,
                                    bytes_per_px, 0, 0, width, height,
                                    crop_gray.data());
    artale::exp::CropParseResult crop_res;
    if (state.engine.ParseCrop(crop_gray.data(), width, height, width,
                               &crop_res)) {
      auto t_end = std::chrono::steady_clock::now();
      float dt_ms =
          std::chrono::duration<float, std::milli>(t_end - t_start).count();

      out_result->success = 1;
      out_result->exp_value = crop_res.exp_value;
      out_result->exp_percent = crop_res.exp_percent;
      out_result->parse_time_ms = dt_ms;
      std::strncpy(out_result->exp_string, crop_res.raw_string.c_str(),
                   sizeof(out_result->exp_string) - 1);
      out_result->crop_x = 0;
      out_result->crop_y = 0;
      out_result->crop_w = width;
      out_result->crop_h = height;
      return 0;
    }
    return 0;
  }

  // Invalidate cache if resolution changed
  if (state.last_frame_width != width || state.last_frame_height != height) {
    state.has_cached_crop = false;
    state.last_frame_width = width;
    state.last_frame_height = height;
  }

  artale::exp::CropParseResult crop_res;
  artale::exp::BoundingBox text_box;
  artale::exp::BoundingBox logo_box;

  // 1. Fast steady-state path: reuse cached crop coordinates
  if (state.has_cached_crop) {
    text_box = state.cached_crop_box;
    logo_box = state.cached_logo_box;

    if (text_box.y + text_box.h <= height && text_box.x + text_box.w <= width) {
      std::vector<uint8_t> crop_gray(text_box.w * text_box.h);
      artale::exp::ExtractGraySubRect(bgr_data, width, height, stride,
                                      bytes_per_px, text_box.x, text_box.y,
                                      text_box.w, text_box.h, crop_gray.data());

      if (state.engine.ParseCrop(crop_gray.data(), text_box.w, text_box.h,
                                 text_box.w, &crop_res)) {
        auto t_end = std::chrono::steady_clock::now();
        float dt_ms =
            std::chrono::duration<float, std::milli>(t_end - t_start).count();

        out_result->success = 1;
        out_result->exp_value = crop_res.exp_value;
        out_result->exp_percent = crop_res.exp_percent;
        out_result->parse_time_ms = dt_ms;
        std::strncpy(out_result->exp_string, crop_res.raw_string.c_str(),
                     sizeof(out_result->exp_string) - 1);
        out_result->crop_x = text_box.x;
        out_result->crop_y = text_box.y;
        out_result->crop_w = text_box.w;
        out_result->crop_h = text_box.h;
        out_result->logo_x = logo_box.x;
        out_result->logo_y = logo_box.y;
        out_result->logo_w = logo_box.w;
        out_result->logo_h = logo_box.h;
        return 0;
      }
    }
  }

  // 2. Cold path: locate logo across ROI
  if (!artale::exp::LocateExpLogo(bgr_data, width, height, stride, bytes_per_px,
                                  &logo_box)) {
    state.has_cached_crop = false;
    return 0;
  }

  // Derive text bounding box exactly as in exp_core.py:
  // crop_x = best_lx + best_tw
  // crop_y = strip_y + best_ly (stored in logo_box.y)
  // crop_w = int(best_th * 9.5)
  // crop_h = best_th
  text_box.x = logo_box.x + logo_box.w;
  text_box.y = logo_box.y;
  text_box.w = static_cast<int>(logo_box.h * 9.5f);
  text_box.h = logo_box.h;

  if (text_box.x + text_box.w > width) text_box.w = width - text_box.x;
  if (text_box.y + text_box.h > height) text_box.h = height - text_box.y;

  if (text_box.w < 10 || text_box.h < 10) {
    state.has_cached_crop = false;
    return 0;
  }

  std::vector<uint8_t> crop_gray(text_box.w * text_box.h);
  artale::exp::ExtractGraySubRect(bgr_data, width, height, stride, bytes_per_px,
                                  text_box.x, text_box.y, text_box.w,
                                  text_box.h, crop_gray.data());

  if (state.engine.ParseCrop(crop_gray.data(), text_box.w, text_box.h,
                             text_box.w, &crop_res)) {
    state.has_cached_crop = true;
    state.cached_crop_box = text_box;
    state.cached_logo_box = logo_box;

    auto t_end = std::chrono::steady_clock::now();
    float dt_ms =
        std::chrono::duration<float, std::milli>(t_end - t_start).count();

    out_result->success = 1;
    out_result->exp_value = crop_res.exp_value;
    out_result->exp_percent = crop_res.exp_percent;
    out_result->parse_time_ms = dt_ms;
    std::strncpy(out_result->exp_string, crop_res.raw_string.c_str(),
                 sizeof(out_result->exp_string) - 1);
    out_result->crop_x = text_box.x;
    out_result->crop_y = text_box.y;
    out_result->crop_w = text_box.w;
    out_result->crop_h = text_box.h;
    out_result->logo_x = logo_box.x;
    out_result->logo_y = logo_box.y;
    out_result->logo_w = logo_box.w;
    out_result->logo_h = logo_box.h;
    return 0;
  }

  state.has_cached_crop = false;
  return 0;
}

void Test_ExtractGraySubRect(const uint8_t* bgr_data, int width, int height,
                             int stride, int bytes_per_px, int rx, int ry,
                             int rw, int rh, uint8_t* out_gray) {
  artale::exp::ExtractGraySubRect(bgr_data, width, height, stride, bytes_per_px,
                                  rx, ry, rw, rh, out_gray);
}

void Test_ResizeGray(const uint8_t* src, int src_w, int src_h, int src_stride,
                     uint8_t* dst, int dst_w, int dst_h, int dst_stride) {
  artale::exp::ExpEngine::ResizeGray(src, src_w, src_h, src_stride, dst, dst_w,
                                     dst_h, dst_stride);
}

void Test_ResizeGrayScalar(const uint8_t* src, int src_w, int src_h,
                           int src_stride, uint8_t* dst, int dst_w, int dst_h,
                           int dst_stride) {
  artale::exp::ExpEngine::ResizeGrayScalar(src, src_w, src_h, src_stride, dst,
                                           dst_w, dst_h, dst_stride);
}

int Test_MatchTemplateNcc(const float* image, int img_w, int img_h,
                          int img_stride, char ch, float* out_response) {
  static const artale::exp::ExpEngine engine;
  const auto& templates = engine.templates();
  auto it = templates.find(ch);
  if (it == templates.end()) return -1;
  artale::exp::ExpEngine::MatchTemplateNcc(image, img_w, img_h, img_stride,
                                           it->second, out_response);
  return 0;
}

}  // extern "C"
