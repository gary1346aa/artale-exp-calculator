// Copyright 2026 Artale Exp Project. All rights reserved.
// Google C++ Style Guide compliant.

#ifndef ARTALE_EXP_CORE_H_
#define ARTALE_EXP_CORE_H_

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#if defined(_WIN32) || defined(__CYGWIN__)
#ifdef ARTALE_EXP_EXPORTS
#define ARTALE_API __declspec(dllexport)
#else
#define ARTALE_API __declspec(dllimport)
#endif
#else
#if __GNUC__ >= 4
#define ARTALE_API __attribute__((visibility("default")))
#else
#define ARTALE_API
#endif
#endif

typedef struct {
  int64_t exp_value;    // Parsed integer EXP (e.g. 772097)
  double exp_percent;   // Parsed percentage (e.g. 0.32), -1.0 if not available
  int success;          // 1 if successfully locked and parsed, 0 otherwise
  float parse_time_ms;  // Processing latency in milliseconds
  char exp_string[64];  // Formatted raw string e.g. "772097[0.32%]"
  int crop_x;           // Absolute text bounding box X in original frame
  int crop_y;           // Absolute text bounding box Y in original frame
  int crop_w;           // Text bounding box width
  int crop_h;           // Text bounding box height
  int logo_x;           // Absolute logo bounding box X in original frame
  int logo_y;           // Absolute logo bounding box Y in original frame
  int logo_w;           // Logo bounding box width
  int logo_h;           // Logo bounding box height
} ExpResult;

/**
 * Parses the Artale EXP bar from an uncompressed BGR / BGRA image frame buffer.
 *
 * @param bgr_data      Pointer to the first byte of the BGR/BGRA frame buffer
 * @param width         Width of the frame in pixels
 * @param height        Height of the frame in pixels
 * @param stride        Row stride (bytes per line, e.g. width * 3 or width * 4)
 * @param bytes_per_px  3 for BGR, 4 for BGRA
 * @param out_result    Pointer to ExpResult structure to populate
 * @return 0 on success (with out_result->success indicating match status),
 * non-zero on invalid arguments.
 */
ARTALE_API int ParseExpFromBuffer(const uint8_t* bgr_data, int width,
                                  int height, int stride, int bytes_per_px,
                                  ExpResult* out_result);

/**
 * Diagnostic & Unit-testing APIs to verify individual engine components
 * against reference Python/OpenCV implementations.
 */
ARTALE_API void Test_ExtractGraySubRect(const uint8_t* bgr_data, int width,
                                        int height, int stride,
                                        int bytes_per_px, int rx, int ry,
                                        int rw, int rh, uint8_t* out_gray);

ARTALE_API void Test_ResizeGray(const uint8_t* src, int src_w, int src_h,
                                int src_stride, uint8_t* dst, int dst_w,
                                int dst_h, int dst_stride);

ARTALE_API void Test_ResizeGrayScalar(const uint8_t* src, int src_w, int src_h,
                                      int src_stride, uint8_t* dst, int dst_w,
                                      int dst_h, int dst_stride);

ARTALE_API int Test_MatchTemplateNcc(const float* image, int img_w, int img_h,
                                     int img_stride, char ch,
                                     float* out_response);

#ifdef __cplusplus
}
#endif

#endif  // ARTALE_EXP_CORE_H_
