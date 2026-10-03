// Copyright 2026 Artale Exp Project. All rights reserved.
// Google C++ Style Guide compliant.

#include "src/cpp/src/exp_engine_avx2.h"

#if defined(__x86_64__) || defined(_M_X64)

#include <immintrin.h>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <vector>

namespace artale {
namespace exp {

namespace {

inline int CvRound(float value) {
  return _mm_cvtss_si32(_mm_set_ss(value));
}

}  // namespace

void ResizeGrayAVX2(const uint8_t* src, int src_w, int src_h, int src_stride,
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
    const __m128i vb0 = _mm_set1_epi16(static_cast<int16_t>(b0));
    const __m128i vb1 = _mm_set1_epi16(static_cast<int16_t>(b1));
    const __m128i v2 = _mm_set1_epi16(2);

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

void MatchTemplateNccAVX2(const float* image, int img_w, int img_h, int img_stride,
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

#endif  // defined(__x86_64__) || defined(_M_X64)
