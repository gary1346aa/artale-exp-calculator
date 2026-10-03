// Copyright 2026 Artale Exp Project. All rights reserved.
// Google C++ Style Guide compliant.

#include "src/cpp/src/exp_engine_scalar.h"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <vector>

#if defined(__SSE2__) || defined(_M_X64) || defined(__x86_64__)
#include <emmintrin.h>
#endif

namespace artale {
namespace exp {

namespace {

inline int CvRound(float value) {
#if defined(__SSE2__) || defined(_M_X64) || defined(__x86_64__)
  return _mm_cvtss_si32(_mm_set_ss(value));
#elif defined(__aarch64__) || defined(__ARM_NEON)
  return static_cast<int>(std::lrintf(value));
#else
  int i = static_cast<int>(std::floor(value));
  float diff = value - i;
  if (diff > 0.5f) return i + 1;
  if (diff < 0.5f) return i;
  return (i % 2 == 0) ? i : i + 1;
#endif
}

}  // namespace

void ResizeGrayScalar(const uint8_t* src, int src_w, int src_h, int src_stride,
                      uint8_t* dst, int dst_w, int dst_h, int dst_stride) {
  if (src_w <= 0 || src_h <= 0 || dst_w <= 0 || dst_h <= 0) return;

  constexpr int kShift = 11;
  constexpr int kScale = 1 << kShift;

  std::vector<int> xofs(dst_w * 2);
  std::vector<int16_t> ialpha(dst_w * 2);
  const double scale_x = static_cast<double>(src_w) / dst_w;

  for (int dx = 0; dx < dst_w; ++dx) {
    float fx = static_cast<float>((dx + 0.5) * scale_x - 0.5);
    int sx = static_cast<int>(std::floor(fx));
    fx -= sx;
    if (sx < 0) {
      fx = 0.0f;
      sx = 0;
    }
    if (sx >= src_w - 1) {
      fx = 0.0f;
      sx = src_w - 1;
    }
    xofs[dx * 2 + 0] = sx;
    xofs[dx * 2 + 1] = std::min(sx + 1, src_w - 1);
    float c0 = 1.0f - fx;
    float c1 = fx;
    ialpha[dx * 2 + 0] = static_cast<int16_t>(CvRound(c0 * kScale));
    ialpha[dx * 2 + 1] = static_cast<int16_t>(CvRound(c1 * kScale));
  }

  std::vector<int> yofs(dst_h);
  std::vector<int16_t> ibeta(dst_h * 2);
  const double scale_y = static_cast<double>(src_h) / dst_h;

  for (int dy = 0; dy < dst_h; ++dy) {
    float fy = static_cast<float>((dy + 0.5) * scale_y - 0.5);
    int sy = static_cast<int>(std::floor(fy));
    fy -= sy;
    yofs[dy] = sy;
    float c0 = 1.0f - fy;
    float c1 = fy;
    ibeta[dy * 2 + 0] = static_cast<int16_t>(CvRound(c0 * kScale));
    ibeta[dy * 2 + 1] = static_cast<int16_t>(CvRound(c1 * kScale));
  }

  for (int dy = 0; dy < dst_h; ++dy) {
    int sy = yofs[dy];
    int sy0 = std::max(0, std::min(sy, src_h - 1));
    int sy1 = std::max(0, std::min(sy + 1, src_h - 1));
    int32_t b0 = ibeta[dy * 2 + 0];
    int32_t b1 = ibeta[dy * 2 + 1];

    const uint8_t* row0 = src + sy0 * src_stride;
    const uint8_t* row1 = src + sy1 * src_stride;
    uint8_t* dst_row = dst + dy * dst_stride;

    for (int dx = 0; dx < dst_w; ++dx) {
      int sx0 = xofs[dx * 2 + 0];
      int sx1 = xofs[dx * 2 + 1];
      int32_t a0 = ialpha[dx * 2 + 0];
      int32_t a1 = ialpha[dx * 2 + 1];

      int32_t s0 = static_cast<int32_t>(row0[sx0]) * a0 + static_cast<int32_t>(row0[sx1]) * a1;
      int32_t s1 = static_cast<int32_t>(row1[sx0]) * a0 + static_cast<int32_t>(row1[sx1]) * a1;

      int32_t val = (((b0 * (s0 >> 4)) >> 16) + ((b1 * (s1 >> 4)) >> 16) + 2) >> 2;
      dst_row[dx] = static_cast<uint8_t>(std::max(0, std::min(255, val)));
    }
  }
}

void MatchTemplateNccScalar(const float* image, int img_w, int img_h, int img_stride,
                            const PreparedTemplate& tpl, float* out_response) {
  const int tw = tpl.width;
  const int th = tpl.height;
  const int out_w = img_w - tw + 1;
  const int out_h = img_h - th + 1;
  if (out_w <= 0 || out_h <= 0) return;

  const float tpl_norm = tpl.norm;
  if (tpl_norm <= 1e-6f) {
    std::fill(out_response, out_response + out_w * out_h, 0.0f);
    return;
  }

  const double inv_pixels = 1.0 / (tw * th);
  std::vector<double> col_sum(img_w, 0.0);
  std::vector<double> col_sum2(img_w, 0.0);
  std::vector<double> pref_i(img_w + 1, 0.0);
  std::vector<double> pref_i2(img_w + 1, 0.0);
  std::vector<float> inv_norm(out_w, 0.0f);

  for (int y = 0; y < out_h; ++y) {
    float* resp_row = out_response + y * out_w;
    if (y == 0) {
      for (int r = 0; r < th; ++r) {
        const float* img_row = image + r * img_stride;
        for (int c = 0; c < img_w; ++c) {
          double val = static_cast<double>(img_row[c]);
          col_sum[c] += val;
          col_sum2[c] = std::fma(val, val, col_sum2[c]);
        }
      }
    } else {
      const float* row_sub = image + (y - 1) * img_stride;
      const float* row_add = image + (y + th - 1) * img_stride;
      for (int c = 0; c < img_w; ++c) {
        double vs = static_cast<double>(row_sub[c]);
        double va = static_cast<double>(row_add[c]);
        col_sum[c] += (va - vs);
        col_sum2[c] += (va * va - vs * vs);
      }
    }

    pref_i[0] = 0.0;
    pref_i2[0] = 0.0;
    for (int c = 0; c < img_w; ++c) {
      pref_i[c + 1] = pref_i[c] + col_sum[c];
      pref_i2[c + 1] = pref_i2[c] + col_sum2[c];
    }

    for (int nx = 0; nx < out_w; ++nx) {
      double sum_i = pref_i[nx + tw] - pref_i[nx];
      double sum_i2 = pref_i2[nx + tw] - pref_i2[nx];
      double var_i = std::fma(-(sum_i * sum_i), inv_pixels, sum_i2);
      if (var_i <= 1e-5) {
        inv_norm[nx] = 0.0f;
      } else {
        inv_norm[nx] = static_cast<float>(1.0 / (tpl_norm * std::sqrt(var_i)));
      }
    }

    for (int x = 0; x < out_w; ++x) {
      float acc = 0.0f;
      float acc_b = 0.0f;
      const float* t_ptr = tpl.zero_mean_fmap.data();
      for (int r = 0; r < th; ++r) {
        const float* img_row = image + (y + r) * img_stride + x;
        int c = 0;
        for (; c + 1 < tw; c += 2) {
          acc = std::fmaf(t_ptr[c], img_row[c], acc);
          acc_b = std::fmaf(t_ptr[c + 1], img_row[c + 1], acc_b);
        }
        for (; c < tw; ++c) {
          acc = std::fmaf(t_ptr[c], img_row[c], acc);
        }
        t_ptr += tw;
      }
      float sum_it = acc + acc_b;
      float ncc = sum_it * inv_norm[x];
      resp_row[x] = std::max(-1.0f, std::min(1.0f, ncc));
    }
  }
}

}  // namespace exp
}  // namespace artale
