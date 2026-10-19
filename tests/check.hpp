// check.hpp - a minimal test harness (no external dependencies)
#pragma once

#include <cmath>
#include <cstdio>
#include <functional>
#include <string>
#include <vector>

namespace check {

inline int& failures() { static int n = 0; return n; }
struct Case { std::string name; std::function<void()> fn; };
inline std::vector<Case>& cases() { static std::vector<Case> c; return c; }

struct Register {
    Register(const std::string& name, std::function<void()> fn) { cases().push_back({name, fn}); }
};

inline int run_all() {
    for (const auto& c : cases()) {
        int before = failures();
        c.fn();
        std::printf("%s %s\n", failures() == before ? "  ok  " : "  FAIL", c.name.c_str());
    }
    std::printf("\n%zu tests, %d failed checks\n", cases().size(), failures());
    return failures() == 0 ? 0 : 1;
}

} // namespace check

#define TEST_CASE(name)                                          \
    static void name();                                          \
    static check::Register reg_##name(#name, name);              \
    static void name()

#define CHECK(cond)                                                                   \
    do {                                                                              \
        if (!(cond)) {                                                                \
            ++check::failures();                                                      \
            std::printf("    %s:%d: CHECK(%s) failed\n", __FILE__, __LINE__, #cond);  \
        }                                                                             \
    } while (0)

#define CHECK_NEAR(a, b, tol)                                                          \
    do {                                                                               \
        double va_ = (a), vb_ = (b);                                                   \
        if (!(std::fabs(va_ - vb_) <= (tol))) {                                        \
            ++check::failures();                                                       \
            std::printf("    %s:%d: %s = %g, expected %g +- %g\n", __FILE__, __LINE__, \
                        #a, va_, vb_, static_cast<double>(tol));                       \
        }                                                                              \
    } while (0)
