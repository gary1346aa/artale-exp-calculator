// Copyright 2026 Artale Exp Project. All rights reserved.
// Google C++ Style Guide compliant.

#include "src/cpp/src/cpu_features.h"

#if defined(__x86_64__) || defined(_M_X64)
#if defined(_MSC_VER)
#include <intrin.h>
#elif defined(__GNUC__) || defined(__clang__)
#include <cpuid.h>
#include <immintrin.h>
#endif
#endif

namespace artale {
namespace exp {

namespace {

bool DetectAvx2Support() {
#if defined(__x86_64__) || defined(_M_X64)
#if defined(_MSC_VER)
  int info[4] = {0};
  __cpuid(info, 0);
  if (info[0] < 7) {
    return false;
  }

  __cpuidex(info, 1, 0);
  bool osxsave = (info[2] & (1 << 27)) != 0;
  bool avx = (info[2] & (1 << 28)) != 0;
  bool fma = (info[2] & (1 << 12)) != 0;
  if (!osxsave || !avx || !fma) {
    return false;
  }

  unsigned long long xcr0 = _xgetbv(0);
  if ((xcr0 & 0x6) != 0x6) {
    return false;
  }

  __cpuidex(info, 7, 0);
  bool avx2 = (info[1] & (1 << 5)) != 0;
  return avx2;
#elif defined(__GNUC__) || defined(__clang__)
  return __builtin_cpu_supports("avx2") && __builtin_cpu_supports("fma");
#else
  return false;
#endif
#else
  return false;
#endif
}

bool DetectSse41Support() {
#if defined(__x86_64__) || defined(_M_X64)
#if defined(_MSC_VER)
  int info[4] = {0};
  __cpuid(info, 1);
  return (info[2] & (1 << 19)) != 0;
#elif defined(__GNUC__) || defined(__clang__)
  return __builtin_cpu_supports("sse4.1");
#else
  return false;
#endif
#else
  return false;
#endif
}

}  // namespace

bool CpuSupportsAvx2() {
  static const bool kHasAvx2 = DetectAvx2Support();
  return kHasAvx2;
}

bool CpuSupportsSse41() {
  static const bool kHasSse41 = DetectSse41Support();
  return kHasSse41;
}

}  // namespace exp
}  // namespace artale
