"""How money crosses the wire.

Every amount is sent twice: as an integer number of paise, and as a formatted
string. That is not redundancy, it is the two things a client actually needs and
a refusal to make it choose badly between them.

* ``*_paise`` is an **integer**. A client that sorts, sums, filters or compares
  uses this. It is exact, and JSON integers survive JavaScript intact --
  which JSON numbers with a decimal point do not. Sending ``530.00`` and letting
  a browser parse it into a float reintroduces, at the last possible moment, the
  rounding error the entire backend was built to avoid.
* ``*_display`` is a **string**, already grouped the Indian way: ``₹6,03,490.57``.
  A client that renders uses this and never formats money itself. Lakh grouping
  is not something a frontend gets right by accident, and getting it wrong is
  instantly visible to the accountant reading the screen.

Serializers list their paise fields in ``money`` and the formatted twins appear
in the response and in the OpenAPI schema, so the two can never drift apart.
"""

from __future__ import annotations

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from core.money import format_inr


class PaiseField(serializers.IntegerField):
    """An exact amount, in whole paise."""

    def __init__(self, **kwargs):
        kwargs.setdefault(
            "help_text",
            "Whole paise, as an exact integer. 53000 means ₹530.00. Never a decimal.",
        )
        super().__init__(**kwargs)


@extend_schema_field(serializers.CharField(allow_null=True))
class MoneyDisplayField(serializers.Field):
    """The same amount, formatted for a screen. Read-only by definition."""

    def __init__(self, source_field: str, **kwargs):
        self.money_source = source_field
        kwargs["read_only"] = True
        kwargs.setdefault("source", "*")
        kwargs.setdefault(
            "help_text", "The amount with Indian digit grouping, e.g. ₹6,03,490.57."
        )
        super().__init__(**kwargs)

    def to_representation(self, instance):
        value = read_path(instance, self.money_source)
        return format_inr(value) if value is not None else None


def read_path(instance, path: str):
    """Follow a dotted attribute path, tolerating a None anywhere along it."""
    for part in path.split("."):
        instance = getattr(instance, part, None)
        if instance is None:
            return None
    return instance


class MoneySerializerMixin:
    """Adds a ``*_display`` string beside every ``*_paise`` field named in ``money``."""

    money: tuple[str, ...] = ()

    def get_fields(self):
        fields = super().get_fields()
        for name in self.money:
            display = name.replace("_paise", "_display")
            fields.setdefault(display, MoneyDisplayField(source_field=name))
        return fields
