"""The audit trail of the books' masters: who changed a ledger, party or rule, and what it was before and after.

``EntryChange`` already keeps the history of vouchers. This is the same idea for what the vouchers are written against, so the
audit screen can show both. Rows are append-only (a database trigger), and only changes that actually change something are written.
"""

from __future__ import annotations

import datetime
import decimal
import uuid

from ledger.models import MasterChange

LEDGER_FIELDS = ("name", "group", "is_active", "status", "nce_line", "nce_section", "alias")
#: A party's GSTIN is held encrypted and is not copied into a log; ``has_gstin`` still shows it being added or removed.
PARTY_FIELDS = ("canonical_name", "role", "rcm_default", "msme", "udyam_no", "tds_section", "ledger", "notes", "is_active", "has_gstin")
TYPE_FIELDS = ("name", "parent")
CLASS_FIELDS = ("name", "voucher_type", "type_name", "head_ledger", "gst_rate")
GODOWN_FIELDS = ("name",)
ITEM_FIELDS = ("name", "unit", "hsn_sac", "gst_rate", "reorder_level", "purchase_ledger", "sales_ledger", "aliases")
RULE_FIELDS = ("match_type", "pattern", "direction", "ledger", "party", "rcm", "tds_section", "confidence", "priority", "is_active")


def _plain(value):
    if isinstance(value, uuid.UUID | decimal.Decimal):
        return str(value)
    if isinstance(value, datetime.date | datetime.datetime):
        return value.isoformat()
    return value


def snapshot(obj, fields: tuple[str, ...]) -> dict:
    """The named fields of ``obj`` as plain JSON values; a relation is its id."""
    out = {}
    for name in fields:
        if name == "has_gstin":
            out[name] = bool(getattr(obj, "gstin_hash", ""))
            continue
        field = obj._meta.get_field(name)
        out[name] = _plain(getattr(obj, field.attname if field.is_relation else name))
    return out


def record_master_change(client, kind: str, obj_id, action: str, *, label: str, before: dict, after: dict, actor) -> MasterChange | None:
    """Write one row. An edit that changed nothing writes nothing."""
    if action == "EDITED" and before == after:
        return None
    return MasterChange.objects.create(
        firm_id=client.firm_id, client=client, kind=kind, object_id=obj_id, action=action, label=(label or "")[:255], before=before, after=after, actor=actor
    )
