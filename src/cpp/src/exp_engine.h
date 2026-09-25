// Copyright 2026 Artale Exp Project. All rights reserved.
// Google C++ Style Guide compliant.

#ifndef ARTALE_EXP_CORE_EXP_ENGINE_H_
#define ARTALE_EXP_CORE_EXP_ENGINE_H_

#include <cstddef>
#include <cstdint>
#include <memory>
#include <string>
#include <unordered_map>
#include <vector>

#include "src/cpp/src/pristine_font_protos.h"

namespace artale {
namespace exp {

// Represents a recognized character with its horizontal position and NCC score.
struct RecognizedChar {
  int x;
  char character;
  float ncc;
};

// Result of parsing an EXP crop.
struct CropParseResult {
  bool success = false;
  int64_t exp_value = 0;
  double exp_percent = 0.0;
  std::string raw_string;
  float parse_time_ms = 0.0f;
  std::vector<RecognizedChar> characters;
};

// Internal preprocessed template representation for NCC evaluation.
struct PreparedTemplate {
  char character;
  int width;
  int height;
  std::vector<float> zero_mean_fmap;
  float norm;
};

// Core EXP recognition engine implementing multi-scale dual-template sizing,
// vertical-jitter NCC response maps, and grammar-constrained DP beam search.
class ExpEngine {
 public:
  ExpEngine();
  ~ExpEngine() = default;

  // Non-copyable, non-movable.
  ExpEngine(const ExpEngine&) = delete;
  ExpEngine& operator=(const ExpEngine&) = delete;

  // Parses a grayscale EXP crop (typically ~20 to ~60 px in height).
  // Returns false if no valid EXP bar was recognized.
  bool ParseCrop(const uint8_t* gray_crop, int width, int height, int stride,
                 CropParseResult* out_result) const;

  // Bilinear interpolation for grayscale image matching OpenCV's
  // cv2.INTER_LINEAR.
  static void ResizeGray(const uint8_t* src, int src_w, int src_h, int src_stride, uint8_t* dst,
                         int dst_w, int dst_h, int dst_stride);

  // Pure scalar reference implementation of bilinear interpolation for
  // bit-exact verification.
  static void ResizeGrayScalar(const uint8_t* src, int src_w, int src_h, int src_stride,
                               uint8_t* dst, int dst_w, int dst_h, int dst_stride);

  // Computes sliding-window normalized cross correlation (TM_CCOEFF_NORMED)
  // for a 2D float patch against a prepared zero-mean template.
  static void MatchTemplateNcc(const float* image, int img_w, int img_h, int img_stride,
                               const PreparedTemplate& tpl, float* out_response);

  const std::unordered_map<char, PreparedTemplate>& templates() const {
    return prepared_templates_;
  }

 private:
  void InitializeTemplates();

  std::unordered_map<char, PreparedTemplate> prepared_templates_;
};

}  // namespace exp
}  // namespace artale

#endif  // ARTALE_EXP_CORE_EXP_ENGINE_H_
