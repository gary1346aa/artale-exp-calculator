// Copyright 2026 Artale Exp Project. All rights reserved.
// Google C++ Style Guide compliant.

#include <cstdlib>
#include <filesystem>
#include <iostream>
#include <string>

#include "gtest/gtest.h"

namespace artale {
namespace exp {

TEST(CodeIntegrityTest, PythonTypeHintsAndImports) {
  // Locate repo root: check TEST_SRCDIR, current path, or walk up until config.py
  std::filesystem::path current = std::filesystem::current_path();
  std::filesystem::path repo_dir;

  for (auto p = current; !p.empty() && p != p.parent_path(); p = p.parent_path()) {
    if (std::filesystem::exists(p / "config.py") && std::filesystem::exists(p / "tests")) {
      repo_dir = p;
      break;
    }
  }

  // If not found in ancestors, check TEST_SRCDIR/_main
  if (repo_dir.empty()) {
    const char* srcdir = std::getenv("TEST_SRCDIR");
    if (srcdir) {
      std::filesystem::path p = std::filesystem::path(srcdir) / "_main";
      if (std::filesystem::exists(p / "config.py")) {
        repo_dir = p;
      }
    }
  }

  std::string cmd;
  if (!repo_dir.empty()) {
    cmd = "cd /d \"" + repo_dir.string() + "\" && python -m unittest tests.test_code_integrity";
  } else {
    cmd = "python -m unittest tests.test_code_integrity";
  }

  int ret = std::system(cmd.c_str());
  EXPECT_EQ(ret, 0) << "Python code integrity test failed!";
}

}  // namespace exp
}  // namespace artale
