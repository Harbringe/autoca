"""What the platform spends on the model, one row per call.

This is operating data for the platform owner, not a firm's books, so it holds counts and tokens and nothing else: no
narration, name, amount, statement text or prompt ever goes in. ``firm_id`` and ``client_id`` are plain identifiers
rather than foreign keys, on purpose: the table belongs to the platform and has no row-level security policy, and a
foreign key to a firm would make it look like a tenant table that escaped one (``core.db.introspect`` flags exactly
that). The web application's database role may insert and read, never update or delete, so a recorded call cannot be
rewritten.

A removable add-on: delete the app, its migration and the three recording calls (``classify/llm.py``,
``banking/scan.py``) and nothing else notices.
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils import timezone


class Purpose(models.TextChoices):
    CLASSIFY = "CLASSIFY", "Placing bank rows in ledgers"
    SCAN = "SCAN", "Reading a scanned statement"
    OTHER = "OTHER", "Other"


class Outcome(models.TextChoices):
    OK = "OK", "Answered"
    RATE_LIMITED = "RATE_LIMITED", "Rate limited"
    ERROR = "ERROR", "Failed"


class UsageEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    at = models.DateTimeField(default=timezone.now, db_index=True)
    purpose = models.CharField(max_length=12, choices=Purpose.choices)
    model = models.CharField(max_length=80, blank=True, default="")
    outcome = models.CharField(max_length=14, choices=Outcome.choices, default=Outcome.OK)
    #: Which firm and client the call was for. Identifiers only; the admin shows the firm's name by looking it up.
    firm_id = models.UUIDField(null=True, blank=True, db_index=True)
    client_id = models.UUIDField(null=True, blank=True)
    input_tokens = models.PositiveIntegerField(default=0)
    #: Of the input tokens, those served from the provider's cache (billed at a fraction).
    cached_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    latency_ms = models.PositiveIntegerField(default=0)
    #: Rows or pages the call was about, so a cost can be read per row or per page.
    rows = models.PositiveIntegerField(default=0)
    pages = models.PositiveIntegerField(default=0)
    #: The price at the time of the call, in millionths of a US dollar: an integer, so sums are exact. Fixed when
    #: recorded, so a later change to the price table does not rewrite history.
    cost_micro_usd = models.BigIntegerField(default=0)
    #: False when the model had no price in ``LLM_PRICES``, so a zero cost means "unknown", not "free".
    priced = models.BooleanField(default=True)

    class Meta:
        db_table = "usage_event"
        ordering = ["-at"]
        indexes = [models.Index(fields=["firm_id", "at"], name="idx_usage_firm_at")]
        verbose_name = "model call"
        verbose_name_plural = "model calls"

    def __str__(self) -> str:
        return f"{self.at:%Y-%m-%d %H:%M} {self.purpose} {self.model}"
