"""Money is a whole number of paise. Everywhere, without exception.

Not a float, and not a ``Decimal`` either. ``Decimal`` is exact and would work,
but the architecture calls for integers end to end and it is right to, for two
reasons that only show up later:

* **Comparison across systems.** GST reconciliation compares our figures to
  GSTR-2B's, with a stated tolerance of one rupee per tax head. A tolerance is
  a subtraction, and subtracting values whose scale and quantisation came from
  two different sources is where "off by one paisa forever" is born. Integers
  have exactly one representation of every amount.
* **Nothing to configure.** ``Decimal`` arithmetic depends on a context --
  precision, rounding mode -- that is process-global and mutable. A library
  that sets it, or a worker that inherits a different one, changes the result
  of arithmetic that has already been written and tested. Integers cannot be
  reconfigured.

The rule that keeps this honest: **paise cross no boundary as anything else.**
Parsers produce paise, the database stores paise, the balance chain adds paise.
Rupees exist in exactly two places -- the screen, and the moment a rupee-scale
GST tolerance is applied -- and both call a function here to get there.

Field names carry the unit. ``balance_paise``, never ``balance``. It is uglier
and it is the whole point: a mixed-unit bug is invisible at the call site and
obvious at the field.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

#: One rupee.
PAISE = 100

#: 18 digits of paise is ten thousand crore, comfortably past any client this
#: system will see, and still inside a 64-bit integer.
MAX_PAISE = 10**18


class MoneyError(ValueError):
    """A value that cannot be read as an amount of money."""


def to_paise(value) -> int:
    """Convert a rupee value to whole paise.

    Accepts ``Decimal``, ``int``, or a string. Refuses ``float`` outright: by
    the time a float reaches here the error is already baked in, and accepting
    it would make this function the place the corruption becomes permanent
    rather than the place it was caught.
    """
    if isinstance(value, bool):
        raise MoneyError(f"Not an amount: {value!r}")
    if isinstance(value, float):
        raise MoneyError(
            f"Refusing to convert the float {value!r} to paise. Floats cannot "
            f"represent most decimal amounts exactly, so this value may already "
            f"be wrong. Parse to Decimal or int from the source text instead."
        )
    if isinstance(value, int):
        return value * PAISE
    if isinstance(value, str):
        value = _decimal_from_text(value)
    if not isinstance(value, Decimal):
        raise MoneyError(f"Cannot convert {type(value).__name__} to paise: {value!r}")

    scaled = value * PAISE
    whole = scaled.to_integral_value()
    if scaled != whole:
        raise MoneyError(
            f"{value} is finer than a paisa. Amounts are exact here; rounding, "
            f"where it is legitimate at all, is a decision the caller makes "
            f"explicitly and not a side effect of storing a number."
        )
    return int(whole)


def to_rupees(paise: int) -> Decimal:
    """Exact rupee value of ``paise``, for display and for GST comparison."""
    return (Decimal(int(paise)) / PAISE).quantize(Decimal("0.01"))


def format_inr(paise: int, *, symbol: bool = True) -> str:
    """Indian digit grouping: ``₹6,03,490.57``, not ``₹603,490.57``.

    Lakh and crore grouping puts separators every two digits after the first
    three. Getting this wrong is instantly visible to an Indian accountant and
    reads as software written for somewhere else.
    """
    negative = paise < 0
    rupees, fraction = divmod(abs(int(paise)), PAISE)
    digits = str(rupees)

    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        head = re.sub(r"(?<=\d)(?=(\d\d)+$)", ",", head)
        digits = f"{head},{tail}"

    out = f"{digits}.{fraction:02d}"
    if symbol:
        out = f"₹{out}"
    return f"-{out}" if negative else out


def _decimal_from_text(text: str) -> Decimal:
    """Read an Indian-format money string. Handles lakh grouping and Cr/Dr."""
    cleaned = text.strip().replace("−", "-").replace(",", "").replace(" ", "")
    if not cleaned:
        raise MoneyError("Empty string is not an amount.")

    sign = 1
    upper = cleaned.upper()
    for marker in ("CR", "DR"):
        if upper.endswith(marker):
            cleaned = cleaned[: -len(marker)]
            if marker == "DR":
                sign = -1
            break
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned, sign = cleaned[1:-1], -1

    try:
        return Decimal(cleaned) * sign
    except (InvalidOperation, ValueError) as exc:
        raise MoneyError(f"Not a money value: {text!r}") from exc
