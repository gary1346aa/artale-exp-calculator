// Copyright 2026 Artale Exp Project. All rights reserved.
// Google C++ Style Guide compliant.

#ifndef ARTALE_EXP_CORE_EXP_ENGINE_AVX2_H_
#define ARTALE_EXP_CORE_EXP_ENGINE_AVX2_H_

#include <cstdint>
#include "src/cpp/src/exp_engine.h"

namespace artale {
namespace exp {

#if defined(__x86_64__) || defined(_M_X64)

// AVX2-accelerated bilinear interpolation.
void ResizeGrayAVX2(const uint8_t* src, int src_w, int src_h, int src_stride,
                    uint8_t* dst, int dst_w, int dst_h, int dst_stride);

// AVX2/FMA-accelerated sliding-window normalized cross-correlation.
void MatchTemplateNccAVX2(const float* image, int img_w, int img_h, int img_stride,
                          const PreparedTemplate& tpl, float* out_response);

#endif

}  // namespace exp
}  // namespace artale

#endif  // ARTALE_EXP_CORE_EXP_ENGINE_AVX2_H_
