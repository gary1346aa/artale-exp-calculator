cmake_minimum_required(VERSION 3.16)
project(artale_exp_core VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Ensure repository root is in include path so "src/cpp/..." includes work
get_filename_component(REPO_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../.." ABSOLUTE)

include_directories(
    ${REPO_ROOT}
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${CMAKE_CURRENT_SOURCE_DIR}/include
    ${CMAKE_CURRENT_SOURCE_DIR}/src
)

add_library(artale_exp_core SHARED
    src/exp_engine.cc
    src/artale_exp_core.cc
)

target_compile_definitions(artale_exp_core PRIVATE ARTALE_EXP_EXPORTS)

if (MSVC)
    target_compile_options(artale_exp_core PRIVATE /O2 /arch:AVX2)
    set_target_properties(artale_exp_core PROPERTIES
        OUTPUT_NAME "artale_exp_core"
        PREFIX ""
    )
elseif (APPLE)
    # macOS Apple Silicon (ARM64 with NEON) or Intel x86_64
    target_compile_options(artale_exp_core PRIVATE -O3 -Wall)
    if (CMAKE_SYSTEM_PROCESSOR MATCHES "arm64|aarch64")
        message(STATUS "Configuring for Apple Silicon ARM64 NEON")
    else()
        target_compile_options(artale_exp_core PRIVATE -mavx2 -mfma)
    endif()
    set_target_properties(artale_exp_core PROPERTIES
        OUTPUT_NAME "artale_exp_core"
        PREFIX "lib"
    )
else()
    # Linux / Windows GCC / Clang
    target_compile_options(artale_exp_core PRIVATE -O3 -mavx2 -mfma -Wall)
    if (WIN32)
        target_link_options(artale_exp_core PRIVATE -static)
        set_target_properties(artale_exp_core PROPERTIES
            OUTPUT_NAME "artale_exp_core"
            PREFIX ""
        )
    else()
        set_target_properties(artale_exp_core PROPERTIES
            OUTPUT_NAME "artale_exp_core"
            PREFIX "lib"
        )
    endif()
endif()
