#include "artale_exp_core.h"
#include "digit_prototypes.h"

#include <cstring>
#include <cmath>
#include <vector>
#include <chrono>
#include <algorithm>
#include <cstdio>
#include <cstdlib>

#if defined(__x86_64__) || defined(_M_X64)
  #define ARTALE_ARCH_X64 1
  #include <immintrin.h>
#elif defined(__aarch64__) || defined(_M_ARM64)
  #define ARTALE_ARCH_ARM64 1
  #include <arm_neon.h>
#endif

namespace artale {

// High-performance SIMD Dot Product over canonical 384-element float buffers
static inline float DotProduct384(const float* a, const float* b) {
#if defined(__AVX2__)
    __m256 sum0 = _mm256_setzero_ps();
    __m256 sum1 = _mm256_setzero_ps();
    for (int i = 0; i < CANON_SIZE; i += 16) {
        __m256 va0 = _mm256_load_ps(a + i);
        __m256 vb0 = _mm256_load_ps(b + i);
        sum0 = _mm256_fmadd_ps(va0, vb0, sum0);

        __m256 va1 = _mm256_load_ps(a + i + 8);
        __m256 vb1 = _mm256_load_ps(b + i + 8);
        sum1 = _mm256_fmadd_ps(va1, vb1, sum1);
    }
    __m256 sum256 = _mm256_add_ps(sum0, sum1);
    __m128 lo = _mm256_castps256_ps128(sum256);
    __m128 hi = _mm256_extractf128_ps(sum256, 1);
    __m128 v4 = _mm_add_ps(lo, hi);
    v4 = _mm_hadd_ps(v4, v4);
    v4 = _mm_hadd_ps(v4, v4);
    return _mm_cvtss_f32(v4);
#elif defined(__ARM_NEON)
    float32x4_t sum0 = vdupq_n_f32(0.0f);
    float32x4_t sum1 = vdupq_n_f32(0.0f);
    for (int i = 0; i < CANON_SIZE; i += 8) {
        float32x4_t va0 = vld1q_f32(a + i);
        float32x4_t vb0 = vld1q_f32(b + i);
        sum0 = vfmaq_f32(sum0, va0, vb0);

        float32x4_t va1 = vld1q_f32(a + i + 4);
        float32x4_t vb1 = vld1q_f32(b + i + 4);
        sum1 = vfmaq_f32(sum1, va1, vb1);
    }
    float32x4_t sum = vaddq_f32(sum0, sum1);
    return vaddvq_f32(sum);
#else
    float sum = 0.0f;
    for (int i = 0; i < CANON_SIZE; ++i) {
        sum += a[i] * b[i];
    }
    return sum;
#endif
}

// Bilinear image resize (uint8 to float) matching OpenCV INTER_LINEAR
static void ResizeBilinear(
    const uint8_t* src, int sw, int sh, int s_stride,
    float* dst, int dw, int dh)
{
    float scale_x = (dw > 0) ? (float)sw / (float)dw : 0.0f;
    float scale_y = (dh > 0) ? (float)sh / (float)dh : 0.0f;

    for (int y = 0; y < dh; ++y) {
        float fy = (y + 0.5f) * scale_y - 0.5f;
        int y1 = (int)std::floor(fy);
        int y2 = y1 + 1;
        float y_diff = fy - (float)y1;

        int sy1 = std::max(0, std::min(sh - 1, y1));
        int sy2 = std::max(0, std::min(sh - 1, y2));

        for (int x = 0; x < dw; ++x) {
            float fx = (x + 0.5f) * scale_x - 0.5f;
            int x1 = (int)std::floor(fx);
            int x2 = x1 + 1;
            float x_diff = fx - (float)x1;

            int sx1 = std::max(0, std::min(sw - 1, x1));
            int sx2 = std::max(0, std::min(sw - 1, x2));

            float p1 = (float)src[sy1 * s_stride + sx1];
            float p2 = (float)src[sy1 * s_stride + sx2];
            float p3 = (float)src[sy2 * s_stride + sx1];
            float p4 = (float)src[sy2 * s_stride + sx2];

            float val = p1 * (1.0f - x_diff) * (1.0f - y_diff) +
                        p2 * (x_diff) * (1.0f - y_diff) +
                        p3 * (1.0f - x_diff) * (y_diff) +
                        p4 * (x_diff) * (y_diff);

            dst[y * dw + x] = val;
        }
    }
}

// Bilinear resize uint8 to uint8 matching OpenCV INTER_LINEAR
static void ResizeBilinearU8(
    const uint8_t* src, int sw, int sh, int s_stride,
    uint8_t* dst, int dw, int dh, int d_stride)
{
    float scale_x = (dw > 0) ? (float)sw / (float)dw : 0.0f;
    float scale_y = (dh > 0) ? (float)sh / (float)dh : 0.0f;

    for (int y = 0; y < dh; ++y) {
        float fy = (y + 0.5f) * scale_y - 0.5f;
        int y1 = (int)std::floor(fy);
        int y2 = y1 + 1;
        float y_diff = fy - (float)y1;

        int sy1 = std::max(0, std::min(sh - 1, y1));
        int sy2 = std::max(0, std::min(sh - 1, y2));

        for (int x = 0; x < dw; ++x) {
            float fx = (x + 0.5f) * scale_x - 0.5f;
            int x1 = (int)std::floor(fx);
            int x2 = x1 + 1;
            float x_diff = fx - (float)x1;

            int sx1 = std::max(0, std::min(sw - 1, x1));
            int sx2 = std::max(0, std::min(sw - 1, x2));

            float p1 = (float)src[sy1 * s_stride + sx1];
            float p2 = (float)src[sy1 * s_stride + sx2];
            float p3 = (float)src[sy2 * s_stride + sx1];
            float p4 = (float)src[sy2 * s_stride + sx2];

            float val = p1 * (1.0f - x_diff) * (1.0f - y_diff) +
                        p2 * (x_diff) * (1.0f - y_diff) +
                        p3 * (1.0f - x_diff) * (y_diff) +
                        p4 * (x_diff) * (y_diff);

            dst[y * d_stride + x] = (uint8_t)(val + 0.5f);
        }
    }
}

// Normalized Cross Correlation for a canonical 16x24 glyph against candidate prototypes
static void MatchCanonicalGlyph(
    const float* canonical_zm, float norm,
    const char* candidates,
    char* best_char, float* best_score,
    const uint8_t* raw_glyph = nullptr, int gw = 0, int gh = 0)
{
    *best_char = '?';
    *best_score = -1.0f;

    if (norm < 1e-6f) return;

    float score_8 = -1.0f;

    for (int i = 0; i < NUM_CANON_PROTOS; ++i) {
        const CanonicalGlyph& p = CANON_PROTOTYPES[i];
        if (strchr(candidates, p.id) == nullptr) continue;
        if (p.norm < 1e-6f) continue;

        float dot = DotProduct384(canonical_zm, p.values);
        float ncc = dot / (norm * p.norm);

        if (p.id == '8') {
            score_8 = ncc;
        }

        if (ncc > *best_score) {
            *best_score = ncc;
            *best_char = p.id;
        }
    }

    // Comprehensive Topological Disambiguation for 8, 3, 0, 6, 9
    if (raw_glyph != nullptr && gw >= 5 && gh >= 6 && strchr(candidates, '8') != nullptr) {
        // Upper loop left fill (y: 20% to 40%, x: left 35%)
        int y_u1 = (int)(gh * 0.20f), y_u2 = (int)(gh * 0.40f) + 1;
        int y_l1 = (int)(gh * 0.60f), y_l2 = (int)(gh * 0.80f) + 1;
        int x_left = std::max(1, (int)(gw * 0.35f));

        int up_count = 0, up_total = 0;
        for (int y = y_u1; y < y_u2 && y < gh; ++y) {
            for (int x = 0; x < x_left && x < gw; ++x) {
                if (raw_glyph[y * gw + x]) up_count++;
                up_total++;
            }
        }
        float up_left_fill = (up_total > 0) ? (float)up_count / (float)up_total : 0.0f;

        int lo_count = 0, lo_total = 0;
        for (int y = y_l1; y < y_l2 && y < gh; ++y) {
            for (int x = 0; x < x_left && x < gw; ++x) {
                if (raw_glyph[y * gw + x]) lo_count++;
                lo_total++;
            }
        }
        float lo_left_fill = (lo_total > 0) ? (float)lo_count / (float)lo_total : 0.0f;

        // Middle row crossbar
        int mid_y = gh / 2;
        int mid_count = 0;
        for (int x = 0; x < gw; ++x) {
            if (raw_glyph[mid_y * gw + x]) mid_count++;
        }
        float mid_row_fill = (float)mid_count / (float)gw;
        uint8_t center_px = raw_glyph[mid_y * gw + (gw / 2)];

        // Rule A: If classified as '3', but has solid left strokes in both upper and lower halves -> IT IS AN '8'
        if (*best_char == '3' && up_left_fill > 0.35f && lo_left_fill > 0.25f && score_8 > 0.35f) {
            *best_char = '8';
            *best_score = std::max(*best_score, score_8);
        }
        // Rule B1: If classified as '0' or '6', but has a solid middle crossbar and left strokes -> IT IS AN '8'
        else if ((*best_char == '0' || *best_char == '6') && center_px == 1 && mid_row_fill > 0.48f && up_left_fill > 0.30f && lo_left_fill > 0.25f && score_8 > 0.35f) {
            *best_char = '8';
            *best_score = std::max(*best_score, score_8);
        }
        // Rule B2: If classified as '9', but has a solid lower-left stroke (which 9 never has) -> IT IS AN '8'
        else if (*best_char == '9' && lo_left_fill > 0.30f && score_8 > 0.35f) {
            *best_char = '8';
            *best_score = std::max(*best_score, score_8);
        }
        // Rule C: If classified as '8', but lower-left is completely open (lo_left_fill < 0.15) -> IT IS A '3' or '9'
        else if (*best_char == '8' && lo_left_fill < 0.15f) {
            if (up_left_fill < 0.15f) {
                *best_char = '3';
            } else {
                *best_char = '9';
            }
        }
        // Rule D: If classified as '8', but center is hollow -> IT IS A '0'
        else if (*best_char == '8' && center_px == 0 && mid_row_fill < 0.40f) {
            *best_char = '0';
        }
    }
}

struct Span {
    int start;
    int end;
};

struct Glyph {
    int w;
    int h;
    std::vector<uint8_t> data;
};

} // namespace artale

extern "C" {

ARTALE_API int ParseExpFromBuffer(
    const uint8_t* bgr_data,
    int width,
    int height,
    int stride,
    int bytes_per_px,
    ExpResult* out_result)
{
    if (!bgr_data || width <= 0 || height <= 0 || !out_result) {
        return -1;
    }

    auto t0 = std::chrono::high_resolution_clock::now();

    out_result->exp_value = 0;
    out_result->exp_percent = -1.0;
    out_result->success = 0;
    out_result->exp_string[0] = '\0';
    out_result->crop_x = 0;
    out_result->crop_y = 0;
    out_result->crop_w = 0;
    out_result->crop_h = 0;
    out_result->logo_x = 0;
    out_result->logo_y = 0;
    out_result->logo_w = 0;
    out_result->logo_h = 0;

    // 1. Crop bottom 15% strip
    int strip_h = std::max(80, (int)(height * 0.15f));
    if (strip_h > height) strip_h = height;
    int strip_y_start = height - strip_h;

    // Convert full bottom strip to grayscale
    std::vector<uint8_t> gray(width * strip_h);
    for (int y = 0; y < strip_h; ++y) {
        const uint8_t* row = bgr_data + (strip_y_start + y) * stride;
        uint8_t* g_row = gray.data() + y * width;
        for (int x = 0; x < width; ++x) {
            int b = row[x * bytes_per_px + 0];
            int g = row[x * bytes_per_px + 1];
            int r = row[x * bytes_per_px + 2];
            g_row[x] = (uint8_t)((b * 29 + g * 150 + r * 77) >> 8);
        }
    }

    // 2. Normalized height multi-scale template search
    constexpr int NORM_H = 80;
    float ds = (float)strip_h / (float)NORM_H;
    int sw = (int)((float)width / ds);
    int sh = NORM_H;

    std::vector<uint8_t> gray_small(sw * sh);
    artale::ResizeBilinearU8(
        gray.data(), width, strip_h, width,
        gray_small.data(), sw, sh, sw
    );

    // Integral Images for O(1) patch sums and variance
    std::vector<double> sat((sw + 1) * (sh + 1), 0.0);
    std::vector<double> sat2((sw + 1) * (sh + 1), 0.0);

    for (int y = 0; y < sh; ++y) {
        double row_sum = 0.0;
        double row_sqsum = 0.0;
        for (int x = 0; x < sw; ++x) {
            double v = (double)gray_small[y * sw + x];
            row_sum += v;
            row_sqsum += v * v;
            sat[(y + 1) * (sw + 1) + (x + 1)] = sat[y * (sw + 1) + (x + 1)] + row_sum;
            sat2[(y + 1) * (sw + 1) + (x + 1)] = sat2[y * (sw + 1) + (x + 1)] + row_sqsum;
        }
    }

    constexpr int NUM_SCALES = 9;
    float s_min = 6.0f / (float)artale::TPL_EXP_HEIGHT;
    float s_max = 12.0f / (float)artale::TPL_EXP_HEIGHT;
    float s_step = (s_max - s_min) / (float)(NUM_SCALES - 1);

    float best_val = -1.0f;
    int best_lx = 0, best_ly = 0;
    int best_tw = 0, best_th = 0;

    std::vector<uint8_t> scaled_tpl;
    std::vector<float> tpl_zm;

    for (int s_idx = 0; s_idx < NUM_SCALES; ++s_idx) {
        float s = s_min + s_idx * s_step;
        int th = (int)(artale::TPL_EXP_HEIGHT * s + 0.5f);
        int tw = (int)(artale::TPL_EXP_WIDTH * s + 0.5f);
        if (th >= sh || tw >= sw || th < 4 || tw < 8) continue;

        scaled_tpl.resize(tw * th);
        artale::ResizeBilinearU8(
            artale::TPL_EXP_DATA, artale::TPL_EXP_WIDTH, artale::TPL_EXP_HEIGHT, artale::TPL_EXP_WIDTH,
            scaled_tpl.data(), tw, th, tw
        );

        float t_sum = 0.0f;
        for (int i = 0; i < tw * th; ++i) t_sum += scaled_tpl[i];
        float t_mean = t_sum / (float)(tw * th);

        tpl_zm.resize(tw * th);
        float t_norm_sq = 0.0f;
        for (int i = 0; i < tw * th; ++i) {
            float v = (float)scaled_tpl[i] - t_mean;
            tpl_zm[i] = v;
            t_norm_sq += v * v;
        }
        float t_norm = std::sqrt(t_norm_sq);
        if (t_norm < 1e-4f) continue;

        double inv_area = 1.0 / (double)(tw * th);
        int max_y = sh - th;
        int max_x = sw - tw;

        for (int y = 0; y <= max_y; ++y) {
            int y2 = y + th;
            for (int x = 0; x <= max_x; ++x) {
                int x2 = x + tw;

                double p_sum = sat[y2 * (sw + 1) + x2] - sat[y * (sw + 1) + x2] - sat[y2 * (sw + 1) + x] + sat[y * (sw + 1) + x];
                double p_sqsum = sat2[y2 * (sw + 1) + x2] - sat2[y * (sw + 1) + x2] - sat2[y2 * (sw + 1) + x] + sat2[y * (sw + 1) + x];
                double variance = p_sqsum - (p_sum * p_sum * inv_area);
                if (variance <= 1.0) continue;

                float p_norm = (float)std::sqrt(variance);

                float dot = 0.0f;
                for (int ty = 0; ty < th; ++ty) {
                    const uint8_t* p_row = gray_small.data() + (y + ty) * sw + x;
                    const float* t_row = tpl_zm.data() + ty * tw;
                    for (int tx = 0; tx < tw; ++tx) {
                        dot += (float)p_row[tx] * t_row[tx];
                    }
                }

                float ncc = dot / (t_norm * p_norm);
                if (ncc > best_val) {
                    best_val = ncc;
                    best_lx = (int)((float)x * ds);
                    best_ly = (int)((float)y * ds);
                    best_tw = (int)((float)tw * ds);
                    best_th = (int)((float)th * ds);
                }
            }
        }
    }

    if (best_val < 0.65f) {
        auto t1 = std::chrono::high_resolution_clock::now();
        out_result->parse_time_ms = std::chrono::duration<float, std::milli>(t1 - t0).count();
        return 0;
    }

    // 3. Extract text region relative to logo coordinates
    // Adaptive threshold: 140 for high/mid res, 132 for low-res
    uint8_t thresh_val = (best_th >= 16) ? 140 : 132;

    int y_start = std::max(0, best_ly - (int)(best_th * 0.45f));
    int y_end = std::min(strip_h, y_start + best_th + 1);
    int x_start = best_lx + best_tw + (int)(best_th * 0.35f);
    int x_end = std::min(width, x_start + (int)(best_th * 13.0f));

    int tc_w = x_end - x_start;
    int tc_h = y_end - y_start;
    if (tc_w <= 0 || tc_h <= 0) return 0;

    out_result->crop_x = x_start;
    out_result->crop_y = strip_y_start + y_start;
    out_result->crop_w = tc_w;
    out_result->crop_h = tc_h;
    out_result->logo_x = best_lx;
    out_result->logo_y = strip_y_start + best_ly;
    out_result->logo_w = best_tw;
    out_result->logo_h = best_th;

    std::vector<uint8_t> mask(tc_w * tc_h);
    for (int y = 0; y < tc_h; ++y) {
        const uint8_t* g_row = gray.data() + (y_start + y) * width + x_start;
        uint8_t* m_row = mask.data() + y * tc_w;
        for (int x = 0; x < tc_w; ++x) {
            m_row[x] = (g_row[x] > thresh_val) ? 1 : 0;
        }
    }

    // 4. Horizontal column-sum projection
    std::vector<int> col_sums(tc_w, 0);
    std::vector<artale::Span> raw_spans;
    bool in_span = false;
    int span_start = 0;

    for (int x = 0; x < tc_w; ++x) {
        int csum = 0;
        for (int y = 0; y < tc_h; ++y) {
            csum += mask[y * tc_w + x];
        }
        col_sums[x] = csum;
        if (csum > 0 && !in_span) {
            in_span = true;
            span_start = x;
        } else if (csum == 0 && in_span) {
            in_span = false;
            raw_spans.push_back({span_start, x});
        }
    }
    if (in_span) {
        raw_spans.push_back({span_start, tc_w});
    }

    // Discard any trailing spans after a large gap (> 1.2 * best_th)
    std::vector<artale::Span> trimmed_raw_spans;
    int max_inter_glyph_gap = std::max(12, (int)(best_th * 1.2f));
    for (size_t i = 0; i < raw_spans.size(); ++i) {
        if (i > 0 && (raw_spans[i].start - raw_spans[i - 1].end) > max_inter_glyph_gap) {
            break;
        }
        trimmed_raw_spans.push_back(raw_spans[i]);
    }

    // Width-aware valley splitting for merged digits (e.g. anti-aliased bridging between '8' and '4', or '[' and '0')
    float exp_w = (float)best_th * 0.60f;
    std::vector<artale::Span> spans;
    bool found_bracket = false;

    for (const auto& sp : trimmed_raw_spans) {
        int span_w = sp.end - sp.start;

        // Quick check if this span is '['
        int y_min = tc_h, y_max = -1;
        for (int y = 0; y < tc_h; ++y) {
            for (int x = sp.start; x < sp.end; ++x) {
                if (mask[y * tc_w + x]) {
                    if (y < y_min) y_min = y;
                    if (y > y_max) y_max = y;
                }
            }
        }
        int gh = (y_max >= y_min) ? (y_max - y_min + 1) : 0;
        if (gh >= (int)(best_th * 0.85f) && span_w <= (int)(exp_w * 0.65f)) {
            found_bracket = true;
        }

        // If span contains 2 merged elements (e.g. 2 digits or '[' + digit)
        if (span_w >= (int)(exp_w * 1.35f) && span_w <= (int)(exp_w * 2.8f)) {
            int m_st = std::max(1, (int)(span_w * 0.20f));
            int m_en = std::min(span_w - 1, (int)(span_w * 0.80f));
            int min_idx = m_st;
            int min_val = col_sums[sp.start + m_st];
            for (int i = m_st + 1; i <= m_en; ++i) {
                if (col_sums[sp.start + i] < min_val) {
                    min_val = col_sums[sp.start + i];
                    min_idx = i;
                }
            }
            if (min_val <= 3) {
                spans.push_back({sp.start, sp.start + min_idx});
                spans.push_back({sp.start + min_idx + 1, sp.end});
                continue;
            }
        }
        spans.push_back(sp);
    }

    // Trim glyphs to tight bounding boxes
    std::vector<artale::Glyph> glyphs;
    for (const auto& sp : spans) {
        int gw = sp.end - sp.start;
        int y_min = tc_h, y_max = -1;
        for (int y = 0; y < tc_h; ++y) {
            for (int x = sp.start; x < sp.end; ++x) {
                if (mask[y * tc_w + x]) {
                    if (y < y_min) y_min = y;
                    if (y > y_max) y_max = y;
                }
            }
        }
        if (y_max < y_min) continue;
        int gh = y_max - y_min + 1;
        if (gw <= 1 && gh <= 3) continue;

        artale::Glyph gl;
        gl.w = gw;
        gl.h = gh;
        gl.data.resize(gw * gh, 0);
        for (int y = 0; y < gh; ++y) {
            for (int x = 0; x < gw; ++x) {
                gl.data[y * gw + x] = mask[(y_min + y) * tc_w + (sp.start + x)];
            }
        }
        glyphs.push_back(std::move(gl));
    }

    if (!spans.empty()) {
        int first_x = spans.front().start;
        int last_x = spans.back().end;
        out_result->crop_x = x_start + first_x;
        out_result->crop_w = std::min(tc_w - first_x, last_x - first_x + (int)(best_th * 0.15f));
    }

    if (glyphs.empty()) {
        auto t1 = std::chrono::high_resolution_clock::now();
        out_result->parse_time_ms = std::chrono::duration<float, std::milli>(t1 - t0).count();
        return 0;
    }

    // Baseline metrics from leading digits
    std::vector<int> sample_h, sample_w;
    for (size_t i = 0; i < std::min((size_t)4, glyphs.size()); ++i) {
        if (glyphs[i].h > 4) {
            sample_h.push_back(glyphs[i].h);
            sample_w.push_back(glyphs[i].w);
        }
    }
    std::sort(sample_h.begin(), sample_h.end());
    std::sort(sample_w.begin(), sample_w.end());

    float base_h = (!sample_h.empty()) ? (float)sample_h[sample_h.size() / 2] : (best_th * 0.85f);
    float base_w = (!sample_w.empty()) ? (float)sample_w[sample_w.size() / 2] : (best_th * 0.60f);

    // 5. Morphological grammar parsing with SIMD canonical matching
    std::string exp_str;
    std::string pct_str;
    bool in_pct = false;

    alignas(32) float canon_buf[artale::CANON_SIZE];
    alignas(32) float canon_zm[artale::CANON_SIZE];

    for (const auto& gl : glyphs) {
        if (!in_pct) {
            // Ignore comma punctuation in EXP number
            if (gl.w <= (int)(base_w * 0.45f) && gl.h <= (int)(base_h * 0.45f)) {
                continue;
            }
        }
        artale::ResizeBilinear(
            gl.data.data(), gl.w, gl.h, gl.w,
            canon_buf, artale::CANON_W, artale::CANON_H
        );

        float g_sum = 0.0f;
        for (int i = 0; i < artale::CANON_SIZE; ++i) g_sum += canon_buf[i];
        float g_mean = g_sum / (float)artale::CANON_SIZE;

        float g_norm_sq = 0.0f;
        for (int i = 0; i < artale::CANON_SIZE; ++i) {
            float v = canon_buf[i] - g_mean;
            canon_zm[i] = v;
            g_norm_sq += v * v;
        }
        float g_norm = std::sqrt(g_norm_sq);

        if (!in_pct) {
            char ch_br = '?', ch_dig = '?';
            float s_br = 0.0f, s_dig = 0.0f;
            artale::MatchCanonicalGlyph(canon_zm, g_norm, "[", &ch_br, &s_br);
            artale::MatchCanonicalGlyph(canon_zm, g_norm, "0123456789", &ch_dig, &s_dig, gl.data.data(), gl.w, gl.h);

            bool is_bracket = false;
            if (!exp_str.empty()) {
                if (gl.h >= 1.08f * base_h && gl.w <= 0.80f * base_w) {
                    is_bracket = true;
                } else if (s_br > 0.35f && s_br > s_dig) {
                    is_bracket = true;
                }
            }

            if (is_bracket) {
                in_pct = true;
                continue;
            }
            exp_str.push_back(ch_dig);
        } else {
            // Decimal dot check
            int dot_max = std::max(4, (int)(base_h * 0.35f));
            if (gl.w <= dot_max && gl.h <= dot_max) {
                pct_str.push_back('.');
                continue;
            }

            char ch_pct = '?', ch_dig = '?';
            float s_pct = 0.0f, s_dig = 0.0f;
            artale::MatchCanonicalGlyph(canon_zm, g_norm, "%", &ch_pct, &s_pct);
            artale::MatchCanonicalGlyph(canon_zm, g_norm, "0123456789", &ch_dig, &s_dig, gl.data.data(), gl.w, gl.h);

            // Check for '%'
            if ((s_pct > 0.30f && s_pct > s_dig) || gl.w >= 1.30f * base_w) {
                pct_str.push_back('%');
                break;
            }

            // Check for closing bracket ']'
            if ((gl.h >= 1.08f * base_h && gl.w <= 0.80f * base_w) || pct_str.length() >= 8) {
                break;
            }

            pct_str.push_back(ch_dig);
        }
    }

    if (!exp_str.empty()) {
        out_result->exp_value = std::atoll(exp_str.c_str());

        std::string clean_pct = pct_str;
        clean_pct.erase(std::remove(clean_pct.begin(), clean_pct.end(), '%'), clean_pct.end());
        if (!clean_pct.empty()) {
            out_result->exp_percent = std::atof(clean_pct.c_str());
        } else {
            out_result->exp_percent = -1.0;
        }

        out_result->success = 1;
        snprintf(
            out_result->exp_string, sizeof(out_result->exp_string),
            "%s[%.2f%%]", exp_str.c_str(),
            (out_result->exp_percent >= 0.0 ? out_result->exp_percent : 0.0)
        );
    }

    auto t1 = std::chrono::high_resolution_clock::now();
    out_result->parse_time_ms = std::chrono::duration<float, std::milli>(t1 - t0).count();

    return 0;
}

} // extern "C"
