// Copyright 2026 Artale Exp Project. All rights reserved.
// Google C++ Style Guide compliant.

#ifndef ARTALE_EXP_CORE_CPU_FEATURES_H_
#define ARTALE_EXP_CORE_CPU_FEATURES_H_

namespace artale {
namespace exp {

// Returns true if the host CPU supports AVX2 and FMA instructions and the OS
// has enabled AVX state saving. Evaluated and cached on first call.
bool CpuSupportsAvx2();

// Returns true if the host CPU supports SSE4.1 instructions. Evaluated and
// cached on first call.
bool CpuSupportsSse41();

}  // namespace exp
}  // namespace artale

#endif  // ARTALE_EXP_CORE_CPU_FEATURES_H_
