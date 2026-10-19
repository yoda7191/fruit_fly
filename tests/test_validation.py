import math

from fruit_fly.validation import Check, bisect, fmt, spearman


def test_bisect_finds_target_both_directions():
    assert abs(bisect(lambda x: 2 * x, 0, 10, 6.0, iters=30) - 3.0) < 1e-6
    assert abs(bisect(lambda x: -x, 0, 10, -4.0, iters=30, increasing=False) - 4.0) < 1e-6
    assert abs(bisect(lambda x: math.log10(x), 1e-7, 1e-3, -5.0, iters=40, log=True) - 1e-5) < 1e-9


def test_bisect_refuses_undefined_values():
    # a NaN measurement must stop the search, not walk it to one end of the range
    try:
        bisect(lambda x: math.nan, 1e-7, 1e-4, -0.6, iters=8, log=True, increasing=False)
    except ValueError as e:
        assert "undefined" in str(e)
    else:
        raise AssertionError("bisect accepted NaN")


def test_spearman_and_formatting():
    assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) == 1.0
    assert spearman([1, 2, 3, 4], [4, 3, 2, 1]) == -1.0
    assert math.isnan(spearman([1, 2], [2, 1]))
    assert fmt(0.123) == "+0.12" and fmt(-0.6, pct=True) == "-60%" and fmt(math.nan) == "n/a"


def test_check_records_unjudged_findings():
    c = Check("x", "finding", "ref", "measured", "target", None)
    assert c.passed is None and c.note == ""


if __name__ == "__main__":
    import sys
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
    sys.exit(0)