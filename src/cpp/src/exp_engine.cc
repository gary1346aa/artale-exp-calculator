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

#include "src/cpp/src/cpu_features.h"
#include "src/cpp/src/exp_engine_avx2.h"
#include "src/cpp/src/exp_engine_neon.h"
#include "src/cpp/src/exp_engine_scalar.h"
#include "src/cpp/src/exp_engine_sse41.h"

namespace artale {
namespace exp {

namespace {


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

// Bilinear interpolation for grayscale image matching OpenCV's cv2.INTER_LINEAR.
// Dispatches to AVX2, NEON, or scalar reference based on runtime CPU detection.
void ExpEngine::ResizeGray(const uint8_t* src, int src_w, int src_h, int src_stride, uint8_t* dst,
                           int dst_w, int dst_h, int dst_stride) {
  if (src_w <= 0 || src_h <= 0 || dst_w <= 0 || dst_h <= 0) return;

#if defined(__x86_64__) || defined(_M_X64)
  if (CpuSupportsAvx2()) {
    ResizeGrayAVX2(src, src_w, src_h, src_stride, dst, dst_w, dst_h, dst_stride);
    return;
  }
  if (CpuSupportsSse41()) {
    ResizeGraySSE41(src, src_w, src_h, src_stride, dst, dst_w, dst_h, dst_stride);
    return;
  }
#elif defined(__ARM_NEON) || defined(__aarch64__)
  ResizeGrayNEON(src, src_w, src_h, src_stride, dst, dst_w, dst_h, dst_stride);
  return;
#endif

  artale::exp::ResizeGrayScalar(src, src_w, src_h, src_stride, dst, dst_w, dst_h, dst_stride);
}

void ExpEngine::ResizeGrayScalar(const uint8_t* src, int src_w, int src_h, int src_stride,
                                 uint8_t* dst, int dst_w, int dst_h, int dst_stride) {
  artale::exp::ResizeGrayScalar(src, src_w, src_h, src_stride, dst, dst_w, dst_h, dst_stride);
}

// Computes sliding-window normalized cross correlation (TM_CCOEFF_NORMED).
// Dispatches to AVX2, NEON, SSE4.1, or scalar reference based on runtime CPU detection.
void ExpEngine::MatchTemplateNcc(const float* image, int img_w, int img_h, int img_stride,
                                 const PreparedTemplate& tpl, float* out_response) {
  const int tw = tpl.width;
  const int th = tpl.height;
  const int out_w = img_w - tw + 1;
  const int out_h = img_h - th + 1;
  if (out_w <= 0 || out_h <= 0) return;

#if defined(__x86_64__) || defined(_M_X64)
  if (CpuSupportsAvx2()) {
    MatchTemplateNccAVX2(image, img_w, img_h, img_stride, tpl, out_response);
    return;
  }
  if (CpuSupportsSse41()) {
    MatchTemplateNccSSE41(image, img_w, img_h, img_stride, tpl, out_response);
    return;
  }
#elif defined(__ARM_NEON) || defined(__aarch64__)
  MatchTemplateNccNEON(image, img_w, img_h, img_stride, tpl, out_response);
  return;
#endif

  artale::exp::MatchTemplateNccScalar(image, img_w, img_h, img_stride, tpl, out_response);
}

void ExpEngine::MatchTemplateNccScalar(const float* image, int img_w, int img_h, int img_stride,
                                       const PreparedTemplate& tpl, float* out_response) {
  artale::exp::MatchTemplateNccScalar(image, img_w, img_h, img_stride, tpl, out_response);
}

bool ExpEngine::ParseCrop(const uint8_t* gray_crop, int width, int height, int stride,
                          CropParseResult* out_result) const {
  if (gray_crop == nullptr || width < 20 || height < 8 || out_result == nullptr) {
    return false;
  }

  auto t_start = std::chrono::steady_clock::now();

  const PreparedTemplate& tpl_bracket = prepared_templates_.at('[');
  const PreparedTemplate& tpl_8 = prepared_templates_.at('8');
  const PreparedTemplate& tpl_pct = prepared_templates_.at('%');

  // 1 & 2. Multi-scale search using '[', '8', and '%'
  float expected_s = (height > 0) ? (38.0f / static_cast<float>(height)) : 1.0f;
  float s_min = std::max(0.35f, expected_s * 0.65f);
  float s_max = std::min(3.60f, std::max(expected_s * 1.25f, std::min(2.50f, expected_s * 1.45f)));

  constexpr int kNumScales = 18;
  float best_combo = -1.0f;
  float best_cs = 1.0f;
  int best_by = 0;

  std::vector<uint8_t> work_gray_buf;
  std::vector<float> work_float_buf;
  std::vector<float> resp_bracket;
  std::vector<float> resp_8;
  std::vector<float> resp_pct;

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

    const float* band_ptr = work_float_buf.data() + argmax_by * wn;

    int out_8w = wn - tpl_8.width + 1;
    int out_8h = kCanonicalStripHeight - tpl_8.height + 1;
    if (out_8w <= 0 || out_8h <= 0) continue;
    resp_8.resize(out_8w * out_8h);
    MatchTemplateNcc(band_ptr, wn, kCanonicalStripHeight, wn, tpl_8, resp_8.data());

    int out_pw = wn - tpl_pct.width + 1;
    int out_ph = kCanonicalStripHeight - tpl_pct.height + 1;
    if (out_pw <= 0 || out_ph <= 0) continue;
    resp_pct.resize(out_pw * out_ph);
    MatchTemplateNcc(band_ptr, wn, kCanonicalStripHeight, wn, tpl_pct, resp_pct.data());

    float max_v8 = -1.0f;
    for (float val : resp_8) {
      if (val > max_v8) max_v8 = val;
    }

    float max_vp = -1.0f;
    for (float val : resp_pct) {
      if (val > max_vp) max_vp = val;
    }

    float combo = max_vb + std::max(max_v8, max_vp);
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


  // States:
  // 0: start (expecting first EXP digit 0-9 -> 1)
  // 1: EXP digits (0-9 -> 1, '[' -> 2)
  // 2: after '[', expecting 1st pct integer digit (0-9 -> 3)
  // 3: after 1st pct integer digit (0-9 -> 4, '.' -> 5)
  // 4: after 2nd pct integer digit ('.' -> 5)
  // 5: after '.', expecting 1st pct decimal digit (0-9 -> 6)
  // 6: after 1st pct decimal digit (0-9 -> 7, '%' -> 8)
  // 7: after 2nd pct decimal digit ('%' -> 8)
  // 8: after '%', expecting ']' (']' -> 9)
  // 9: completed string
  constexpr int kNumStates = 10;
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

      // Allowed state transitions based on grammar
      std::vector<std::pair<char, int>> allowed;
      if (st == 0) {
        for (char d = '0'; d <= '9'; ++d)
          allowed.emplace_back(d, 1);
      } else if (st == 1) {
        for (char d = '0'; d <= '9'; ++d)
          allowed.emplace_back(d, 1);
        allowed.emplace_back('[', 2);
      } else if (st == 2) {
        for (char d = '0'; d <= '9'; ++d)
          allowed.emplace_back(d, 3);
      } else if (st == 3) {
        for (char d = '0'; d <= '9'; ++d)
          allowed.emplace_back(d, 4);
        allowed.emplace_back('.', 5);
      } else if (st == 4) {
        allowed.emplace_back('.', 5);
      } else if (st == 5) {
        for (char d = '0'; d <= '9'; ++d)
          allowed.emplace_back(d, 6);
      } else if (st == 6) {
        for (char d = '0'; d <= '9'; ++d)
          allowed.emplace_back(d, 7);
        allowed.emplace_back('%', 8);
      } else if (st == 7) {
        allowed.emplace_back('%', 8);
      } else if (st == 8) {
        allowed.emplace_back(']', 9);
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

        float min_ncc = (ch == '1' || ch == '[' || ch == ']') ? kMinNccNarrowOrBracket : kMinNccDigitOrDot;
        int min_adv = (ch == '.') ? 4 : ((ch == '[' || ch == ']') ? 6 : ((ch == '1') ? 10 : std::max(t.width, 11)));

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

  // Select best terminal state in state 9
  int best_term_x = -1;
  int best_term_st = -1;
  float best_term_score = -1e8f;

  for (int x = 0; x <= win_w; ++x) {
    const DpNode& node = get_dp(x, 9);
    if (node.score > best_term_score) {
      best_term_score = node.score;
      best_term_x = x;
      best_term_st = 9;
    }
  }

  // Require completed grammar (state 9 reached with closing bracket)
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

  // Enforce character contiguity so digits/occluded regions cannot be skipped
  for (size_t i = 0; i + 1 < chars.size(); ++i) {
    char ch = chars[i].character;
    const PreparedTemplate& t = prepared_templates_.at(ch);
    int min_adv = (ch == '.') ? 4 : ((ch == '[' || ch == ']') ? 6 : ((ch == '1') ? 10 : std::max(t.width, 11)));
    int gap = chars[i + 1].x - (chars[i].x + min_adv);
    int max_gap = (ch == '%') ? 24 : 8;
    if (gap > max_gap) {
      return false;
    }
  }

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

  if (exp_digits.empty() || pct_part.empty()) {
    return false;
  }

  char* exp_end = nullptr;
  int64_t exp_val = std::strtoll(exp_digits.c_str(), &exp_end, 10);
  if (exp_end == nullptr || *exp_end != '\0') {
    return false;
  }

  char* pct_end = nullptr;
  double pct_val = std::strtod(pct_part.c_str(), &pct_end);
  if (pct_end == nullptr || *pct_end != '\0' || pct_val < 0.0 || pct_val >= 100.0) {
    return false;
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
