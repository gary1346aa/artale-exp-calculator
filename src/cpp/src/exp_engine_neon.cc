// Copyright 2026 Artale Exp Project. All rights reserved.
// Google C++ Style Guide compliant.

#include "src/cpp/src/exp_engine_neon.h"

#if defined(__ARM_NEON) || defined(__aarch64__)

#include <arm_neon.h>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <vector>

namespace artale {
namespace exp {

namespace {

inline int CvRound(float value) {
  return static_cast<int>(std::lrintf(value));
}

}  // namespace

void ResizeGrayNEON(const uint8_t* src, int src_w, int src_h, int src_stride,
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

    int dx = 0;
    const int16x8_t vb0 = vdupq_n_s16(static_cast<int16_t>(b0));
    const int16x8_t vb1 = vdupq_n_s16(static_cast<int16_t>(b1));
    const int32x4_t vtwo = vdupq_n_s32(2);

    for (; dx + 16 <= dst_w && xofs[(dx + 15) * 2 + 0] < src_w - 1; dx += 16) {
      alignas(16) uint16_t w0_0[8];
      alignas(16) uint16_t w1_0[8];
      alignas(16) uint16_t w0_1[8];
      alignas(16) uint16_t w1_1[8];
      const int* pxofs0 = xofs.data() + dx * 2;
      const int* pxofs1 = xofs.data() + (dx + 8) * 2;
      for (int k = 0; k < 8; ++k) {
        w0_0[k] = *reinterpret_cast<const uint16_t*>(row0 + pxofs0[k * 2]);
        w1_0[k] = *reinterpret_cast<const uint16_t*>(row1 + pxofs0[k * 2]);
        w0_1[k] = *reinterpret_cast<const uint16_t*>(row0 + pxofs1[k * 2]);
        w1_1[k] = *reinterpret_cast<const uint16_t*>(row1 + pxofs1[k * 2]);
      }

      uint8x16_t r0_0_u8 = vld1q_u8(reinterpret_cast<const uint8_t*>(w0_0));
      uint8x16_t r1_0_u8 = vld1q_u8(reinterpret_cast<const uint8_t*>(w1_0));
      int16x8_t r0_0_lo = vreinterpretq_s16_u16(vmovl_u8(vget_low_u8(r0_0_u8)));
      int16x8_t r0_0_hi = vreinterpretq_s16_u16(vmovl_u8(vget_high_u8(r0_0_u8)));
      int16x8_t r1_0_lo = vreinterpretq_s16_u16(vmovl_u8(vget_low_u8(r1_0_u8)));
      int16x8_t r1_0_hi = vreinterpretq_s16_u16(vmovl_u8(vget_high_u8(r1_0_u8)));

      int16x8_t a0_lo = vld1q_s16(ialpha.data() + dx * 2);
      int16x8_t a0_hi = vld1q_s16(ialpha.data() + dx * 2 + 8);

      int32x4_t s0_0_lo =
          vshrq_n_s32(vpaddq_s32(vmull_s16(vget_low_s16(r0_0_lo), vget_low_s16(a0_lo)),
                                 vmull_s16(vget_high_s16(r0_0_lo), vget_high_s16(a0_lo))),
                      4);
      int32x4_t s0_0_hi =
          vshrq_n_s32(vpaddq_s32(vmull_s16(vget_low_s16(r0_0_hi), vget_low_s16(a0_hi)),
                                 vmull_s16(vget_high_s16(r0_0_hi), vget_high_s16(a0_hi))),
                      4);

      int32x4_t s1_0_lo =
          vshrq_n_s32(vpaddq_s32(vmull_s16(vget_low_s16(r1_0_lo), vget_low_s16(a0_lo)),
                                 vmull_s16(vget_high_s16(r1_0_lo), vget_high_s16(a0_lo))),
                      4);
      int32x4_t s1_0_hi =
          vshrq_n_s32(vpaddq_s32(vmull_s16(vget_low_s16(r1_0_hi), vget_low_s16(a0_hi)),
                                 vmull_s16(vget_high_s16(r1_0_hi), vget_high_s16(a0_hi))),
                      4);

      int16x8_t s0_0_16 = vcombine_s16(vqmovn_s32(s0_0_lo), vqmovn_s32(s0_0_hi));
      int16x8_t s1_0_16 = vcombine_s16(vqmovn_s32(s1_0_lo), vqmovn_s32(s1_0_hi));

      int32x4_t t0_0_lo = vshrq_n_s32(vmull_s16(vget_low_s16(s0_0_16), vget_low_s16(vb0)), 16);
      int32x4_t t1_0_lo = vshrq_n_s32(vmull_s16(vget_low_s16(s1_0_16), vget_low_s16(vb1)), 16);
      int32x4_t val0_lo = vshrq_n_s32(vaddq_s32(vaddq_s32(t0_0_lo, t1_0_lo), vtwo), 2);

      int32x4_t t0_0_hi = vshrq_n_s32(vmull_s16(vget_high_s16(s0_0_16), vget_high_s16(vb0)), 16);
      int32x4_t t1_0_hi = vshrq_n_s32(vmull_s16(vget_high_s16(s1_0_16), vget_high_s16(vb1)), 16);
      int32x4_t val0_hi = vshrq_n_s32(vaddq_s32(vaddq_s32(t0_0_hi, t1_0_hi), vtwo), 2);

      uint8x8_t res0 = vqmovun_s16(vcombine_s16(vqmovn_s32(val0_lo), vqmovn_s32(val0_hi)));

      // Block 1: pixels dx+8..dx+15
      uint8x16_t r0_1_u8 = vld1q_u8(reinterpret_cast<const uint8_t*>(w0_1));
      uint8x16_t r1_1_u8 = vld1q_u8(reinterpret_cast<const uint8_t*>(w1_1));
      int16x8_t r0_1_lo = vreinterpretq_s16_u16(vmovl_u8(vget_low_u8(r0_1_u8)));
      int16x8_t r0_1_hi = vreinterpretq_s16_u16(vmovl_u8(vget_high_u8(r0_1_u8)));
      int16x8_t r1_1_lo = vreinterpretq_s16_u16(vmovl_u8(vget_low_u8(r1_1_u8)));
      int16x8_t r1_1_hi = vreinterpretq_s16_u16(vmovl_u8(vget_high_u8(r1_1_u8)));

      int16x8_t a1_lo = vld1q_s16(ialpha.data() + (dx + 8) * 2);
      int16x8_t a1_hi = vld1q_s16(ialpha.data() + (dx + 8) * 2 + 8);

      int32x4_t s0_1_lo =
          vshrq_n_s32(vpaddq_s32(vmull_s16(vget_low_s16(r0_1_lo), vget_low_s16(a1_lo)),
                                 vmull_s16(vget_high_s16(r0_1_lo), vget_high_s16(a1_lo))),
                      4);
      int32x4_t s0_1_hi =
          vshrq_n_s32(vpaddq_s32(vmull_s16(vget_low_s16(r0_1_hi), vget_low_s16(a1_hi)),
                                 vmull_s16(vget_high_s16(r0_1_hi), vget_high_s16(a1_hi))),
                      4);

      int32x4_t s1_1_lo =
          vshrq_n_s32(vpaddq_s32(vmull_s16(vget_low_s16(r1_1_lo), vget_low_s16(a1_lo)),
                                 vmull_s16(vget_high_s16(r1_1_lo), vget_high_s16(a1_lo))),
                      4);
      int32x4_t s1_1_hi =
          vshrq_n_s32(vpaddq_s32(vmull_s16(vget_low_s16(r1_1_hi), vget_low_s16(a1_hi)),
                                 vmull_s16(vget_high_s16(r1_1_hi), vget_high_s16(a1_hi))),
                      4);

      int16x8_t s0_1_16 = vcombine_s16(vqmovn_s32(s0_1_lo), vqmovn_s32(s0_1_hi));
      int16x8_t s1_1_16 = vcombine_s16(vqmovn_s32(s1_1_lo), vqmovn_s32(s1_1_hi));

      int32x4_t t0_1_lo = vshrq_n_s32(vmull_s16(vget_low_s16(s0_1_16), vget_low_s16(vb0)), 16);
      int32x4_t t1_1_lo = vshrq_n_s32(vmull_s16(vget_low_s16(s1_1_16), vget_low_s16(vb1)), 16);
      int32x4_t val1_lo = vshrq_n_s32(vaddq_s32(vaddq_s32(t0_1_lo, t1_1_lo), vtwo), 2);

      int32x4_t t0_1_hi = vshrq_n_s32(vmull_s16(vget_high_s16(s0_1_16), vget_high_s16(vb0)), 16);
      int32x4_t t1_1_hi = vshrq_n_s32(vmull_s16(vget_high_s16(s1_1_16), vget_high_s16(vb1)), 16);
      int32x4_t val1_hi = vshrq_n_s32(vaddq_s32(vaddq_s32(t0_1_hi, t1_1_hi), vtwo), 2);

      uint8x8_t res1 = vqmovun_s16(vcombine_s16(vqmovn_s32(val1_lo), vqmovn_s32(val1_hi)));

      vst1q_u8(dst_row + dx, vcombine_u8(res0, res1));
    }

    for (; dx + 8 <= dst_w && xofs[(dx + 7) * 2 + 0] < src_w - 1; dx += 8) {
      alignas(16) uint16_t w0[8];
      alignas(16) uint16_t w1[8];
      const int* pxofs = xofs.data() + dx * 2;
      for (int k = 0; k < 8; ++k) {
        w0[k] = *reinterpret_cast<const uint16_t*>(row0 + pxofs[k * 2]);
        w1[k] = *reinterpret_cast<const uint16_t*>(row1 + pxofs[k * 2]);
      }

      uint8x16_t r0_u8 = vld1q_u8(reinterpret_cast<const uint8_t*>(w0));
      uint8x16_t r1_u8 = vld1q_u8(reinterpret_cast<const uint8_t*>(w1));
      int16x8_t r0_lo = vreinterpretq_s16_u16(vmovl_u8(vget_low_u8(r0_u8)));
      int16x8_t r0_hi = vreinterpretq_s16_u16(vmovl_u8(vget_high_u8(r0_u8)));
      int16x8_t r1_lo = vreinterpretq_s16_u16(vmovl_u8(vget_low_u8(r1_u8)));
      int16x8_t r1_hi = vreinterpretq_s16_u16(vmovl_u8(vget_high_u8(r1_u8)));

      int16x8_t alpha_lo = vld1q_s16(ialpha.data() + dx * 2);
      int16x8_t alpha_hi = vld1q_s16(ialpha.data() + dx * 2 + 8);

      int32x4_t s0_lo =
          vshrq_n_s32(vpaddq_s32(vmull_s16(vget_low_s16(r0_lo), vget_low_s16(alpha_lo)),
                                 vmull_s16(vget_high_s16(r0_lo), vget_high_s16(alpha_lo))),
                      4);
      int32x4_t s0_hi =
          vshrq_n_s32(vpaddq_s32(vmull_s16(vget_low_s16(r0_hi), vget_low_s16(alpha_hi)),
                                 vmull_s16(vget_high_s16(r0_hi), vget_high_s16(alpha_hi))),
                      4);

      int32x4_t s1_lo =
          vshrq_n_s32(vpaddq_s32(vmull_s16(vget_low_s16(r1_lo), vget_low_s16(alpha_lo)),
                                 vmull_s16(vget_high_s16(r1_lo), vget_high_s16(alpha_lo))),
                      4);
      int32x4_t s1_hi =
          vshrq_n_s32(vpaddq_s32(vmull_s16(vget_low_s16(r1_hi), vget_low_s16(alpha_hi)),
                                 vmull_s16(vget_high_s16(r1_hi), vget_high_s16(alpha_hi))),
                      4);

      int16x8_t s0_16 = vcombine_s16(vqmovn_s32(s0_lo), vqmovn_s32(s0_hi));
      int16x8_t s1_16 = vcombine_s16(vqmovn_s32(s1_lo), vqmovn_s32(s1_hi));

      int32x4_t t0_lo = vshrq_n_s32(vmull_s16(vget_low_s16(s0_16), vget_low_s16(vb0)), 16);
      int32x4_t t1_lo = vshrq_n_s32(vmull_s16(vget_low_s16(s1_16), vget_low_s16(vb1)), 16);
      int32x4_t val_lo = vshrq_n_s32(vaddq_s32(vaddq_s32(t0_lo, t1_lo), vtwo), 2);

      int32x4_t t0_hi = vshrq_n_s32(vmull_s16(vget_high_s16(s0_16), vget_high_s16(vb0)), 16);
      int32x4_t t1_hi = vshrq_n_s32(vmull_s16(vget_high_s16(s1_16), vget_high_s16(vb1)), 16);
      int32x4_t val_hi = vshrq_n_s32(vaddq_s32(vaddq_s32(t0_hi, t1_hi), vtwo), 2);

      uint8x8_t res = vqmovun_s16(vcombine_s16(vqmovn_s32(val_lo), vqmovn_s32(val_hi)));
      vst1_u8(dst_row + dx, res);
    }

    for (; dx < dst_w; ++dx) {
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

void MatchTemplateNccNEON(const float* image, int img_w, int img_h, int img_stride,
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

  alignas(32) double stack_col_sum[512];
  alignas(32) double stack_col_sum2[512];
  alignas(32) double stack_pref_i[513];
  alignas(32) double stack_pref_i2[513];
  alignas(32) float stack_inv_norm[512];

  double* col_sum = stack_col_sum;
  double* col_sum2 = stack_col_sum2;
  double* pref_i = stack_pref_i;
  double* pref_i2 = stack_pref_i2;
  float* inv_norm = stack_inv_norm;

  std::vector<double> heap_col_sum;
  std::vector<double> heap_col_sum2;
  std::vector<double> heap_pref_i;
  std::vector<double> heap_pref_i2;
  std::vector<float> heap_inv_norm;

  if (img_w > 512) {
    heap_col_sum.resize(img_w);
    heap_col_sum2.resize(img_w);
    heap_pref_i.resize(img_w + 1);
    heap_pref_i2.resize(img_w + 1);
    heap_inv_norm.resize(out_w);

    col_sum = heap_col_sum.data();
    col_sum2 = heap_col_sum2.data();
    pref_i = heap_pref_i.data();
    pref_i2 = heap_pref_i2.data();
    inv_norm = heap_inv_norm.data();
  }

  for (int y = 0; y < out_h; ++y) {
    float* resp_row = out_response + y * out_w;

    if (y == 0) {
      for (int c = 0; c < img_w; ++c) {
        col_sum[c] = 0.0;
        col_sum2[c] = 0.0;
      }
      for (int r = 0; r < th; ++r) {
        const float* img_row = image + r * img_stride;
        int c = 0;
        for (; c + 3 < img_w; c += 4) {
          float32x4_t v = vld1q_f32(img_row + c);
          float64x2_t d_lo = vcvt_f64_f32(vget_low_f32(v));
          float64x2_t d_hi = vcvt_high_f64_f32(v);

          float64x2_t cs_lo = vld1q_f64(col_sum + c);
          float64x2_t cs_hi = vld1q_f64(col_sum + c + 2);
          vst1q_f64(col_sum + c, vaddq_f64(cs_lo, d_lo));
          vst1q_f64(col_sum + c + 2, vaddq_f64(cs_hi, d_hi));

          float64x2_t cs2_lo = vld1q_f64(col_sum2 + c);
          float64x2_t cs2_hi = vld1q_f64(col_sum2 + c + 2);
          vst1q_f64(col_sum2 + c, vfmaq_f64(cs2_lo, d_lo, d_lo));
          vst1q_f64(col_sum2 + c + 2, vfmaq_f64(cs2_hi, d_hi, d_hi));
        }
        for (; c < img_w; ++c) {
          double val = static_cast<double>(img_row[c]);
          col_sum[c] += val;
          col_sum2[c] = std::fma(val, val, col_sum2[c]);
        }
      }
    } else {
      const float* row_sub = image + (y - 1) * img_stride;
      const float* row_add = image + (y + th - 1) * img_stride;
      int c = 0;
      for (; c + 3 < img_w; c += 4) {
        float32x4_t v_sub = vld1q_f32(row_sub + c);
        float32x4_t v_add = vld1q_f32(row_add + c);
        float64x2_t sub_lo = vcvt_f64_f32(vget_low_f32(v_sub));
        float64x2_t sub_hi = vcvt_high_f64_f32(v_sub);
        float64x2_t add_lo = vcvt_f64_f32(vget_low_f32(v_add));
        float64x2_t add_hi = vcvt_high_f64_f32(v_add);

        float64x2_t cs_lo = vld1q_f64(col_sum + c);
        float64x2_t cs_hi = vld1q_f64(col_sum + c + 2);
        cs_lo = vaddq_f64(cs_lo, vsubq_f64(add_lo, sub_lo));
        cs_hi = vaddq_f64(cs_hi, vsubq_f64(add_hi, sub_hi));
        vst1q_f64(col_sum + c, cs_lo);
        vst1q_f64(col_sum + c + 2, cs_hi);

        float64x2_t cs2_lo = vld1q_f64(col_sum2 + c);
        float64x2_t cs2_hi = vld1q_f64(col_sum2 + c + 2);
        cs2_lo = vaddq_f64(cs2_lo, vsubq_f64(vmulq_f64(add_lo, add_lo), vmulq_f64(sub_lo, sub_lo)));
        cs2_hi = vaddq_f64(cs2_hi, vsubq_f64(vmulq_f64(add_hi, add_hi), vmulq_f64(sub_hi, sub_hi)));
        vst1q_f64(col_sum2 + c, cs2_lo);
        vst1q_f64(col_sum2 + c + 2, cs2_hi);
      }
      for (; c < img_w; ++c) {
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

    int nx = 0;
    const float64x2_t vinv_pix = vdupq_n_f64(inv_pixels);
    const float64x2_t vtpl_norm = vdupq_n_f64(tpl_norm);
    const float64x2_t vone = vdupq_n_f64(1.0);
    const float64x2_t veps = vdupq_n_f64(1e-5);
    const uint64x2_t vzero_u64 = vdupq_n_u64(0);

    for (; nx + 3 < out_w; nx += 4) {
      float64x2_t s_i_lo = vsubq_f64(vld1q_f64(pref_i + nx + tw), vld1q_f64(pref_i + nx));
      float64x2_t s_i_hi = vsubq_f64(vld1q_f64(pref_i + nx + tw + 2), vld1q_f64(pref_i + nx + 2));
      float64x2_t s_i2_lo = vsubq_f64(vld1q_f64(pref_i2 + nx + tw), vld1q_f64(pref_i2 + nx));
      float64x2_t s_i2_hi =
          vsubq_f64(vld1q_f64(pref_i2 + nx + tw + 2), vld1q_f64(pref_i2 + nx + 2));

      float64x2_t var_lo = vfmsq_f64(s_i2_lo, vmulq_f64(s_i_lo, s_i_lo), vinv_pix);
      float64x2_t var_hi = vfmsq_f64(s_i2_hi, vmulq_f64(s_i_hi, s_i_hi), vinv_pix);

      uint64x2_t mask_lo = vcgtq_f64(var_lo, veps);
      uint64x2_t mask_hi = vcgtq_f64(var_hi, veps);

      float64x2_t inv_lo = vdivq_f64(vone, vmulq_f64(vtpl_norm, vsqrtq_f64(var_lo)));
      float64x2_t inv_hi = vdivq_f64(vone, vmulq_f64(vtpl_norm, vsqrtq_f64(var_hi)));

      inv_lo = vbslq_f64(mask_lo, inv_lo, vreinterpretq_f64_u64(vzero_u64));
      inv_hi = vbslq_f64(mask_hi, inv_hi, vreinterpretq_f64_u64(vzero_u64));

      float32x4_t inv_f = vcombine_f32(vcvt_f32_f64(inv_lo), vcvt_f32_f64(inv_hi));
      vst1q_f32(inv_norm + nx, inv_f);
    }
    for (; nx < out_w; ++nx) {
      double sum_i = pref_i[nx + tw] - pref_i[nx];
      double sum_i2 = pref_i2[nx + tw] - pref_i2[nx];
      double var_i = std::fma(-(sum_i * sum_i), inv_pixels, sum_i2);
      if (var_i <= 1e-5) {
        inv_norm[nx] = 0.0f;
      } else {
        inv_norm[nx] = static_cast<float>(1.0 / (tpl_norm * std::sqrt(var_i)));
      }
    }

    int x = 0;
    const float32x4_t vmin = vdupq_n_f32(-1.0f);
    const float32x4_t vmax = vdupq_n_f32(1.0f);

    for (; x + 15 < out_w; x += 16) {
      float32x4_t acc0 = vdupq_n_f32(0.0f);
      float32x4_t acc1 = vdupq_n_f32(0.0f);
      float32x4_t acc2 = vdupq_n_f32(0.0f);
      float32x4_t acc3 = vdupq_n_f32(0.0f);
      float32x4_t acc0_b = vdupq_n_f32(0.0f);
      float32x4_t acc1_b = vdupq_n_f32(0.0f);
      float32x4_t acc2_b = vdupq_n_f32(0.0f);
      float32x4_t acc3_b = vdupq_n_f32(0.0f);

      const float* t_ptr = tpl.zero_mean_fmap.data();
      for (int r = 0; r < th; ++r) {
        const float* img_row = image + (y + r) * img_stride + x;
        int c = 0;
        for (; c + 1 < tw; c += 2) {
          float32x4_t t0 = vdupq_n_f32(t_ptr[c]);
          float32x4_t t1 = vdupq_n_f32(t_ptr[c + 1]);

          float32x4_t i0 = vld1q_f32(img_row + c);
          float32x4_t i1 = vld1q_f32(img_row + c + 4);
          float32x4_t i2 = vld1q_f32(img_row + c + 8);
          float32x4_t i3 = vld1q_f32(img_row + c + 12);

          acc0 = vfmaq_f32(acc0, t0, i0);
          acc1 = vfmaq_f32(acc1, t0, i1);
          acc2 = vfmaq_f32(acc2, t0, i2);
          acc3 = vfmaq_f32(acc3, t0, i3);

          float32x4_t i0_b = vld1q_f32(img_row + c + 1);
          float32x4_t i1_b = vld1q_f32(img_row + c + 5);
          float32x4_t i2_b = vld1q_f32(img_row + c + 9);
          float32x4_t i3_b = vld1q_f32(img_row + c + 13);

          acc0_b = vfmaq_f32(acc0_b, t1, i0_b);
          acc1_b = vfmaq_f32(acc1_b, t1, i1_b);
          acc2_b = vfmaq_f32(acc2_b, t1, i2_b);
          acc3_b = vfmaq_f32(acc3_b, t1, i3_b);
        }
        for (; c < tw; ++c) {
          float32x4_t t0 = vdupq_n_f32(t_ptr[c]);
          float32x4_t i0 = vld1q_f32(img_row + c);
          float32x4_t i1 = vld1q_f32(img_row + c + 4);
          float32x4_t i2 = vld1q_f32(img_row + c + 8);
          float32x4_t i3 = vld1q_f32(img_row + c + 12);

          acc0 = vfmaq_f32(acc0, t0, i0);
          acc1 = vfmaq_f32(acc1, t0, i1);
          acc2 = vfmaq_f32(acc2, t0, i2);
          acc3 = vfmaq_f32(acc3, t0, i3);
        }
        t_ptr += tw;
      }
      acc0 = vaddq_f32(acc0, acc0_b);
      acc1 = vaddq_f32(acc1, acc1_b);
      acc2 = vaddq_f32(acc2, acc2_b);
      acc3 = vaddq_f32(acc3, acc3_b);

      float32x4_t inv0 = vld1q_f32(inv_norm + x);
      float32x4_t inv1 = vld1q_f32(inv_norm + x + 4);
      float32x4_t inv2 = vld1q_f32(inv_norm + x + 8);
      float32x4_t inv3 = vld1q_f32(inv_norm + x + 12);

      float32x4_t ncc0 = vminq_f32(vmaxq_f32(vmulq_f32(acc0, inv0), vmin), vmax);
      float32x4_t ncc1 = vminq_f32(vmaxq_f32(vmulq_f32(acc1, inv1), vmin), vmax);
      float32x4_t ncc2 = vminq_f32(vmaxq_f32(vmulq_f32(acc2, inv2), vmin), vmax);
      float32x4_t ncc3 = vminq_f32(vmaxq_f32(vmulq_f32(acc3, inv3), vmin), vmax);

      vst1q_f32(resp_row + x, ncc0);
      vst1q_f32(resp_row + x + 4, ncc1);
      vst1q_f32(resp_row + x + 8, ncc2);
      vst1q_f32(resp_row + x + 12, ncc3);
    }

    for (; x + 7 < out_w; x += 8) {
      float32x4_t acc0 = vdupq_n_f32(0.0f);
      float32x4_t acc1 = vdupq_n_f32(0.0f);
      float32x4_t acc0_b = vdupq_n_f32(0.0f);
      float32x4_t acc1_b = vdupq_n_f32(0.0f);

      const float* t_ptr = tpl.zero_mean_fmap.data();
      for (int r = 0; r < th; ++r) {
        const float* img_row = image + (y + r) * img_stride + x;
        int c = 0;
        for (; c + 1 < tw; c += 2) {
          float32x4_t t0 = vdupq_n_f32(t_ptr[c]);
          float32x4_t t1 = vdupq_n_f32(t_ptr[c + 1]);

          float32x4_t i0 = vld1q_f32(img_row + c);
          float32x4_t i1 = vld1q_f32(img_row + c + 4);
          acc0 = vfmaq_f32(acc0, t0, i0);
          acc1 = vfmaq_f32(acc1, t0, i1);

          float32x4_t i0_b = vld1q_f32(img_row + c + 1);
          float32x4_t i1_b = vld1q_f32(img_row + c + 5);
          acc0_b = vfmaq_f32(acc0_b, t1, i0_b);
          acc1_b = vfmaq_f32(acc1_b, t1, i1_b);
        }
        for (; c < tw; ++c) {
          float32x4_t t0 = vdupq_n_f32(t_ptr[c]);
          float32x4_t i0 = vld1q_f32(img_row + c);
          float32x4_t i1 = vld1q_f32(img_row + c + 4);
          acc0 = vfmaq_f32(acc0, t0, i0);
          acc1 = vfmaq_f32(acc1, t0, i1);
        }
        t_ptr += tw;
      }
      acc0 = vaddq_f32(acc0, acc0_b);
      acc1 = vaddq_f32(acc1, acc1_b);

      float32x4_t inv0 = vld1q_f32(inv_norm + x);
      float32x4_t inv1 = vld1q_f32(inv_norm + x + 4);
      float32x4_t ncc0 = vminq_f32(vmaxq_f32(vmulq_f32(acc0, inv0), vmin), vmax);
      float32x4_t ncc1 = vminq_f32(vmaxq_f32(vmulq_f32(acc1, inv1), vmin), vmax);

      vst1q_f32(resp_row + x, ncc0);
      vst1q_f32(resp_row + x + 4, ncc1);
    }

    for (; x < out_w; ++x) {
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

#endif  // defined(__ARM_NEON) || defined(__aarch64__)
