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

}  // namespace
}  // namespace exp
}  // namespace artale
