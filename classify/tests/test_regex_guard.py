"""A member's regex may not be able to stall the shared workers."""

from __future__ import annotations

import re
import time

import pytest

from classify import regex_guard
from classify.regex_guard import UnsafeRegex, check

DANGEROUS = [r"(a+)+$", r"(a|aa)+$", r"(a|a)*$", r"(a?){25}a{25}", r"(\w*)*x", r"(a)\1", r"a*a*a*a*b", r"(.*a){12}",
    r"a{0,999}a{0,999}a{0,999}a{0,999}b", r"(a{1,30}){1,30}$"]
ORDINARY = [
    r"UPI/[A-Z]+/\d{6,}",
    r"(?:HDFC|ICICI) BANK",
    r"(abc)+",
    r"\bNEFT\b.*SALARY",
    r"^IMPS-\d+-",
    r"EMI|INSTALMENT",
    r"CHQ\s*(?:NO)?\s*\d+",
]


@pytest.mark.parametrize("pattern", DANGEROUS)
def test_a_pattern_that_can_backtrack_badly_is_refused(pattern):
    with pytest.raises(UnsafeRegex):
        check(pattern)


@pytest.mark.parametrize("pattern", ORDINARY)
def test_ordinary_narration_patterns_are_allowed(pattern):
    check(pattern)


def test_a_malformed_pattern_is_still_a_regex_error():
    with pytest.raises(re.error):
        check("(unclosed")


def test_an_allowed_pattern_is_fast_on_the_longest_text_it_will_be_run_on():
    pattern = r"UPI/[A-Z]+/\d{6,}.*SALARY"
    check(pattern)
    text = ("A" * 990) + "!"
    started = time.perf_counter()
    re.search(pattern, text[: regex_guard.MAX_TEXT_LENGTH], re.IGNORECASE)
    assert time.perf_counter() - started < 1.0
