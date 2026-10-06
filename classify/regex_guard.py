"""Is a member's regex safe to run against every narration of every statement?

Python's ``re`` backtracks, holds the GIL and has no timeout, so one pattern that backtracks exponentially, saved by one
member of staff, stalls the shared web workers for everyone. A pattern cannot be told safe by matching its text, so this
reads the parsed pattern instead and refuses the shapes that cause trouble:

* a repetition whose body contains another repetition or an alternation -- ``(a+)+``, ``(a|aa)+``, ``(a?){25}a{25}``;
* a back-reference, which can make matching exponential on its own;
* more than ``MAX_OPEN_REPEATS`` unbounded or very wide repetitions, whose product is a polynomial of that degree in the text length.

Everything refused here has a plain rewrite, and the product's other match types cover what most rules need.
"""

from __future__ import annotations

try:  # Python 3.11+ moved the parser
    import re._constants as _c
    import re._parser as _p
except ImportError:  # pragma: no cover - older interpreters
    import sre_constants as _c
    import sre_parse as _p

MAX_OPEN_REPEATS = 3
#: A bounded repetition wider than this counts as open-ended: ``a{0,999}`` costs what ``a*`` does.
WIDE_REPEAT = 20
#: Narrations are short; a pattern is never run against more than this much of one, which also bounds the cost of any
#: polynomial pattern that is still allowed.
MAX_TEXT_LENGTH = 300

_REPEATS = {_c.MAX_REPEAT, _c.MIN_REPEAT, getattr(_c, "POSSESSIVE_REPEAT", _c.MAX_REPEAT)}
_GROUPS = {_c.SUBPATTERN, getattr(_c, "ATOMIC_GROUP", _c.SUBPATTERN)}


class UnsafeRegex(ValueError):
    """The pattern is valid but may take far too long to run."""


def check(pattern: str) -> None:
    """Raise ``UnsafeRegex`` (a reason a person can act on) or ``re.error`` (malformed); return quietly if it is fine."""
    parsed = _p.parse(pattern)
    open_repeats = 0

    def walk(nodes, inside_repeat: bool) -> None:
        nonlocal open_repeats
        for op, arg in nodes:
            if op == _c.GROUPREF or op == _c.GROUPREF_EXISTS:
                raise UnsafeRegex("A back-reference (\1) can take the matcher exponential time. Rewrite without it.")
            if op in _REPEATS:
                low, high, body = arg
                wide = high == _c.MAXREPEAT or high > WIDE_REPEAT
                if wide:
                    open_repeats += 1
                if _has_repeat_or_choice(body) and high > 1:
                    raise UnsafeRegex(
                        "A repeated group containing a repetition or an alternative -- like (a+)+ or (a|b)+ -- can "
                        "take the matcher exponential time. Rewrite without nesting."
                    )
                walk(body, True)
            elif op in _GROUPS:
                walk(arg[-1], inside_repeat)
            elif op == _c.BRANCH:
                for branch in arg[1]:
                    walk(branch, inside_repeat)
            elif op in (_c.ASSERT, _c.ASSERT_NOT):
                walk(arg[1], inside_repeat)
            elif op == _c.CATEGORY or op == _c.IN or op == _c.LITERAL:
                continue

    walk(parsed, False)
    if open_repeats > MAX_OPEN_REPEATS:
        raise UnsafeRegex(
            f"At most {MAX_OPEN_REPEATS} open-ended repetitions (+, *, {{n,}}) are allowed; more can take the matcher "
            "exponential or very long polynomial time."
        )


def _has_repeat_or_choice(nodes) -> bool:
    for op, arg in nodes:
        if op in _REPEATS or op == _c.BRANCH:
            return True
        if op in _GROUPS and _has_repeat_or_choice(arg[-1]):
            return True
        if op in (_c.ASSERT, _c.ASSERT_NOT) and _has_repeat_or_choice(arg[1]):
            return True
    return False
