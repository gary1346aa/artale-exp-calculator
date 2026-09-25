// Copyright 2026 Artale Exp Project. All rights reserved.
// Google C++ Style Guide compliant.

#include "src/cpp/src/exp_engine.h"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <string>
#include <utility>
#include <vector>

#if defined(__SSE2__) || defined(_M_X64) || defined(__x86_64__) || defined(__AVX2__)
#include <immintrin.h>
#elif defined(__ARM_NEON) || defined(__aarch64__)
#include <arm_neon.h>
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

constexpr float kMinNccDigitOrDot = 0.55f;
constexpr float kMinNccNarrowOrBracket = 0.65f;
constexpr float kCharPenalty = 0.20f;
constexpr float kNccExcessBase = 0.45f;
constexpr float kMinComboThreshold = 1.10f;
constexpr int kCanonicalStripHeight = 25;

struct DpNode {
  float score = -1e9f;
  int prev_x = -1;
  int prev_st = -1;
  char character = '\0';
  float ncc = 0.0f;
};

}  // namespace

ExpEngine::ExpEngine() {
  InitializeTemplates();
}

void ExpEngine::InitializeTemplates() {
  prepared_templates_.clear();
  for (size_t i = 0; i < kNumPristinePrototypes; ++i) {
    const PristinePrototype& proto = kPristinePrototypes[i];
    PreparedTemplate pt;
    pt.character = proto.character;
    pt.width = proto.width;
    pt.height = proto.height;

    int total = pt.width * pt.height;
    pt.zero_mean_fmap.resize(total);

    // Compute mean of template
    double sum = 0.0;
    for (int j = 0; j < total; ++j) {
      sum += proto.float_map[j];
    }
    float mean = static_cast<float>(sum / total);

    // Compute zero-mean float map and its L2 norm
    double sum_sq = 0.0;
    for (int j = 0; j < total; ++j) {
      float zm = proto.float_map[j] - mean;
      pt.zero_mean_fmap[j] = zm;
      sum_sq += zm * zm;
    }
    pt.norm = static_cast<float>(std::sqrt(sum_sq));
    prepared_templates_[proto.character] = std::move(pt);
  }
}

// Bilinear interpolation kernel for 8-bit grayscale images.
// Matches OpenCV's cv2.INTER_LINEAR bit-for-bit:
// 1. Uses 11-bit fixed-point weights (INTER_RESIZE_COEF_BITS = 11, scale =
// 2048).
// 2. Uses Banker's rounding (round-half-to-even) via CvRound/_mm_cvtss_si32.
// 3. Vectorized with AVX2 dual-pipeline 16-pixel unrolling, using direct 16-bit
//    word loads to eliminate serial VPINSRB dependency chains.
void ExpEngine::ResizeGray(const uint8_t* src, int src_w, int src_h, int src_stride, uint8_t* dst,
                           int dst_w, int dst_h, int dst_stride) {
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
    if (sy < 0) {
      fy = 0.0f;
      sy = 0;
    }
    if (sy >= src_h - 1) {
      fy = 0.0f;
      sy = src_h - 1;
    }
    yofs[dy] = sy;
    float c0 = 1.0f - fy;
    float c1 = fy;
    ibeta[dy * 2 + 0] = static_cast<int16_t>(CvRound(c0 * kScale));
    ibeta[dy * 2 + 1] = static_cast<int16_t>(CvRound(c1 * kScale));
  }

  for (int dy = 0; dy < dst_h; ++dy) {
    int sy0 = yofs[dy];
    int sy1 = std::min(sy0 + 1, src_h - 1);
    int32_t b0 = ibeta[dy * 2 + 0];
    int32_t b1 = ibeta[dy * 2 + 1];

    const uint8_t* row0 = src + sy0 * src_stride;
    const uint8_t* row1 = src + sy1 * src_stride;
    uint8_t* dst_row = dst + dy * dst_stride;

    int dx = 0;
#if defined(__AVX2__)
    const __m128i vb0 = _mm_set1_epi16(static_cast<int16_t>(b0));
    const __m128i vb1 = _mm_set1_epi16(static_cast<int16_t>(b1));
    const __m128i v2 = _mm_set1_epi16(2);

    // 16-pixel parallel unrolled AVX2 loop:
    // Computes two 8-pixel blocks in parallel, packs into 16 bytes via
    // _mm_packus_epi16, and stores 16 destination pixels in a single 128-bit
    // store instruction.
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

      __m256i r0_0 = _mm256_cvtepu8_epi16(_mm_load_si128(reinterpret_cast<const __m128i*>(w0_0)));
      __m256i r1_0 = _mm256_cvtepu8_epi16(_mm_load_si128(reinterpret_cast<const __m128i*>(w1_0)));
      __m256i r0_1 = _mm256_cvtepu8_epi16(_mm_load_si128(reinterpret_cast<const __m128i*>(w0_1)));
      __m256i r1_1 = _mm256_cvtepu8_epi16(_mm_load_si128(reinterpret_cast<const __m128i*>(w1_1)));

      __m256i alpha0 = _mm256_loadu_si256(reinterpret_cast<const __m256i*>(ialpha.data() + dx * 2));
      __m256i alpha1 =
          _mm256_loadu_si256(reinterpret_cast<const __m256i*>(ialpha.data() + (dx + 8) * 2));

      __m256i s0_0 = _mm256_srai_epi32(_mm256_madd_epi16(r0_0, alpha0), 4);
      __m256i s1_0 = _mm256_srai_epi32(_mm256_madd_epi16(r1_0, alpha0), 4);
      __m256i s0_1 = _mm256_srai_epi32(_mm256_madd_epi16(r0_1, alpha1), 4);
      __m256i s1_1 = _mm256_srai_epi32(_mm256_madd_epi16(r1_1, alpha1), 4);

      __m128i s0_16_0 =
          _mm_packs_epi32(_mm256_castsi256_si128(s0_0), _mm256_extracti128_si256(s0_0, 1));
      __m128i s1_16_0 =
          _mm_packs_epi32(_mm256_castsi256_si128(s1_0), _mm256_extracti128_si256(s1_0, 1));
      __m128i s0_16_1 =
          _mm_packs_epi32(_mm256_castsi256_si128(s0_1), _mm256_extracti128_si256(s0_1, 1));
      __m128i s1_16_1 =
          _mm_packs_epi32(_mm256_castsi256_si128(s1_1), _mm256_extracti128_si256(s1_1, 1));

      __m128i sum0 = _mm_srai_epi16(
          _mm_add_epi16(_mm_add_epi16(_mm_mulhi_epi16(s0_16_0, vb0), _mm_mulhi_epi16(s1_16_0, vb1)),
                        v2),
          2);
      __m128i sum1 = _mm_srai_epi16(
          _mm_add_epi16(_mm_add_epi16(_mm_mulhi_epi16(s0_16_1, vb0), _mm_mulhi_epi16(s1_16_1, vb1)),
                        v2),
          2);

      __m128i packed16 = _mm_packus_epi16(sum0, sum1);
      _mm_storeu_si128(reinterpret_cast<__m128i*>(dst_row + dx), packed16);
    }

    for (; dx + 8 <= dst_w && xofs[(dx + 7) * 2 + 0] < src_w - 1; dx += 8) {
      alignas(16) uint16_t w0[8];
      alignas(16) uint16_t w1[8];
      const int* pxofs = xofs.data() + dx * 2;
      for (int k = 0; k < 8; ++k) {
        w0[k] = *reinterpret_cast<const uint16_t*>(row0 + pxofs[k * 2]);
        w1[k] = *reinterpret_cast<const uint16_t*>(row1 + pxofs[k * 2]);
      }

      __m256i r0 = _mm256_cvtepu8_epi16(_mm_load_si128(reinterpret_cast<const __m128i*>(w0)));
      __m256i r1 = _mm256_cvtepu8_epi16(_mm_load_si128(reinterpret_cast<const __m128i*>(w1)));

      __m256i alpha = _mm256_loadu_si256(reinterpret_cast<const __m256i*>(ialpha.data() + dx * 2));

      __m256i s0 = _mm256_srai_epi32(_mm256_madd_epi16(r0, alpha), 4);
      __m256i s1 = _mm256_srai_epi32(_mm256_madd_epi16(r1, alpha), 4);

      __m128i s0_16 = _mm_packs_epi32(_mm256_castsi256_si128(s0), _mm256_extracti128_si256(s0, 1));
      __m128i s1_16 = _mm_packs_epi32(_mm256_castsi256_si128(s1), _mm256_extracti128_si256(s1, 1));

      __m128i sum = _mm_srai_epi16(
          _mm_add_epi16(_mm_add_epi16(_mm_mulhi_epi16(s0_16, vb0), _mm_mulhi_epi16(s1_16, vb1)),
                        v2),
          2);

      __m128i packed = _mm_packus_epi16(sum, sum);
      std::memcpy(dst_row + dx, &packed, 8);
    }
#elif defined(__ARM_NEON) || defined(__aarch64__)
    const int16x8_t vb0 = vdupq_n_s16(static_cast<int16_t>(b0));
    const int16x8_t vb1 = vdupq_n_s16(static_cast<int16_t>(b1));
    const int32x4_t vtwo = vdupq_n_s32(2);

    // 16-pixel parallel unrolled NEON loop:
    // Computes two 8-pixel blocks in parallel, packs into 16 bytes via
    // saturating narrowing, and stores 16 destination pixels in a single 128-bit
    // store instruction.
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

      // Block 0: pixels dx..dx+7
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
          vshrq_n_s32(vpaddq_s32(vmull_s16(vget_high_s16(r1_1_hi), vget_high_s16(a1_hi)),
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

    // 8-pixel remainder NEON loop
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
          vshrq_n_s32(vpaddq_s32(vmull_s16(vget_high_s16(r1_hi), vget_high_s16(alpha_hi)),
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
#endif

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

void ExpEngine::ResizeGrayScalar(const uint8_t* src, int src_w, int src_h, int src_stride,
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
    if (sy < 0) {
      fy = 0.0f;
      sy = 0;
    }
    if (sy >= src_h - 1) {
      fy = 0.0f;
      sy = src_h - 1;
    }
    yofs[dy] = sy;
    float c0 = 1.0f - fy;
    float c1 = fy;
    ibeta[dy * 2 + 0] = static_cast<int16_t>(CvRound(c0 * kScale));
    ibeta[dy * 2 + 1] = static_cast<int16_t>(CvRound(c1 * kScale));
  }

  for (int dy = 0; dy < dst_h; ++dy) {
    int sy0 = yofs[dy];
    int sy1 = std::min(sy0 + 1, src_h - 1);
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

void ExpEngine::MatchTemplateNcc(const float* image, int img_w, int img_h, int img_stride,
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

  const int total_pixels = tw * th;
  const double inv_pixels = 1.0 / total_pixels;

  constexpr int kMaxStackW = 512;
  double stack_col_sum[kMaxStackW];
  double stack_col_sum2[kMaxStackW];
  double stack_pref_i[kMaxStackW + 1];
  double stack_pref_i2[kMaxStackW + 1];
  float stack_inv_norm[kMaxStackW];

  std::vector<double> heap_col_sum;
  std::vector<double> heap_col_sum2;
  std::vector<double> heap_pref_i;
  std::vector<double> heap_pref_i2;
  std::vector<float> heap_inv_norm;

  double* col_sum = stack_col_sum;
  double* col_sum2 = stack_col_sum2;
  double* pref_i = stack_pref_i;
  double* pref_i2 = stack_pref_i2;
  float* inv_norm = stack_inv_norm;

  if (img_w > kMaxStackW) {
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
      // 1. Initial Column sums across window rows [0, th)
      for (int c = 0; c < img_w; ++c) {
        col_sum[c] = 0.0;
        col_sum2[c] = 0.0;
      }
      for (int r = 0; r < th; ++r) {
        const float* img_row = image + r * img_stride;
        int c = 0;
#if defined(__AVX2__)
        for (; c + 7 < img_w; c += 8) {
          __m256 v = _mm256_loadu_ps(img_row + c);
          __m128 v_lo = _mm256_castps256_ps128(v);
          __m128 v_hi = _mm256_extractf128_ps(v, 1);
          __m256d d_lo = _mm256_cvtps_pd(v_lo);
          __m256d d_hi = _mm256_cvtps_pd(v_hi);

          __m256d cs_lo = _mm256_loadu_pd(col_sum + c);
          __m256d cs_hi = _mm256_loadu_pd(col_sum + c + 4);
          cs_lo = _mm256_add_pd(cs_lo, d_lo);
          cs_hi = _mm256_add_pd(cs_hi, d_hi);
          _mm256_storeu_pd(col_sum + c, cs_lo);
          _mm256_storeu_pd(col_sum + c + 4, cs_hi);

          __m256d cs2_lo = _mm256_loadu_pd(col_sum2 + c);
          __m256d cs2_hi = _mm256_loadu_pd(col_sum2 + c + 4);
          cs2_lo = _mm256_fmadd_pd(d_lo, d_lo, cs2_lo);
          cs2_hi = _mm256_fmadd_pd(d_hi, d_hi, cs2_hi);
          _mm256_storeu_pd(col_sum2 + c, cs2_lo);
          _mm256_storeu_pd(col_sum2 + c + 4, cs2_hi);
        }
#elif defined(__ARM_NEON) || defined(__aarch64__)
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
#endif
        for (; c < img_w; ++c) {
          double val = static_cast<double>(img_row[c]);
          col_sum[c] += val;
          col_sum2[c] += val * val;
        }
      }
    } else {
      // Rolling column sum update: subtract exiting row (y - 1), add entering
      // row (y + th - 1)
      const float* row_sub = image + (y - 1) * img_stride;
      const float* row_add = image + (y + th - 1) * img_stride;
      int c = 0;
#if defined(__AVX2__)
      for (; c + 7 < img_w; c += 8) {
        __m256 v_sub = _mm256_loadu_ps(row_sub + c);
        __m256 v_add = _mm256_loadu_ps(row_add + c);
        __m256d sub_lo = _mm256_cvtps_pd(_mm256_castps256_ps128(v_sub));
        __m256d sub_hi = _mm256_cvtps_pd(_mm256_extractf128_ps(v_sub, 1));
        __m256d add_lo = _mm256_cvtps_pd(_mm256_castps256_ps128(v_add));
        __m256d add_hi = _mm256_cvtps_pd(_mm256_extractf128_ps(v_add, 1));

        __m256d cs_lo = _mm256_loadu_pd(col_sum + c);
        __m256d cs_hi = _mm256_loadu_pd(col_sum + c + 4);
        cs_lo = _mm256_add_pd(cs_lo, _mm256_sub_pd(add_lo, sub_lo));
        cs_hi = _mm256_add_pd(cs_hi, _mm256_sub_pd(add_hi, sub_hi));
        _mm256_storeu_pd(col_sum + c, cs_lo);
        _mm256_storeu_pd(col_sum + c + 4, cs_hi);

        __m256d cs2_lo = _mm256_loadu_pd(col_sum2 + c);
        __m256d cs2_hi = _mm256_loadu_pd(col_sum2 + c + 4);
        cs2_lo =
            _mm256_add_pd(cs2_lo, _mm256_fmsub_pd(add_lo, add_lo, _mm256_mul_pd(sub_lo, sub_lo)));
        cs2_hi =
            _mm256_add_pd(cs2_hi, _mm256_fmsub_pd(add_hi, add_hi, _mm256_mul_pd(sub_hi, sub_hi)));
        _mm256_storeu_pd(col_sum2 + c, cs2_lo);
        _mm256_storeu_pd(col_sum2 + c + 4, cs2_hi);
      }
#elif defined(__ARM_NEON) || defined(__aarch64__)
      for (; c + 3 < img_w; c += 4) {
        float32x4_t v_sub = vld1q_f32(row_sub + c);
        float32x4_t v_add = vld1q_f32(row_add + c);
        float64x2_t sub_lo = vcvt_f64_f32(vget_low_f32(v_sub));
        float64x2_t sub_hi = vcvt_high_f64_f32(v_sub);
        float64x2_t add_lo = vcvt_f64_f32(vget_low_f32(v_add));
        float64x2_t add_hi = vcvt_high_f64_f32(v_add);

        float64x2_t cs_lo = vld1q_f64(col_sum + c);
        float64x2_t cs_hi = vld1q_f64(col_sum + c + 2);
        vst1q_f64(col_sum + c, vaddq_f64(cs_lo, vsubq_f64(add_lo, sub_lo)));
        vst1q_f64(col_sum + c + 2, vaddq_f64(cs_hi, vsubq_f64(add_hi, sub_hi)));

        float64x2_t cs2_lo = vld1q_f64(col_sum2 + c);
        float64x2_t cs2_hi = vld1q_f64(col_sum2 + c + 2);
        float64x2_t diff2_lo = vsubq_f64(vmulq_f64(add_lo, add_lo), vmulq_f64(sub_lo, sub_lo));
        float64x2_t diff2_hi = vsubq_f64(vmulq_f64(add_hi, add_hi), vmulq_f64(sub_hi, sub_hi));
        vst1q_f64(col_sum2 + c, vaddq_f64(cs2_lo, diff2_lo));
        vst1q_f64(col_sum2 + c + 2, vaddq_f64(cs2_hi, diff2_hi));
      }
#endif
      for (; c < img_w; ++c) {
        double vs = static_cast<double>(row_sub[c]);
        double va = static_cast<double>(row_add[c]);
        col_sum[c] += (va - vs);
        col_sum2[c] += (va * va - vs * vs);
      }
    }

    // 2. 1D prefix sums for horizontal sliding windows
    pref_i[0] = 0.0;
    pref_i2[0] = 0.0;
    for (int c = 0; c < img_w; ++c) {
      pref_i[c + 1] = pref_i[c] + col_sum[c];
      pref_i2[c + 1] = pref_i2[c] + col_sum2[c];
    }

    // 3. Inverse normalizer inv_norm[x] = 1.0 / (tpl_norm * norm_i)
    int nx = 0;
#if defined(__AVX2__) && defined(__FMA__)
    const __m256d vinv_pix = _mm256_set1_pd(inv_pixels);
    const __m256d vtpl_norm = _mm256_set1_pd(tpl_norm);
    const __m256d vone = _mm256_set1_pd(1.0);
    const __m256d veps = _mm256_set1_pd(1e-5);

    for (; nx + 3 < out_w; nx += 4) {
      __m256d s_i = _mm256_sub_pd(_mm256_loadu_pd(pref_i + nx + tw), _mm256_loadu_pd(pref_i + nx));
      __m256d s_i2 =
          _mm256_sub_pd(_mm256_loadu_pd(pref_i2 + nx + tw), _mm256_loadu_pd(pref_i2 + nx));
      __m256d var_i = _mm256_fnmadd_pd(_mm256_mul_pd(s_i, s_i), vinv_pix, s_i2);

      __m256d mask = _mm256_cmp_pd(var_i, veps, _CMP_GT_OQ);
      __m256d sqrt_var = _mm256_sqrt_pd(var_i);
      __m256d denom = _mm256_mul_pd(vtpl_norm, sqrt_var);
      __m256d inv = _mm256_div_pd(vone, denom);
      inv = _mm256_and_pd(inv, mask);

      __m128 inv_f = _mm256_cvtpd_ps(inv);
      _mm_storeu_ps(inv_norm + nx, inv_f);
    }
#elif defined(__ARM_NEON) || defined(__aarch64__)
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
#endif
    for (; nx < out_w; ++nx) {
      double sum_i = pref_i[nx + tw] - pref_i[nx];
      double sum_i2 = pref_i2[nx + tw] - pref_i2[nx];
      double var_i = sum_i2 - (sum_i * sum_i) * inv_pixels;
      if (var_i <= 1e-5) {
        inv_norm[nx] = 0.0f;
      } else {
        inv_norm[nx] = static_cast<float>(1.0 / (tpl_norm * std::sqrt(var_i)));
      }
    }

    // 4. Dot product with template zero-mean map: sum_it
    int x = 0;
#if defined(__AVX2__) && defined(__FMA__)
    const __m256 vmin = _mm256_set1_ps(-1.0f);
    const __m256 vmax = _mm256_set1_ps(1.0f);

    for (; x + 31 < out_w; x += 32) {
      __m256 acc0 = _mm256_setzero_ps();
      __m256 acc1 = _mm256_setzero_ps();
      __m256 acc2 = _mm256_setzero_ps();
      __m256 acc3 = _mm256_setzero_ps();
      __m256 acc0_b = _mm256_setzero_ps();
      __m256 acc1_b = _mm256_setzero_ps();
      __m256 acc2_b = _mm256_setzero_ps();
      __m256 acc3_b = _mm256_setzero_ps();

      const float* t_ptr = tpl.zero_mean_fmap.data();
      for (int r = 0; r < th; ++r) {
        const float* img_row = image + (y + r) * img_stride + x;
        int c = 0;
        for (; c + 1 < tw; c += 2) {
          __m256 t0 = _mm256_set1_ps(t_ptr[c]);
          __m256 t1 = _mm256_set1_ps(t_ptr[c + 1]);

          __m256 i0 = _mm256_loadu_ps(img_row + c);
          __m256 i1 = _mm256_loadu_ps(img_row + c + 8);
          __m256 i2 = _mm256_loadu_ps(img_row + c + 16);
          __m256 i3 = _mm256_loadu_ps(img_row + c + 24);

          acc0 = _mm256_fmadd_ps(t0, i0, acc0);
          acc1 = _mm256_fmadd_ps(t0, i1, acc1);
          acc2 = _mm256_fmadd_ps(t0, i2, acc2);
          acc3 = _mm256_fmadd_ps(t0, i3, acc3);

          __m256 i0_b = _mm256_loadu_ps(img_row + c + 1);
          __m256 i1_b = _mm256_loadu_ps(img_row + c + 9);
          __m256 i2_b = _mm256_loadu_ps(img_row + c + 17);
          __m256 i3_b = _mm256_loadu_ps(img_row + c + 25);

          acc0_b = _mm256_fmadd_ps(t1, i0_b, acc0_b);
          acc1_b = _mm256_fmadd_ps(t1, i1_b, acc1_b);
          acc2_b = _mm256_fmadd_ps(t1, i2_b, acc2_b);
          acc3_b = _mm256_fmadd_ps(t1, i3_b, acc3_b);
        }
        for (; c < tw; ++c) {
          __m256 t0 = _mm256_set1_ps(t_ptr[c]);
          __m256 i0 = _mm256_loadu_ps(img_row + c);
          __m256 i1 = _mm256_loadu_ps(img_row + c + 8);
          __m256 i2 = _mm256_loadu_ps(img_row + c + 16);
          __m256 i3 = _mm256_loadu_ps(img_row + c + 24);

          acc0 = _mm256_fmadd_ps(t0, i0, acc0);
          acc1 = _mm256_fmadd_ps(t0, i1, acc1);
          acc2 = _mm256_fmadd_ps(t0, i2, acc2);
          acc3 = _mm256_fmadd_ps(t0, i3, acc3);
        }
        t_ptr += tw;
      }
      acc0 = _mm256_add_ps(acc0, acc0_b);
      acc1 = _mm256_add_ps(acc1, acc1_b);
      acc2 = _mm256_add_ps(acc2, acc2_b);
      acc3 = _mm256_add_ps(acc3, acc3_b);

      __m256 inv0 = _mm256_loadu_ps(inv_norm + x);
      __m256 inv1 = _mm256_loadu_ps(inv_norm + x + 8);
      __m256 inv2 = _mm256_loadu_ps(inv_norm + x + 16);
      __m256 inv3 = _mm256_loadu_ps(inv_norm + x + 24);

      __m256 ncc0 = _mm256_min_ps(_mm256_max_ps(_mm256_mul_ps(acc0, inv0), vmin), vmax);
      __m256 ncc1 = _mm256_min_ps(_mm256_max_ps(_mm256_mul_ps(acc1, inv1), vmin), vmax);
      __m256 ncc2 = _mm256_min_ps(_mm256_max_ps(_mm256_mul_ps(acc2, inv2), vmin), vmax);
      __m256 ncc3 = _mm256_min_ps(_mm256_max_ps(_mm256_mul_ps(acc3, inv3), vmin), vmax);

      _mm256_storeu_ps(resp_row + x, ncc0);
      _mm256_storeu_ps(resp_row + x + 8, ncc1);
      _mm256_storeu_ps(resp_row + x + 16, ncc2);
      _mm256_storeu_ps(resp_row + x + 24, ncc3);
    }

    for (; x + 15 < out_w; x += 16) {
      __m256 acc0 = _mm256_setzero_ps();
      __m256 acc1 = _mm256_setzero_ps();
      __m256 acc0_b = _mm256_setzero_ps();
      __m256 acc1_b = _mm256_setzero_ps();

      const float* t_ptr = tpl.zero_mean_fmap.data();
      for (int r = 0; r < th; ++r) {
        const float* img_row = image + (y + r) * img_stride + x;
        int c = 0;
        for (; c + 1 < tw; c += 2) {
          __m256 t0 = _mm256_set1_ps(t_ptr[c]);
          __m256 t1 = _mm256_set1_ps(t_ptr[c + 1]);

          __m256 i0 = _mm256_loadu_ps(img_row + c);
          __m256 i1 = _mm256_loadu_ps(img_row + c + 8);
          acc0 = _mm256_fmadd_ps(t0, i0, acc0);
          acc1 = _mm256_fmadd_ps(t0, i1, acc1);

          __m256 i0_b = _mm256_loadu_ps(img_row + c + 1);
          __m256 i1_b = _mm256_loadu_ps(img_row + c + 9);
          acc0_b = _mm256_fmadd_ps(t1, i0_b, acc0_b);
          acc1_b = _mm256_fmadd_ps(t1, i1_b, acc1_b);
        }
        for (; c < tw; ++c) {
          __m256 t0 = _mm256_set1_ps(t_ptr[c]);
          __m256 i0 = _mm256_loadu_ps(img_row + c);
          __m256 i1 = _mm256_loadu_ps(img_row + c + 8);
          acc0 = _mm256_fmadd_ps(t0, i0, acc0);
          acc1 = _mm256_fmadd_ps(t0, i1, acc1);
        }
        t_ptr += tw;
      }
      acc0 = _mm256_add_ps(acc0, acc0_b);
      acc1 = _mm256_add_ps(acc1, acc1_b);

      __m256 inv0 = _mm256_loadu_ps(inv_norm + x);
      __m256 inv1 = _mm256_loadu_ps(inv_norm + x + 8);
      __m256 ncc0 = _mm256_min_ps(_mm256_max_ps(_mm256_mul_ps(acc0, inv0), vmin), vmax);
      __m256 ncc1 = _mm256_min_ps(_mm256_max_ps(_mm256_mul_ps(acc1, inv1), vmin), vmax);

      _mm256_storeu_ps(resp_row + x, ncc0);
      _mm256_storeu_ps(resp_row + x + 8, ncc1);
    }

    for (; x + 7 < out_w; x += 8) {
      __m256 acc = _mm256_setzero_ps();
      __m256 acc_b = _mm256_setzero_ps();
      const float* t_ptr = tpl.zero_mean_fmap.data();
      for (int r = 0; r < th; ++r) {
        const float* img_row = image + (y + r) * img_stride + x;
        int c = 0;
        for (; c + 1 < tw; c += 2) {
          __m256 t0 = _mm256_set1_ps(t_ptr[c]);
          __m256 t1 = _mm256_set1_ps(t_ptr[c + 1]);
          __m256 img0 = _mm256_loadu_ps(img_row + c);
          __m256 img1 = _mm256_loadu_ps(img_row + c + 1);
          acc = _mm256_fmadd_ps(t0, img0, acc);
          acc_b = _mm256_fmadd_ps(t1, img1, acc_b);
        }
        for (; c < tw; ++c) {
          __m256 t_val = _mm256_set1_ps(t_ptr[c]);
          __m256 img_val = _mm256_loadu_ps(img_row + c);
          acc = _mm256_fmadd_ps(t_val, img_val, acc);
        }
        t_ptr += tw;
      }
      acc = _mm256_add_ps(acc, acc_b);
      __m256 inv = _mm256_loadu_ps(inv_norm + x);
      __m256 ncc = _mm256_mul_ps(acc, inv);
      ncc = _mm256_min_ps(_mm256_max_ps(ncc, vmin), vmax);
      _mm256_storeu_ps(resp_row + x, ncc);
    }
#elif defined(__ARM_NEON) || defined(__aarch64__)
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

          acc0 = vmlaq_f32(acc0, t0, i0);
          acc1 = vmlaq_f32(acc1, t0, i1);
          acc2 = vmlaq_f32(acc2, t0, i2);
          acc3 = vmlaq_f32(acc3, t0, i3);

          float32x4_t i0_b = vld1q_f32(img_row + c + 1);
          float32x4_t i1_b = vld1q_f32(img_row + c + 5);
          float32x4_t i2_b = vld1q_f32(img_row + c + 9);
          float32x4_t i3_b = vld1q_f32(img_row + c + 13);

          acc0_b = vmlaq_f32(acc0_b, t1, i0_b);
          acc1_b = vmlaq_f32(acc1_b, t1, i1_b);
          acc2_b = vmlaq_f32(acc2_b, t1, i2_b);
          acc3_b = vmlaq_f32(acc3_b, t1, i3_b);
        }
        for (; c < tw; ++c) {
          float32x4_t t0 = vdupq_n_f32(t_ptr[c]);
          float32x4_t i0 = vld1q_f32(img_row + c);
          float32x4_t i1 = vld1q_f32(img_row + c + 4);
          float32x4_t i2 = vld1q_f32(img_row + c + 8);
          float32x4_t i3 = vld1q_f32(img_row + c + 12);

          acc0 = vmlaq_f32(acc0, t0, i0);
          acc1 = vmlaq_f32(acc1, t0, i1);
          acc2 = vmlaq_f32(acc2, t0, i2);
          acc3 = vmlaq_f32(acc3, t0, i3);
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
          acc0 = vmlaq_f32(acc0, t0, i0);
          acc1 = vmlaq_f32(acc1, t0, i1);

          float32x4_t i0_b = vld1q_f32(img_row + c + 1);
          float32x4_t i1_b = vld1q_f32(img_row + c + 5);
          acc0_b = vmlaq_f32(acc0_b, t1, i0_b);
          acc1_b = vmlaq_f32(acc1_b, t1, i1_b);
        }
        for (; c < tw; ++c) {
          float32x4_t t0 = vdupq_n_f32(t_ptr[c]);
          float32x4_t i0 = vld1q_f32(img_row + c);
          float32x4_t i1 = vld1q_f32(img_row + c + 4);
          acc0 = vmlaq_f32(acc0, t0, i0);
          acc1 = vmlaq_f32(acc1, t0, i1);
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

    for (; x + 3 < out_w; x += 4) {
      float32x4_t acc = vdupq_n_f32(0.0f);
      float32x4_t acc_b = vdupq_n_f32(0.0f);

      const float* t_ptr = tpl.zero_mean_fmap.data();
      for (int r = 0; r < th; ++r) {
        const float* img_row = image + (y + r) * img_stride + x;
        int c = 0;
        for (; c + 1 < tw; c += 2) {
          float32x4_t t0 = vdupq_n_f32(t_ptr[c]);
          float32x4_t t1 = vdupq_n_f32(t_ptr[c + 1]);
          float32x4_t img0 = vld1q_f32(img_row + c);
          float32x4_t img1 = vld1q_f32(img_row + c + 1);
          acc = vmlaq_f32(acc, t0, img0);
          acc_b = vmlaq_f32(acc_b, t1, img1);
        }
        for (; c < tw; ++c) {
          float32x4_t t_val = vdupq_n_f32(t_ptr[c]);
          float32x4_t img_val = vld1q_f32(img_row + c);
          acc = vmlaq_f32(acc, t_val, img_val);
        }
        t_ptr += tw;
      }
      acc = vaddq_f32(acc, acc_b);
      float32x4_t inv = vld1q_f32(inv_norm + x);
      float32x4_t ncc = vmulq_f32(acc, inv);
      ncc = vminq_f32(vmaxq_f32(ncc, vmin), vmax);
      vst1q_f32(resp_row + x, ncc);
    }
#endif
    for (; x < out_w; ++x) {
      double sum_it = 0.0;
      const float* t_ptr = tpl.zero_mean_fmap.data();
      for (int r = 0; r < th; ++r) {
        const float* img_row = image + (y + r) * img_stride + x;
        for (int c = 0; c < tw; ++c) {
          sum_it += t_ptr[c] * img_row[c];
        }
        t_ptr += tw;
      }
      float ncc = static_cast<float>(sum_it * inv_norm[x]);
      resp_row[x] = std::max(-1.0f, std::min(1.0f, ncc));
    }
  }
}

bool ExpEngine::ParseCrop(const uint8_t* gray_crop, int width, int height, int stride,
                          CropParseResult* out_result) const {
  if (gray_crop == nullptr || width < 20 || height < 8 || out_result == nullptr) {
    return false;
  }

  auto t_start = std::chrono::steady_clock::now();

  const PreparedTemplate& tpl_bracket = prepared_templates_.at('[');
  const PreparedTemplate& tpl_8 = prepared_templates_.at('8');

  // 1 & 2. Robust multi-scale search using '[' and '8'
  float expected_s = (height > 0) ? (38.0f / static_cast<float>(height)) : 1.0f;
  float s_min = std::max(0.35f, expected_s * 0.65f);
  float s_max = std::min(2.50f, expected_s * 1.45f);

  constexpr int kNumScales = 18;
  float best_combo = -1.0f;
  float best_cs = 1.0f;
  int best_by = 0;

  std::vector<uint8_t> work_gray_buf;
  std::vector<float> work_float_buf;
  std::vector<float> resp_bracket;
  std::vector<float> resp_8;

  for (int s_idx = 0; s_idx < kNumScales; ++s_idx) {
    float cs = s_min + (s_max - s_min) * (static_cast<float>(s_idx) / (kNumScales - 1));
    int wn = static_cast<int>(std::round(width * cs));
    int hn = static_cast<int>(std::round(height * cs));
    if (hn < 25 || wn < 30) continue;

    work_gray_buf.resize(wn * hn);
    ResizeGray(gray_crop, width, height, stride, work_gray_buf.data(), wn, hn, wn);

    work_float_buf.resize(wn * hn);
    for (int i = 0; i < wn * hn; ++i) {
      work_float_buf[i] = static_cast<float>(work_gray_buf[i]);
    }

    int out_bw = wn - tpl_bracket.width + 1;
    int out_bh = hn - tpl_bracket.height + 1;
    if (out_bw <= 0 || out_bh <= 0) continue;
    resp_bracket.resize(out_bw * out_bh);
    MatchTemplateNcc(work_float_buf.data(), wn, hn, wn, tpl_bracket, resp_bracket.data());

    int out_8w = wn - tpl_8.width + 1;
    int out_8h = hn - tpl_8.height + 1;
    if (out_8w <= 0 || out_8h <= 0) continue;
    resp_8.resize(out_8w * out_8h);
    MatchTemplateNcc(work_float_buf.data(), wn, hn, wn, tpl_8, resp_8.data());

    float max_vb = -1.0f;
    int argmax_by = 0;
    for (int y = 0; y < out_bh; ++y) {
      for (int x = 0; x < out_bw; ++x) {
        float val = resp_bracket[y * out_bw + x];
        if (val > max_vb) {
          max_vb = val;
          argmax_by = y;
        }
      }
    }

    float max_v8 = -1.0f;
    for (float val : resp_8) {
      if (val > max_v8) max_v8 = val;
    }

    float combo = max_vb + max_v8;
    if (combo > best_combo) {
      best_combo = combo;
      best_cs = cs;
      best_by = argmax_by;
    }
  }

  if (best_combo < kMinComboThreshold) {
    return false;
  }

  // Build canonical work image at winning scale
  int win_w = static_cast<int>(std::round(width * best_cs));
  int win_h = static_cast<int>(std::round(height * best_cs));
  work_gray_buf.resize(win_w * win_h);
  ResizeGray(gray_crop, width, height, stride, work_gray_buf.data(), win_w, win_h, win_w);

  // Extract canonical 25px strip
  if (best_by + kCanonicalStripHeight > win_h) {
    best_by = win_h - kCanonicalStripHeight;
  }
  if (best_by < 0) best_by = 0;

  std::vector<float> strip_float(win_w * kCanonicalStripHeight);
  for (int y = 0; y < kCanonicalStripHeight; ++y) {
    const uint8_t* src_row = work_gray_buf.data() + (best_by + y) * win_w;
    float* dst_row = strip_float.data() + y * win_w;
    for (int x = 0; x < win_w; ++x) {
      dst_row[x] = static_cast<float>(src_row[x]);
    }
  }

  // 3. Sliding-window NCC responses across all 15 characters
  std::unordered_map<char, std::vector<float>> responses;
  for (const auto& pair : prepared_templates_) {
    char ch = pair.first;
    const PreparedTemplate& t = pair.second;
    int resp_w = win_w - t.width + 1;
    if (resp_w <= 0) continue;

    if (t.height == kCanonicalStripHeight) {
      std::vector<float> r(resp_w);
      MatchTemplateNcc(strip_float.data(), win_w, kCanonicalStripHeight, win_w, t, r.data());
      responses[ch] = std::move(r);
    } else {
      // Vertical jitter of +/-1px to maximize alignment across scales
      std::vector<float> r_max(resp_w, -1.0f);
      std::vector<float> r_temp(resp_w);

      for (int dy = -1; dy <= 1; ++dy) {
        int start_y = 1 + dy;
        const float* sub_img = strip_float.data() + start_y * win_w;
        MatchTemplateNcc(sub_img, win_w, t.height, win_w, t, r_temp.data());
        for (int x = 0; x < resp_w; ++x) {
          if (r_temp[x] > r_max[x]) {
            r_max[x] = r_temp[x];
          }
        }
      }
      responses[ch] = std::move(r_max);
    }
  }

  // 4. Grammar-constrained dynamic programming beam search
  // States:
  // 0: EXP digits (0-9) or '['
  // 1: inside brackets (0-9, '.') or '%'
  // 2: after '%', expecting ']'
  // 3: completed string
  constexpr int kNumStates = 4;
  std::vector<DpNode> dp((win_w + 1) * kNumStates);
  auto get_dp = [&](int x, int st) -> DpNode& { return dp[x * kNumStates + st]; };

  get_dp(0, 0).score = 0.0f;

  for (int x = 0; x < win_w; ++x) {
    for (int st = 0; st < kNumStates; ++st) {
      const DpNode& cur = get_dp(x, st);
      if (cur.score < -1e8f) continue;
      float score = cur.score;

      // Skip blank / background pixel
      DpNode& next_blank = get_dp(x + 1, st);
      if (score > next_blank.score) {
        next_blank.score = score;
        next_blank.prev_x = x;
        next_blank.prev_st = st;
        next_blank.character = '\0';
        next_blank.ncc = 0.0f;
      }

      // Allowed transitions based on grammar
      std::vector<std::pair<char, int>> allowed;
      if (st == 0) {
        for (char d = '0'; d <= '9'; ++d)
          allowed.emplace_back(d, 0);
        allowed.emplace_back('[', 1);
      } else if (st == 1) {
        for (char d = '0'; d <= '9'; ++d)
          allowed.emplace_back(d, 1);
        allowed.emplace_back('.', 1);
        allowed.emplace_back('%', 2);
      } else if (st == 2) {
        allowed.emplace_back(']', 3);
      } else {
        continue;
      }

      for (const auto& tr : allowed) {
        char ch = tr.first;
        int next_st = tr.second;

        auto it = prepared_templates_.find(ch);
        if (it == prepared_templates_.end()) continue;
        const PreparedTemplate& t = it->second;

        auto resp_it = responses.find(ch);
        if (resp_it == responses.end()) continue;
        const auto& resp_vec = resp_it->second;

        float min_ncc = (ch == '1' || ch == ']') ? kMinNccNarrowOrBracket : kMinNccDigitOrDot;
        int min_adv = (ch == '.') ? 4 : ((ch == '[' || ch == ']') ? 6 : std::max(t.width, 11));

        if (x + t.width <= win_w && x < static_cast<int>(resp_vec.size())) {
          float ncc = resp_vec[x];
          if (ncc >= min_ncc) {
            float excess = ncc - kNccExcessBase;
            int eff_w = std::max(t.width, 11);
            float gain = (excess * excess) * eff_w - kCharPenalty;
            float cand_score = score + gain;
            int next_x = x + min_adv;

            if (next_x <= win_w) {
              DpNode& next_node = get_dp(next_x, next_st);
              if (cand_score > next_node.score) {
                next_node.score = cand_score;
                next_node.prev_x = x;
                next_node.prev_st = st;
                next_node.character = ch;
                next_node.ncc = ncc;
              }
            }
          }
        }
      }
    }
  }

  // Select best terminal state in state 3
  int best_term_x = -1;
  int best_term_st = -1;
  float best_term_score = -1e8f;

  for (int x = 0; x <= win_w; ++x) {
    const DpNode& node = get_dp(x, 3);
    if (node.score > best_term_score) {
      best_term_score = node.score;
      best_term_x = x;
      best_term_st = 3;
    }
  }

  // Require completed grammar (state 3 reached with closing bracket)
  if (best_term_x == -1 || best_term_score <= 0.0f) {
    return false;
  }

  // Backtrack to extract recognized character sequence
  std::vector<RecognizedChar> chars;
  int cur_x = best_term_x;
  int cur_st = best_term_st;

  while (cur_x >= 0 && cur_st >= 0) {
    const DpNode& node = get_dp(cur_x, cur_st);
    if (node.prev_x < 0) break;
    if (node.character != '\0') {
      chars.push_back({node.prev_x, node.character, node.ncc});
    }
    cur_x = node.prev_x;
    cur_st = node.prev_st;
  }

  std::reverse(chars.begin(), chars.end());

  std::string raw_str;
  for (const auto& rc : chars) {
    raw_str.push_back(rc.character);
  }

  // Grammar check: must contain '['
  size_t bracket_pos = raw_str.find('[');
  if (bracket_pos == std::string::npos) {
    return false;
  }

  std::string exp_digits = raw_str.substr(0, bracket_pos);
  std::string pct_part = raw_str.substr(bracket_pos + 1);

  size_t closing_pos = pct_part.find(']');
  if (closing_pos != std::string::npos) {
    pct_part = pct_part.substr(0, closing_pos);
  }
  if (!pct_part.empty() && pct_part.back() == '%') {
    pct_part.pop_back();
  }

  int64_t exp_val = 0;
  if (!exp_digits.empty()) {
    char* end = nullptr;
    exp_val = std::strtoll(exp_digits.c_str(), &end, 10);
  }

  double pct_val = 0.0;
  if (!pct_part.empty()) {
    char* end = nullptr;
    pct_val = std::strtod(pct_part.c_str(), &end);
    if (end != nullptr && *end != '\0') {
      pct_val = 0.0;
    }
  }

  auto t_end = std::chrono::steady_clock::now();
  float dt_ms = std::chrono::duration<float, std::milli>(t_end - t_start).count();

  out_result->success = true;
  out_result->exp_value = exp_val;
  out_result->exp_percent = pct_val;
  out_result->raw_string = raw_str;
  out_result->parse_time_ms = dt_ms;
  out_result->characters = std::move(chars);

  return true;
}

}  // namespace exp
}  // namespace artale
