"""Golden tests for typingtrainer.linebreak: subdivide_line and str_find_all.

Covers subdivide_line at both split types ("LHS" and "CENTRE"), a line under the
limit, a line far over the limit with no punctuation at all, and the boundary case
exactly at the limit. Cases mirror the original functions.run_tests(), now deleted
in favour of this suite.
"""

from typingtrainer.linebreak import str_find_all, subdivide_line


def test_str_find_all_finds_every_occurrence():
    assert list(str_find_all("a.b.c.", ".")) == [1, 3, 5]


def test_str_find_all_no_match():
    assert list(str_find_all("abc", "x")) == []


def test_subdivide_line_under_limit_returns_unchanged():
    assert subdivide_line("short text.", line_len_limit=100) == ["short text."]


def test_subdivide_line_exactly_at_limit_returns_unchanged():
    line = "a" * 100
    assert subdivide_line(line, line_len_limit=100) == [line]


def test_subdivide_line_no_punctuation_over_limit_returns_unchanged():
    """No split point exists, so a line far over the limit is returned as-is."""
    line = "a" * 150
    assert subdivide_line(line, line_len_limit=100) == [line]


def test_subdivide_line_lhs_splits_at_last_punctuation_before_limit():
    long_string = "".join(["a" * 70, "?", "a" * 20, "?", "a" * 40])
    expected = ["".join(["a" * 70, "?", "a" * 20, "?"]), "a" * 40]
    assert subdivide_line(long_string, line_len_limit=100, split_type="LHS") == expected


def test_subdivide_line_centre_splits_near_the_middle():
    long_string = "".join(["a" * 70, "?", "a" * 20, "?", "a" * 40])
    expected = ["".join(["a" * 70, "?"]), "".join(["a" * 20, "?", "a" * 40])]
    assert subdivide_line(long_string, line_len_limit=100, split_type="CENTRE") == expected


def test_subdivide_line_invalid_split_type_raises():
    import pytest

    # punctuation within line[min_split_index:line_len_limit] so the line does not
    # short-circuit as unsplittable before the split_type is ever checked
    line = "a" * 20 + "?" + "a" * 100
    with pytest.raises(ValueError):
        subdivide_line(line, line_len_limit=100, split_type="BOGUS")
