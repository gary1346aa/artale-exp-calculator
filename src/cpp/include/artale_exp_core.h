#pragma once

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
    #define ARTALE_API __attribute__ ((visibility ("default")))
  #else
    #define ARTALE_API
  #endif
#endif

typedef struct {
    int64_t exp_value;      // Parsed integer EXP (e.g. 772097)
    double exp_percent;     // Parsed percentage (e.g. 0.32), -1.0 if not available
    int success;            // 1 if successfully locked and parsed, 0 otherwise
    float parse_time_ms;    // Processing latency in milliseconds
    char exp_string[64];    // Formatted raw string e.g. "772097[0.32%]"
    int crop_x;             // Absolute text bounding box X in original frame
    int crop_y;             // Absolute text bounding box Y in original frame
    int crop_w;             // Text bounding box width
    int crop_h;             // Text bounding box height
    int logo_x;             // Absolute logo bounding box X in original frame
    int logo_y;             // Absolute logo bounding box Y in original frame
    int logo_w;             // Logo bounding box width
    int logo_h;             // Logo bounding box height
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
 * @return 0 on success (with out_result->success indicating match status), non-zero on invalid arguments.
 */
ARTALE_API int ParseExpFromBuffer(
    const uint8_t* bgr_data,
    int width,
    int height,
    int stride,
    int bytes_per_px,
    ExpResult* out_result
);

#ifdef __cplusplus
}
#endif
