// Copyright 2026 Artale Exp Project. All rights reserved.
// Google C++ Style Guide compliant.

#include "src/cpp/src/exp_engine.h"

#if defined(__SSE2__) || defined(_M_X64) || defined(__x86_64__)
#include <immintrin.h>
#elif defined(__ARM_NEON) || defined(__aarch64__)
#include <arm_neon.h>
#endif

#include <cmath>
#include <cstdint>
#include <string>
#include <vector>

#include "gtest/gtest.h"
#include "src/cpp/include/artale_exp_core.h"
#include "src/cpp/src/pristine_font_protos.h"

namespace artale {
namespace exp {
namespace {

inline int TestCvRound(float value) {
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

TEST(ExpEngineTest, ResizeGrayPreservesUniformValues) {
  constexpr int kSrcW = 10;
  constexpr int kSrcH = 10;
  constexpr int kDstW = 25;
  constexpr int kDstH = 25;
  std::vector<uint8_t> src(kSrcW * kSrcH, 128);
  std::vector<uint8_t> dst(kDstW * kDstH, 0);

  ExpEngine::ResizeGray(src.data(), kSrcW, kSrcH, kSrcW, dst.data(), kDstW, kDstH, kDstW);

  for (size_t i = 0; i < dst.size(); ++i) {
    EXPECT_EQ(dst[i], 128);
  }
}

TEST(ExpEngineTest, ResizeGrayBilinearInterpolation) {
  constexpr int kSrcW = 2;
  constexpr int kSrcH = 2;
  constexpr int kDstW = 3;
  constexpr int kDstH = 3;
  // Simple 2x2 ramp:
  // [  0, 100 ]
  // [  0, 100 ]
  std::vector<uint8_t> src = {0, 100, 0, 100};
  std::vector<uint8_t> dst(kDstW * kDstH, 0);

  ExpEngine::ResizeGray(src.data(), kSrcW, kSrcH, kSrcW, dst.data(), kDstW, kDstH, kDstW);

  // Center column should be roughly 50
  EXPECT_NEAR(dst[1], 50, 2);
  EXPECT_NEAR(dst[4], 50, 2);
  EXPECT_NEAR(dst[7], 50, 2);
}

void ResizeGrayScalarReference(const uint8_t* src, int src_w, int src_h, int src_stride,
                               uint8_t* dst, int dst_w, int dst_h, int dst_stride) {
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
    ialpha[dx * 2 + 0] = static_cast<int16_t>(TestCvRound(c0 * kScale));
    ialpha[dx * 2 + 1] = static_cast<int16_t>(TestCvRound(c1 * kScale));
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
    ibeta[dy * 2 + 0] = static_cast<int16_t>(TestCvRound(c0 * kScale));
    ibeta[dy * 2 + 1] = static_cast<int16_t>(TestCvRound(c1 * kScale));
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

TEST(ExpEngineTest, SimdResizeMatchesScalarExactAcrossArbitrarySizes) {
  struct SizeCase {
    int sw, sh, dw, dh;
  };
  const SizeCase kCases[] = {
      {10, 10, 25, 25},   {15, 15, 19, 19},   {30, 20, 25, 17},
      {33, 33, 49, 49},   {100, 38, 77, 25},  {230, 25, 180, 21},
      {350, 38, 230, 25}, {416, 16, 988, 38}, {1247, 38, 1247, 38},
  };

  for (const auto& sc : kCases) {
    std::vector<uint8_t> src(sc.sw * sc.sh);
    for (size_t i = 0; i < src.size(); ++i) {
      src[i] = static_cast<uint8_t>((i * 73 + 19) % 256);
    }
    std::vector<uint8_t> dst_simd(sc.dw * sc.dh, 0);
    std::vector<uint8_t> dst_scalar(sc.dw * sc.dh, 0);

    ExpEngine::ResizeGray(src.data(), sc.sw, sc.sh, sc.sw, dst_simd.data(), sc.dw, sc.dh, sc.dw);
    ResizeGrayScalarReference(src.data(), sc.sw, sc.sh, sc.sw, dst_scalar.data(), sc.dw, sc.dh,
                              sc.dw);

    for (int i = 0; i < sc.dw * sc.dh; ++i) {
      ASSERT_EQ(dst_simd[i], dst_scalar[i]) << "Mismatch at index " << i << " in size " << sc.sw
                                            << "x" << sc.sh << " -> " << sc.dw << "x" << sc.dh;
    }
  }
}

TEST(ExpEngineTest, MatchTemplateNccFindsExactMatch) {
  // Create an image with an embedded template
  const PristinePrototype& proto_8 = kPristinePrototypes[8];  // '8'
  const int tw = proto_8.width;
  const int th = proto_8.height;

  PreparedTemplate pt;
  pt.character = '8';
  pt.width = tw;
  pt.height = th;
  pt.zero_mean_fmap.resize(tw * th);

  double sum = 0.0;
  for (int i = 0; i < tw * th; ++i)
    sum += proto_8.float_map[i];
  float mean = static_cast<float>(sum / (tw * th));
  double sum_sq = 0.0;
  for (int i = 0; i < tw * th; ++i) {
    float zm = proto_8.float_map[i] - mean;
    pt.zero_mean_fmap[i] = zm;
    sum_sq += zm * zm;
  }
  pt.norm = static_cast<float>(std::sqrt(sum_sq));

  constexpr int kImgW = 40;
  constexpr int kImgH = 40;
  constexpr int kTargetX = 14;
  constexpr int kTargetY = 8;
  std::vector<float> image(kImgW * kImgH, 20.0f);

  // Embed prototype scaled by 255.0f into image at (kTargetX, kTargetY)
  for (int y = 0; y < th; ++y) {
    for (int x = 0; x < tw; ++x) {
      image[(kTargetY + y) * kImgW + (kTargetX + x)] = proto_8.float_map[y * tw + x] * 255.0f;
    }
  }

  const int out_w = kImgW - tw + 1;
  const int out_h = kImgH - th + 1;
  std::vector<float> resp(out_w * out_h, 0.0f);

  ExpEngine::MatchTemplateNcc(image.data(), kImgW, kImgH, kImgW, pt, resp.data());

  float best_score = -1.0f;
  int best_x = -1;
  int best_y = -1;
  for (int y = 0; y < out_h; ++y) {
    for (int x = 0; x < out_w; ++x) {
      float score = resp[y * out_w + x];
      if (score > best_score) {
        best_score = score;
        best_x = x;
        best_y = y;
      }
    }
  }

  EXPECT_EQ(best_x, kTargetX);
  EXPECT_EQ(best_y, kTargetY);
  EXPECT_GT(best_score, 0.99f);
}

TEST(ExpEngineTest, ParseCropRejectsTooSmallOrInvalid) {
  ExpEngine engine;
  CropParseResult result;
  std::vector<uint8_t> tiny(10 * 10, 0);

  EXPECT_FALSE(engine.ParseCrop(nullptr, 100, 30, 100, &result));
  EXPECT_FALSE(engine.ParseCrop(tiny.data(), 10, 10, 10, &result));
}

TEST(ExpEngineTest, ParseCropRecognizesSynthesizedExpStrip) {
  ExpEngine engine;

  // Synthesize a canonical 38px height strip with "772097[0.32%]"
  std::string text = "772097[0.32%]";
  constexpr int kStripH = 38;
  constexpr int kStripW = 350;
  std::vector<uint8_t> strip(kStripW * kStripH, 0);

  // Find prototypes for each character and render onto strip
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
    ASSERT_NE(found, nullptr);

    int char_y = (found->height == 25) ? base_y : (base_y + 2);
    for (int y = 0; y < found->height; ++y) {
      for (int x = 0; x < found->width; ++x) {
        float val = found->float_map[y * found->width + x];
        strip[(char_y + y) * kStripW + (cur_x + x)] =
            static_cast<uint8_t>(std::round(val * 255.0f));
      }
    }
    cur_x += (ch == '.') ? 6 : (found->width + 2);
  }

  CropParseResult result;
  bool ok = engine.ParseCrop(strip.data(), kStripW, kStripH, kStripW, &result);

  EXPECT_TRUE(ok);
  EXPECT_EQ(result.exp_value, 772097);
  EXPECT_NEAR(result.exp_percent, 0.32, 1e-4);
  EXPECT_EQ(result.raw_string, "772097[0.32%]");
}

TEST(ExpEngineTest, ExtractGraySubRectExactConversion) {
  constexpr int kWidth = 4;
  constexpr int kHeight = 2;
  std::vector<uint8_t> bgr = {
      255, 0,   0,   0, 255, 0, 0,  0,   255, 255, 255, 255,
      100, 100, 100, 0, 0,   0, 50, 150, 200, 128, 64,  32,
  };
  std::vector<uint8_t> out_gray(kWidth * kHeight, 0);

  Test_ExtractGraySubRect(bgr.data(), kWidth, kHeight, kWidth * 3, 3, 0, 0, kWidth, kHeight,
                          out_gray.data());

  EXPECT_EQ(out_gray[0], 29);
  EXPECT_EQ(out_gray[1], 150);
  EXPECT_EQ(out_gray[2], 76);
  EXPECT_EQ(out_gray[3], 255);
  EXPECT_EQ(out_gray[4], 100);
  EXPECT_EQ(out_gray[5], 0);
}

TEST(ExpEngineTest, ParseCropLowResWithoutDigit8AndStrictGrammar) {
  ExpEngine engine;
  constexpr int kStripH = 38;
  constexpr int kStripW = 420;

  auto render_strip = [&](const std::string& text, int gap_idx, int extra_gap) {
    std::vector<uint8_t> strip(kStripW * kStripH, 0);
    int cur_x = 20;
    int base_y = 6;
    for (size_t idx = 0; idx < text.size(); ++idx) {
      char ch = text[idx];
      const PristinePrototype* found = nullptr;
      for (size_t i = 0; i < kNumPristinePrototypes; ++i) {
        if (kPristinePrototypes[i].character == ch) {
          found = &kPristinePrototypes[i];
          break;
        }
      }
      if (found == nullptr) continue;
      int char_y = (found->height == 25) ? base_y : (base_y + 2);
      for (int y = 0; y < found->height; ++y) {
        for (int x = 0; x < found->width; ++x) {
          float val = found->float_map[y * found->width + x];
          strip[(char_y + y) * kStripW + (cur_x + x)] =
              static_cast<uint8_t>(std::round(val * 255.0f));
        }
      }
      cur_x += (ch == '.') ? 6 : (found->width + 2);
      if (static_cast<int>(idx) == gap_idx) {
        cur_x += extra_gap;
      }
    }
    return strip;
  };

  // 1. Downscale "444444442[44.44%]" to 210x19 (1920x720 crop height)
  std::vector<uint8_t> canonical = render_strip("444444442[44.44%]", -1, 0);
  std::vector<uint8_t> low_res(210 * 19, 0);
  ExpEngine::ResizeGray(canonical.data(), kStripW, kStripH, kStripW, low_res.data(), 210, 19, 210);

  CropParseResult res;
  ASSERT_TRUE(engine.ParseCrop(low_res.data(), 210, 19, 210, &res));
  EXPECT_EQ(res.exp_value, 444444442);
  EXPECT_NEAR(res.exp_percent, 44.44, 1e-4);
  EXPECT_EQ(res.raw_string, "444444442[44.44%]");

  // 2. Verify 1-decimal-digit percentage format (e.g. "772097[0.3%]" and "123456[12.5%]")
  std::vector<uint8_t> one_dec1 = render_strip("772097[0.3%]", -1, 0);
  ASSERT_TRUE(engine.ParseCrop(one_dec1.data(), kStripW, kStripH, kStripW, &res));
  EXPECT_EQ(res.exp_value, 772097);
  EXPECT_NEAR(res.exp_percent, 0.3, 1e-4);
  EXPECT_EQ(res.raw_string, "772097[0.3%]");

  std::vector<uint8_t> one_dec2 = render_strip("123456[12.5%]", -1, 0);
  std::vector<uint8_t> one_dec2_low(210 * 19, 0);
  ExpEngine::ResizeGray(one_dec2.data(), kStripW, kStripH, kStripW, one_dec2_low.data(), 210, 19, 210);
  ASSERT_TRUE(engine.ParseCrop(one_dec2_low.data(), 210, 19, 210, &res));
  EXPECT_EQ(res.exp_value, 123456);
  EXPECT_NEAR(res.exp_percent, 12.5, 1e-4);
  EXPECT_EQ(res.raw_string, "123456[12.5%]");

  // 3. Reject malformed grammar and occluded gaps
  std::vector<uint8_t> bad1 = render_strip("6[%]", -1, 0);
  EXPECT_FALSE(engine.ParseCrop(bad1.data(), kStripW, kStripH, kStripW, &res));

  std::vector<uint8_t> bad2 = render_strip("[84.99%]", -1, 0);
  EXPECT_FALSE(engine.ParseCrop(bad2.data(), kStripW, kStripH, kStripW, &res));

  std::vector<uint8_t> gapped = render_strip("6[0.00%]", 0, 50);
  EXPECT_FALSE(engine.ParseCrop(gapped.data(), kStripW, kStripH, kStripW, &res));
}

#if !defined(__ARM_NEON) && !defined(__aarch64__)
// Lightweight host-side ARM NEON intrinsic semantics verifier so that all
// #elif defined(__ARM_NEON) code paths in ExtractGraySubRect, ResizeGray, and
// MatchTemplateNcc are continuously verified for bit-exactness on x86_64 CI/hosts.
namespace neon_verify {

struct uint8x8_t { uint8_t v[8]; };
struct uint8x16_t { uint8_t v[16]; };
struct uint8x8x3_t { uint8x8_t val[3]; };
struct uint8x8x4_t { uint8x8_t val[4]; };
struct uint16x4_t { uint16_t v[4]; };
struct uint16x8_t { uint16_t v[8]; };
struct int16x4_t { int16_t v[4]; };
struct int16x8_t { int16_t v[8]; };
struct int32x4_t { int32_t v[4]; };
struct uint32x4_t { uint32_t v[4]; };
struct uint64x2_t { uint64_t v[2]; };
struct float32x4_t { float v[4]; };
struct float64x2_t { double v[2]; };

inline int16x8_t vdupq_n_s16(int16_t x) { int16x8_t r; for (int i = 0; i < 8; ++i) r.v[i] = x; return r; }
inline int32x4_t vdupq_n_s32(int32_t x) { return {{x, x, x, x}}; }
inline uint32x4_t vdupq_n_u32(uint32_t x) { return {{x, x, x, x}}; }
inline uint64x2_t vdupq_n_u64(uint64_t x) { return {{x, x}}; }
inline float32x4_t vdupq_n_f32(float x) { return {{x, x, x, x}}; }
inline float64x2_t vdupq_n_f64(double x) { return {{x, x}}; }

inline uint8x16_t vld1q_u8(const uint8_t* p) { uint8x16_t r; std::memcpy(r.v, p, 16); return r; }
inline void vst1_u8(uint8_t* p, uint8x8_t a) { std::memcpy(p, a.v, 8); }
inline void vst1q_u8(uint8_t* p, uint8x16_t a) { std::memcpy(p, a.v, 16); }
inline int16x8_t vld1q_s16(const int16_t* p) { int16x8_t r; std::memcpy(r.v, p, 16); return r; }
inline float32x4_t vld1q_f32(const float* p) { float32x4_t r; std::memcpy(r.v, p, 16); return r; }
inline void vst1q_f32(float* p, float32x4_t a) { std::memcpy(p, a.v, 16); }
inline float64x2_t vld1q_f64(const double* p) { float64x2_t r; std::memcpy(r.v, p, 16); return r; }
inline void vst1q_f64(double* p, float64x2_t a) { std::memcpy(p, a.v, 16); }

inline uint8x8x3_t vld3_u8(const uint8_t* p) {
  uint8x8x3_t r;
  for (int i = 0; i < 8; ++i) {
    r.val[0].v[i] = p[i * 3 + 0];
    r.val[1].v[i] = p[i * 3 + 1];
    r.val[2].v[i] = p[i * 3 + 2];
  }
  return r;
}
inline uint8x8x4_t vld4_u8(const uint8_t* p) {
  uint8x8x4_t r;
  for (int i = 0; i < 8; ++i) {
    r.val[0].v[i] = p[i * 4 + 0];
    r.val[1].v[i] = p[i * 4 + 1];
    r.val[2].v[i] = p[i * 4 + 2];
    r.val[3].v[i] = p[i * 4 + 3];
  }
  return r;
}

inline uint8x8_t vget_low_u8(uint8x16_t a) { uint8x8_t r; std::memcpy(r.v, a.v, 8); return r; }
inline uint8x8_t vget_high_u8(uint8x16_t a) { uint8x8_t r; std::memcpy(r.v, a.v + 8, 8); return r; }
inline uint16x8_t vmovl_u8(uint8x8_t a) { uint16x8_t r; for (int i = 0; i < 8; ++i) r.v[i] = a.v[i]; return r; }
inline int16x8_t vreinterpretq_s16_u16(uint16x8_t a) { int16x8_t r; std::memcpy(r.v, a.v, 16); return r; }
inline uint16x4_t vget_low_u16(uint16x8_t a) { return {{a.v[0], a.v[1], a.v[2], a.v[3]}}; }
inline uint16x4_t vget_high_u16(uint16x8_t a) { return {{a.v[4], a.v[5], a.v[6], a.v[7]}}; }
inline int16x4_t vget_low_s16(int16x8_t a) { return {{a.v[0], a.v[1], a.v[2], a.v[3]}}; }
inline int16x4_t vget_high_s16(int16x8_t a) { return {{a.v[4], a.v[5], a.v[6], a.v[7]}}; }

inline uint32x4_t vmlal_n_u16(uint32x4_t acc, uint16x4_t a, uint16_t n) {
  for (int i = 0; i < 4; ++i) acc.v[i] += static_cast<uint32_t>(a.v[i]) * n;
  return acc;
}
inline uint16x4_t vshrn_n_u32(uint32x4_t a, int n) {
  uint16x4_t r;
  for (int i = 0; i < 4; ++i) r.v[i] = static_cast<uint16_t>(a.v[i] >> n);
  return r;
}
inline uint16x8_t vcombine_u16(uint16x4_t lo, uint16x4_t hi) {
  return {{lo.v[0], lo.v[1], lo.v[2], lo.v[3], hi.v[0], hi.v[1], hi.v[2], hi.v[3]}};
}
inline uint8x8_t vmovn_u16(uint16x8_t a) {
  uint8x8_t r;
  for (int i = 0; i < 8; ++i) r.v[i] = static_cast<uint8_t>(a.v[i]);
  return r;
}

inline int32x4_t vmull_s16(int16x4_t a, int16x4_t b) {
  int32x4_t r;
  for (int i = 0; i < 4; ++i) r.v[i] = static_cast<int32_t>(a.v[i]) * static_cast<int32_t>(b.v[i]);
  return r;
}
inline int32x4_t vpaddq_s32(int32x4_t a, int32x4_t b) {
  return {{a.v[0] + a.v[1], a.v[2] + a.v[3], b.v[0] + b.v[1], b.v[2] + b.v[3]}};
}
inline int32x4_t vshrq_n_s32(int32x4_t a, int n) {
  return {{a.v[0] >> n, a.v[1] >> n, a.v[2] >> n, a.v[3] >> n}};
}
inline int16x4_t vqmovn_s32(int32x4_t a) {
  int16x4_t r;
  for (int i = 0; i < 4; ++i) {
    int32_t v = std::max(-32768, std::min(32767, a.v[i]));
    r.v[i] = static_cast<int16_t>(v);
  }
  return r;
}
inline int16x8_t vcombine_s16(int16x4_t lo, int16x4_t hi) {
  return {{lo.v[0], lo.v[1], lo.v[2], lo.v[3], hi.v[0], hi.v[1], hi.v[2], hi.v[3]}};
}
inline int32x4_t vaddq_s32(int32x4_t a, int32x4_t b) {
  return {{a.v[0] + b.v[0], a.v[1] + b.v[1], a.v[2] + b.v[2], a.v[3] + b.v[3]}};
}
inline uint8x8_t vqmovun_s16(int16x8_t a) {
  uint8x8_t r;
  for (int i = 0; i < 8; ++i) {
    int16_t v = std::max<int16_t>(0, std::min<int16_t>(255, a.v[i]));
    r.v[i] = static_cast<uint8_t>(v);
  }
  return r;
}
inline uint8x16_t vcombine_u8(uint8x8_t lo, uint8x8_t hi) {
  uint8x16_t r;
  std::memcpy(r.v, lo.v, 8);
  std::memcpy(r.v + 8, hi.v, 8);
  return r;
}

inline float64x2_t vcvt_f64_f32(float32x4_t a) { return {{a.v[0], a.v[1]}}; }
inline float32x4_t vget_low_f32(float32x4_t a) { return a; }
inline float64x2_t vcvt_high_f64_f32(float32x4_t a) { return {{a.v[2], a.v[3]}}; }
inline float64x2_t vaddq_f64(float64x2_t a, float64x2_t b) { return {{a.v[0] + b.v[0], a.v[1] + b.v[1]}}; }
inline float64x2_t vsubq_f64(float64x2_t a, float64x2_t b) { return {{a.v[0] - b.v[0], a.v[1] - b.v[1]}}; }
inline float64x2_t vmulq_f64(float64x2_t a, float64x2_t b) { return {{a.v[0] * b.v[0], a.v[1] * b.v[1]}}; }
inline float64x2_t vdivq_f64(float64x2_t a, float64x2_t b) { return {{a.v[0] / b.v[0], a.v[1] / b.v[1]}}; }
inline float64x2_t vsqrtq_f64(float64x2_t a) { return {{std::sqrt(a.v[0]), std::sqrt(a.v[1])}}; }
inline float64x2_t vfmaq_f64(float64x2_t acc, float64x2_t a, float64x2_t b) {
  return {{std::fma(a.v[0], b.v[0], acc.v[0]), std::fma(a.v[1], b.v[1], acc.v[1])}};
}
inline float64x2_t vfmsq_f64(float64x2_t acc, float64x2_t a, float64x2_t b) {
  return {{std::fma(-a.v[0], b.v[0], acc.v[0]), std::fma(-a.v[1], b.v[1], acc.v[1])}};
}
inline uint64x2_t vcgtq_f64(float64x2_t a, float64x2_t b) {
  return {{a.v[0] > b.v[0] ? ~0ULL : 0ULL, a.v[1] > b.v[1] ? ~0ULL : 0ULL}};
}
inline float64x2_t vreinterpretq_f64_u64(uint64x2_t a) {
  float64x2_t r;
  std::memcpy(r.v, a.v, 16);
  return r;
}
inline float64x2_t vbslq_f64(uint64x2_t mask, float64x2_t a, float64x2_t b) {
  uint64_t ua[2], ub[2], ur[2];
  std::memcpy(ua, a.v, 16);
  std::memcpy(ub, b.v, 16);
  ur[0] = (ua[0] & mask.v[0]) | (ub[0] & ~mask.v[0]);
  ur[1] = (ua[1] & mask.v[1]) | (ub[1] & ~mask.v[1]);
  float64x2_t r;
  std::memcpy(r.v, ur, 16);
  return r;
}
inline float32x4_t vcvt_f32_f64(float64x2_t a) {
  return {{static_cast<float>(a.v[0]), static_cast<float>(a.v[1]), 0.0f, 0.0f}};
}
inline float32x4_t vcombine_f32(float32x4_t lo, float32x4_t hi) {
  return {{lo.v[0], lo.v[1], hi.v[0], hi.v[1]}};
}
inline float32x4_t vfmaq_f32(float32x4_t acc, float32x4_t a, float32x4_t b) {
  for (int i = 0; i < 4; ++i) acc.v[i] = std::fmaf(a.v[i], b.v[i], acc.v[i]);
  return acc;
}
inline float32x4_t vaddq_f32(float32x4_t a, float32x4_t b) {
  for (int i = 0; i < 4; ++i) a.v[i] += b.v[i];
  return a;
}
inline float32x4_t vmulq_f32(float32x4_t a, float32x4_t b) {
  for (int i = 0; i < 4; ++i) a.v[i] *= b.v[i];
  return a;
}
inline float32x4_t vminq_f32(float32x4_t a, float32x4_t b) {
  for (int i = 0; i < 4; ++i) a.v[i] = std::min(a.v[i], b.v[i]);
  return a;
}
inline float32x4_t vmaxq_f32(float32x4_t a, float32x4_t b) {
  for (int i = 0; i < 4; ++i) a.v[i] = std::max(a.v[i], b.v[i]);
  return a;
}

void ExtractGraySubRectNeon(const uint8_t* bgr_data, int width, int height, int stride,
                            int bytes_per_px, int rx, int ry, int rw, int rh, uint8_t* out_gray) {
  for (int y = 0; y < rh; ++y) {
    int src_y = ry + y;
    if (src_y < 0 || src_y >= height) continue;
    const uint8_t* src_row = bgr_data + src_y * stride;
    uint8_t* dst_row = out_gray + y * rw;
    int x = 0;
    if (rx >= 0 && rx + rw <= width) {
      if (bytes_per_px == 4) {
        for (; x + 7 < rw; x += 8) {
          const uint8_t* px = src_row + (rx + x) * 4;
          uint8x8x4_t bgra = vld4_u8(px);
          uint16x8_t b16 = vmovl_u8(bgra.val[0]);
          uint16x8_t g16 = vmovl_u8(bgra.val[1]);
          uint16x8_t r16 = vmovl_u8(bgra.val[2]);
          uint32x4_t s_lo = vdupq_n_u32(16384);
          s_lo = vmlal_n_u16(s_lo, vget_low_u16(b16), 3735);
          s_lo = vmlal_n_u16(s_lo, vget_low_u16(g16), 19235);
          s_lo = vmlal_n_u16(s_lo, vget_low_u16(r16), 9798);
          uint32x4_t s_hi = vdupq_n_u32(16384);
          s_hi = vmlal_n_u16(s_hi, vget_high_u16(b16), 3735);
          s_hi = vmlal_n_u16(s_hi, vget_high_u16(g16), 19235);
          s_hi = vmlal_n_u16(s_hi, vget_high_u16(r16), 9798);
          uint8x8_t res = vmovn_u16(vcombine_u16(vshrn_n_u32(s_lo, 15), vshrn_n_u32(s_hi, 15)));
          vst1_u8(dst_row + x, res);
        }
      } else if (bytes_per_px == 3) {
        for (; x + 7 < rw; x += 8) {
          const uint8_t* px = src_row + (rx + x) * 3;
          uint8x8x3_t bgr = vld3_u8(px);
          uint16x8_t b16 = vmovl_u8(bgr.val[0]);
          uint16x8_t g16 = vmovl_u8(bgr.val[1]);
          uint16x8_t r16 = vmovl_u8(bgr.val[2]);
          uint32x4_t s_lo = vdupq_n_u32(16384);
          s_lo = vmlal_n_u16(s_lo, vget_low_u16(b16), 3735);
          s_lo = vmlal_n_u16(s_lo, vget_low_u16(g16), 19235);
          s_lo = vmlal_n_u16(s_lo, vget_low_u16(r16), 9798);
          uint32x4_t s_hi = vdupq_n_u32(16384);
          s_hi = vmlal_n_u16(s_hi, vget_high_u16(b16), 3735);
          s_hi = vmlal_n_u16(s_hi, vget_high_u16(g16), 19235);
          s_hi = vmlal_n_u16(s_hi, vget_high_u16(r16), 9798);
          uint8x8_t res = vmovn_u16(vcombine_u16(vshrn_n_u32(s_lo, 15), vshrn_n_u32(s_hi, 15)));
          vst1_u8(dst_row + x, res);
        }
      }
    }
    for (; x < rw; ++x) {
      const uint8_t* px = src_row + (rx + x) * bytes_per_px;
      dst_row[x] = static_cast<uint8_t>((px[0] * 3735 + px[1] * 19235 + px[2] * 9798 + 16384) >> 15);
    }
  }
}

void ResizeGrayNeon(const uint8_t* src, int src_w, int src_h, int src_stride, uint8_t* dst,
                    int dst_w, int dst_h, int dst_stride) {
  constexpr int kShift = 11;
  constexpr int kScale = 1 << kShift;
  std::vector<int> xofs(dst_w * 2);
  std::vector<int16_t> ialpha(dst_w * 2);
  const double scale_x = static_cast<double>(src_w) / dst_w;
  for (int dx = 0; dx < dst_w; ++dx) {
    float fx = static_cast<float>((dx + 0.5) * scale_x - 0.5);
    int sx = static_cast<int>(std::floor(fx));
    fx -= sx;
    if (sx < 0) { fx = 0.0f; sx = 0; }
    if (sx >= src_w - 1) { fx = 0.0f; sx = src_w - 1; }
    xofs[dx * 2 + 0] = sx;
    xofs[dx * 2 + 1] = std::min(sx + 1, src_w - 1);
    ialpha[dx * 2 + 0] = static_cast<int16_t>(TestCvRound((1.0f - fx) * kScale));
    ialpha[dx * 2 + 1] = static_cast<int16_t>(TestCvRound(fx * kScale));
  }
  std::vector<int> yofs(dst_h);
  std::vector<int16_t> ibeta(dst_h * 2);
  const double scale_y = static_cast<double>(src_h) / dst_h;
  for (int dy = 0; dy < dst_h; ++dy) {
    float fy = static_cast<float>((dy + 0.5) * scale_y - 0.5);
    int sy = static_cast<int>(std::floor(fy));
    fy -= sy;
    yofs[dy] = sy;
    ibeta[dy * 2 + 0] = static_cast<int16_t>(TestCvRound((1.0f - fy) * kScale));
    ibeta[dy * 2 + 1] = static_cast<int16_t>(TestCvRound(fy * kScale));
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
      alignas(16) uint16_t w0_0[8], w1_0[8], w0_1[8], w1_1[8];
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
      int32x4_t s0_0_lo = vshrq_n_s32(vpaddq_s32(vmull_s16(vget_low_s16(r0_0_lo), vget_low_s16(a0_lo)),
                                                 vmull_s16(vget_high_s16(r0_0_lo), vget_high_s16(a0_lo))), 4);
      int32x4_t s0_0_hi = vshrq_n_s32(vpaddq_s32(vmull_s16(vget_low_s16(r0_0_hi), vget_low_s16(a0_hi)),
                                                 vmull_s16(vget_high_s16(r0_0_hi), vget_high_s16(a0_hi))), 4);
      int32x4_t s1_0_lo = vshrq_n_s32(vpaddq_s32(vmull_s16(vget_low_s16(r1_0_lo), vget_low_s16(a0_lo)),
                                                 vmull_s16(vget_high_s16(r1_0_lo), vget_high_s16(a0_lo))), 4);
      int32x4_t s1_0_hi = vshrq_n_s32(vpaddq_s32(vmull_s16(vget_low_s16(r1_0_hi), vget_low_s16(a0_hi)),
                                                 vmull_s16(vget_high_s16(r1_0_hi), vget_high_s16(a0_hi))), 4);
      int16x8_t s0_0_16 = vcombine_s16(vqmovn_s32(s0_0_lo), vqmovn_s32(s0_0_hi));
      int16x8_t s1_0_16 = vcombine_s16(vqmovn_s32(s1_0_lo), vqmovn_s32(s1_0_hi));
      int32x4_t t0_0_lo = vshrq_n_s32(vmull_s16(vget_low_s16(s0_0_16), vget_low_s16(vb0)), 16);
      int32x4_t t1_0_lo = vshrq_n_s32(vmull_s16(vget_low_s16(s1_0_16), vget_low_s16(vb1)), 16);
      int32x4_t val0_lo = vshrq_n_s32(vaddq_s32(vaddq_s32(t0_0_lo, t1_0_lo), vtwo), 2);
      int32x4_t t0_0_hi = vshrq_n_s32(vmull_s16(vget_high_s16(s0_0_16), vget_high_s16(vb0)), 16);
      int32x4_t t1_0_hi = vshrq_n_s32(vmull_s16(vget_high_s16(s1_0_16), vget_high_s16(vb1)), 16);
      int32x4_t val0_hi = vshrq_n_s32(vaddq_s32(vaddq_s32(t0_0_hi, t1_0_hi), vtwo), 2);
      uint8x8_t res0 = vqmovun_s16(vcombine_s16(vqmovn_s32(val0_lo), vqmovn_s32(val0_hi)));

      uint8x16_t r0_1_u8 = vld1q_u8(reinterpret_cast<const uint8_t*>(w0_1));
      uint8x16_t r1_1_u8 = vld1q_u8(reinterpret_cast<const uint8_t*>(w1_1));
      int16x8_t r0_1_lo = vreinterpretq_s16_u16(vmovl_u8(vget_low_u8(r0_1_u8)));
      int16x8_t r0_1_hi = vreinterpretq_s16_u16(vmovl_u8(vget_high_u8(r0_1_u8)));
      int16x8_t r1_1_lo = vreinterpretq_s16_u16(vmovl_u8(vget_low_u8(r1_1_u8)));
      int16x8_t r1_1_hi = vreinterpretq_s16_u16(vmovl_u8(vget_high_u8(r1_1_u8)));
      int16x8_t a1_lo = vld1q_s16(ialpha.data() + (dx + 8) * 2);
      int16x8_t a1_hi = vld1q_s16(ialpha.data() + (dx + 8) * 2 + 8);
      int32x4_t s0_1_lo = vshrq_n_s32(vpaddq_s32(vmull_s16(vget_low_s16(r0_1_lo), vget_low_s16(a1_lo)),
                                                 vmull_s16(vget_high_s16(r0_1_lo), vget_high_s16(a1_lo))), 4);
      int32x4_t s0_1_hi = vshrq_n_s32(vpaddq_s32(vmull_s16(vget_low_s16(r0_1_hi), vget_low_s16(a1_hi)),
                                                 vmull_s16(vget_high_s16(r0_1_hi), vget_high_s16(a1_hi))), 4);
      int32x4_t s1_1_lo = vshrq_n_s32(vpaddq_s32(vmull_s16(vget_low_s16(r1_1_lo), vget_low_s16(a1_lo)),
                                                 vmull_s16(vget_high_s16(r1_1_lo), vget_high_s16(a1_lo))), 4);
      int32x4_t s1_1_hi = vshrq_n_s32(vpaddq_s32(vmull_s16(vget_low_s16(r1_1_hi), vget_low_s16(a1_hi)),
                                                 vmull_s16(vget_high_s16(r1_1_hi), vget_high_s16(a1_hi))), 4);
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
      alignas(16) uint16_t w0[8], w1[8];
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
      int32x4_t s0_lo = vshrq_n_s32(vpaddq_s32(vmull_s16(vget_low_s16(r0_lo), vget_low_s16(alpha_lo)),
                                               vmull_s16(vget_high_s16(r0_lo), vget_high_s16(alpha_lo))), 4);
      int32x4_t s0_hi = vshrq_n_s32(vpaddq_s32(vmull_s16(vget_low_s16(r0_hi), vget_low_s16(alpha_hi)),
                                               vmull_s16(vget_high_s16(r0_hi), vget_high_s16(alpha_hi))), 4);
      int32x4_t s1_lo = vshrq_n_s32(vpaddq_s32(vmull_s16(vget_low_s16(r1_lo), vget_low_s16(alpha_lo)),
                                               vmull_s16(vget_high_s16(r1_lo), vget_high_s16(alpha_lo))), 4);
      int32x4_t s1_hi = vshrq_n_s32(vpaddq_s32(vmull_s16(vget_low_s16(r1_hi), vget_low_s16(alpha_hi)),
                                               vmull_s16(vget_high_s16(r1_hi), vget_high_s16(alpha_hi))), 4);
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

void MatchTemplateNccNeon(const float* image, int img_w, int img_h, int img_stride,
                          const PreparedTemplate& tpl, float* out_response) {
  const int tw = tpl.width;
  const int th = tpl.height;
  const int out_w = img_w - tw + 1;
  const int out_h = img_h - th + 1;
  if (out_w <= 0 || out_h <= 0) return;
  const float tpl_norm = tpl.norm;
  const double inv_pixels = 1.0 / (tw * th);
  std::vector<double> col_sum(img_w, 0.0), col_sum2(img_w, 0.0);
  std::vector<double> pref_i(img_w + 1, 0.0), pref_i2(img_w + 1, 0.0);
  std::vector<float> inv_norm(out_w, 0.0f);

  for (int y = 0; y < out_h; ++y) {
    float* resp_row = out_response + y * out_w;
    if (y == 0) {
      for (int r = 0; r < th; ++r) {
        const float* img_row = image + r * img_stride;
        int c = 0;
        for (; c + 3 < img_w; c += 4) {
          float32x4_t v = vld1q_f32(img_row + c);
          float64x2_t d_lo = vcvt_f64_f32(vget_low_f32(v));
          float64x2_t d_hi = vcvt_high_f64_f32(v);
          vst1q_f64(col_sum.data() + c, vaddq_f64(vld1q_f64(col_sum.data() + c), d_lo));
          vst1q_f64(col_sum.data() + c + 2, vaddq_f64(vld1q_f64(col_sum.data() + c + 2), d_hi));
          vst1q_f64(col_sum2.data() + c, vfmaq_f64(vld1q_f64(col_sum2.data() + c), d_lo, d_lo));
          vst1q_f64(col_sum2.data() + c + 2, vfmaq_f64(vld1q_f64(col_sum2.data() + c + 2), d_hi, d_hi));
        }
        for (; c < img_w; ++c) {
          double val = img_row[c];
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
        vst1q_f64(col_sum.data() + c, vaddq_f64(vld1q_f64(col_sum.data() + c), vsubq_f64(add_lo, sub_lo)));
        vst1q_f64(col_sum.data() + c + 2, vaddq_f64(vld1q_f64(col_sum.data() + c + 2), vsubq_f64(add_hi, sub_hi)));
        float64x2_t diff2_lo = vsubq_f64(vmulq_f64(add_lo, add_lo), vmulq_f64(sub_lo, sub_lo));
        float64x2_t diff2_hi = vsubq_f64(vmulq_f64(add_hi, add_hi), vmulq_f64(sub_hi, sub_hi));
        vst1q_f64(col_sum2.data() + c, vaddq_f64(vld1q_f64(col_sum2.data() + c), diff2_lo));
        vst1q_f64(col_sum2.data() + c + 2, vaddq_f64(vld1q_f64(col_sum2.data() + c + 2), diff2_hi));
      }
      for (; c < img_w; ++c) {
        double vs = row_sub[c], va = row_add[c];
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
      float64x2_t s_i_lo = vsubq_f64(vld1q_f64(pref_i.data() + nx + tw), vld1q_f64(pref_i.data() + nx));
      float64x2_t s_i_hi = vsubq_f64(vld1q_f64(pref_i.data() + nx + tw + 2), vld1q_f64(pref_i.data() + nx + 2));
      float64x2_t s_i2_lo = vsubq_f64(vld1q_f64(pref_i2.data() + nx + tw), vld1q_f64(pref_i2.data() + nx));
      float64x2_t s_i2_hi = vsubq_f64(vld1q_f64(pref_i2.data() + nx + tw + 2), vld1q_f64(pref_i2.data() + nx + 2));
      float64x2_t var_lo = vfmsq_f64(s_i2_lo, vmulq_f64(s_i_lo, s_i_lo), vinv_pix);
      float64x2_t var_hi = vfmsq_f64(s_i2_hi, vmulq_f64(s_i_hi, s_i_hi), vinv_pix);
      uint64x2_t mask_lo = vcgtq_f64(var_lo, veps);
      uint64x2_t mask_hi = vcgtq_f64(var_hi, veps);
      float64x2_t inv_lo = vbslq_f64(mask_lo, vdivq_f64(vone, vmulq_f64(vtpl_norm, vsqrtq_f64(var_lo))), vreinterpretq_f64_u64(vzero_u64));
      float64x2_t inv_hi = vbslq_f64(mask_hi, vdivq_f64(vone, vmulq_f64(vtpl_norm, vsqrtq_f64(var_hi))), vreinterpretq_f64_u64(vzero_u64));
      vst1q_f32(inv_norm.data() + nx, vcombine_f32(vcvt_f32_f64(inv_lo), vcvt_f32_f64(inv_hi)));
    }
    for (; nx < out_w; ++nx) {
      double sum_i = pref_i[nx + tw] - pref_i[nx];
      double sum_i2 = pref_i2[nx + tw] - pref_i2[nx];
      double var_i = std::fma(-(sum_i * sum_i), inv_pixels, sum_i2);
      inv_norm[nx] = (var_i <= 1e-5) ? 0.0f : static_cast<float>(1.0 / (tpl_norm * std::sqrt(var_i)));
    }

    int x = 0;
    const float32x4_t vmin = vdupq_n_f32(-1.0f);
    const float32x4_t vmax = vdupq_n_f32(1.0f);
    for (; x + 15 < out_w; x += 16) {
      float32x4_t acc0 = vdupq_n_f32(0.0f), acc1 = vdupq_n_f32(0.0f), acc2 = vdupq_n_f32(0.0f), acc3 = vdupq_n_f32(0.0f);
      float32x4_t acc0_b = vdupq_n_f32(0.0f), acc1_b = vdupq_n_f32(0.0f), acc2_b = vdupq_n_f32(0.0f), acc3_b = vdupq_n_f32(0.0f);
      const float* t_ptr = tpl.zero_mean_fmap.data();
      for (int r = 0; r < th; ++r) {
        const float* img_row = image + (y + r) * img_stride + x;
        int c = 0;
        for (; c + 1 < tw; c += 2) {
          float32x4_t t0 = vdupq_n_f32(t_ptr[c]), t1 = vdupq_n_f32(t_ptr[c + 1]);
          acc0 = vfmaq_f32(acc0, t0, vld1q_f32(img_row + c));
          acc1 = vfmaq_f32(acc1, t0, vld1q_f32(img_row + c + 4));
          acc2 = vfmaq_f32(acc2, t0, vld1q_f32(img_row + c + 8));
          acc3 = vfmaq_f32(acc3, t0, vld1q_f32(img_row + c + 12));
          acc0_b = vfmaq_f32(acc0_b, t1, vld1q_f32(img_row + c + 1));
          acc1_b = vfmaq_f32(acc1_b, t1, vld1q_f32(img_row + c + 5));
          acc2_b = vfmaq_f32(acc2_b, t1, vld1q_f32(img_row + c + 9));
          acc3_b = vfmaq_f32(acc3_b, t1, vld1q_f32(img_row + c + 13));
        }
        for (; c < tw; ++c) {
          float32x4_t t0 = vdupq_n_f32(t_ptr[c]);
          acc0 = vfmaq_f32(acc0, t0, vld1q_f32(img_row + c));
          acc1 = vfmaq_f32(acc1, t0, vld1q_f32(img_row + c + 4));
          acc2 = vfmaq_f32(acc2, t0, vld1q_f32(img_row + c + 8));
          acc3 = vfmaq_f32(acc3, t0, vld1q_f32(img_row + c + 12));
        }
        t_ptr += tw;
      }
      acc0 = vaddq_f32(acc0, acc0_b); acc1 = vaddq_f32(acc1, acc1_b);
      acc2 = vaddq_f32(acc2, acc2_b); acc3 = vaddq_f32(acc3, acc3_b);
      vst1q_f32(resp_row + x, vminq_f32(vmaxq_f32(vmulq_f32(acc0, vld1q_f32(inv_norm.data() + x)), vmin), vmax));
      vst1q_f32(resp_row + x + 4, vminq_f32(vmaxq_f32(vmulq_f32(acc1, vld1q_f32(inv_norm.data() + x + 4)), vmin), vmax));
      vst1q_f32(resp_row + x + 8, vminq_f32(vmaxq_f32(vmulq_f32(acc2, vld1q_f32(inv_norm.data() + x + 8)), vmin), vmax));
      vst1q_f32(resp_row + x + 12, vminq_f32(vmaxq_f32(vmulq_f32(acc3, vld1q_f32(inv_norm.data() + x + 12)), vmin), vmax));
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
      resp_row[x] = std::max(-1.0f, std::min(1.0f, (acc + acc_b) * inv_norm[x]));
    }
  }
}

}  // namespace neon_verify

TEST(ExpEngineTest, NeonKernelsMatchScalarAndAvx2BitExact) {
  // 1. Verify ExtractGraySubRect NEON (3-channel BGR and 4-channel BGRA)
  constexpr int kW = 37;
  constexpr int kH = 7;
  std::vector<uint8_t> bgr(kW * kH * 3);
  std::vector<uint8_t> bgra(kW * kH * 4);
  for (size_t i = 0; i < bgr.size(); ++i) bgr[i] = static_cast<uint8_t>((i * 41 + 17) % 256);
  for (size_t i = 0; i < bgra.size(); ++i) bgra[i] = static_cast<uint8_t>((i * 59 + 31) % 256);

  std::vector<uint8_t> gray_ref(kW * kH, 0), gray_neon(kW * kH, 0);
  Test_ExtractGraySubRect(bgr.data(), kW, kH, kW * 3, 3, 0, 0, kW, kH, gray_ref.data());
  neon_verify::ExtractGraySubRectNeon(bgr.data(), kW, kH, kW * 3, 3, 0, 0, kW, kH, gray_neon.data());
  EXPECT_EQ(gray_ref, gray_neon);

  Test_ExtractGraySubRect(bgra.data(), kW, kH, kW * 4, 4, 0, 0, kW, kH, gray_ref.data());
  neon_verify::ExtractGraySubRectNeon(bgra.data(), kW, kH, kW * 4, 4, 0, 0, kW, kH, gray_neon.data());
  EXPECT_EQ(gray_ref, gray_neon);

  // 2. Verify ResizeGray NEON vs AVX2 and Scalar across all 9 geometries
  struct SizeCase { int sw, sh, dw, dh; };
  const SizeCase kCases[] = {
      {10, 10, 25, 25},   {15, 15, 19, 19},   {30, 20, 25, 17},
      {33, 33, 49, 49},   {100, 38, 77, 25},  {230, 25, 180, 21},
      {350, 38, 230, 25}, {416, 16, 988, 38}, {1247, 38, 1247, 38},
  };
  for (const auto& sc : kCases) {
    std::vector<uint8_t> src(sc.sw * sc.sh);
    for (size_t i = 0; i < src.size(); ++i) src[i] = static_cast<uint8_t>((i * 73 + 19) % 256);
    std::vector<uint8_t> dst_avx2(sc.dw * sc.dh, 0);
    std::vector<uint8_t> dst_neon(sc.dw * sc.dh, 0);
    std::vector<uint8_t> dst_scalar(sc.dw * sc.dh, 0);
    ExpEngine::ResizeGray(src.data(), sc.sw, sc.sh, sc.sw, dst_avx2.data(), sc.dw, sc.dh, sc.dw);
    neon_verify::ResizeGrayNeon(src.data(), sc.sw, sc.sh, sc.sw, dst_neon.data(), sc.dw, sc.dh, sc.dw);
    ExpEngine::ResizeGrayScalar(src.data(), sc.sw, sc.sh, sc.sw, dst_scalar.data(), sc.dw, sc.dh, sc.dw);
    EXPECT_EQ(dst_avx2, dst_neon) << "NEON vs AVX2 mismatch at size " << sc.sw << "x" << sc.sh
                                  << " -> " << sc.dw << "x" << sc.dh;
    EXPECT_EQ(dst_avx2, dst_scalar) << "Scalar vs AVX2 mismatch at size " << sc.sw << "x" << sc.sh
                                    << " -> " << sc.dw << "x" << sc.dh;
  }

  // 3. Verify MatchTemplateNcc NEON vs AVX2 vs Scalar bit-exact across all 15 character templates
  ExpEngine engine;
  constexpr int kImgW = 230;
  constexpr int kImgH = 25;
  std::vector<float> synth_img(kImgW * kImgH);
  for (size_t i = 0; i < synth_img.size(); ++i) {
    synth_img[i] = 20.0f + static_cast<float>((i * 97 + 13) % 200);
  }
  for (const auto& kv : engine.templates()) {
    const PreparedTemplate& tpl = kv.second;
    int out_w = kImgW - tpl.width + 1;
    int out_h = kImgH - tpl.height + 1;
    std::vector<float> resp_avx2(out_w * out_h, 0.0f);
    std::vector<float> resp_neon(out_w * out_h, 0.0f);
    std::vector<float> resp_scalar(out_w * out_h, 0.0f);
    ExpEngine::MatchTemplateNcc(synth_img.data(), kImgW, kImgH, kImgW, tpl, resp_avx2.data());
    neon_verify::MatchTemplateNccNeon(synth_img.data(), kImgW, kImgH, kImgW, tpl, resp_neon.data());
    ExpEngine::MatchTemplateNccScalar(synth_img.data(), kImgW, kImgH, kImgW, tpl, resp_scalar.data());
    EXPECT_EQ(resp_avx2, resp_neon)
        << "NEON vs AVX2 NCC bit-exact mismatch for char '" << kv.first << "'";
    EXPECT_EQ(resp_avx2, resp_scalar)
        << "Scalar vs AVX2 NCC bit-exact mismatch for char '" << kv.first << "'";
  }
}
#endif

}  // namespace
}  // namespace exp
}  // namespace artale
