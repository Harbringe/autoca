"""What makes two records the same invoice, shared by everything that has to agree about it.

An invoice turns up in several places: the books (a bill), an uploaded purchase register, the GSTR-2B the portal
publishes, a GST decision, the invoice file itself. They are only reconciled if they are recognised as the same
invoice, so there is exactly ONE definition of that, here, and every module imports it.

It lives in ``core`` rather than in ``gst/`` or ``ledger/`` so neither depends on the other. ``gst/`` is a removable
add-on and nothing outside it may import it; the books need the same key without importing it.

The key is supplier identity plus the normalised invoice number, hashed per firm. It is a blind index in the same sense
as ``core.crypto.blind_index``: it cannot be reversed, differs between firms, and is comparable by equality, so it is safe
to store beside a row and to index.
"""

from __future__ import annotations

import re

from core.crypto import blind_index

#: The purpose string the blind index is keyed with. It is the label GST decisions were first stored under, and it is
#: kept as it is so every key already stored stays valid. It names a purpose, not the module that owns the function.
INVOICE_KEY_PURPOSE = "gst.match"

_NON_ALNUM = re.compile(r"[^A-Z0-9]")


def normalise_invoice_no(raw: str) -> str:
    """The comparison form of an invoice number.

    Suppliers and staff disagree about separators, case and zero padding for
    the same invoice: ``INV/0042``, ``inv-42`` and ``INV 042`` are one invoice.
    Dropping non-alphanumerics, upper-casing and stripping zeros that follow
    a letter or start the number makes those equal. It cannot make two
    different invoices equal in any way a real numbering series produces -- if
    it ever does, the amounts are compared next and will differ.
    """
    s = _NON_ALNUM.sub("", (raw or "").upper())
    # Zeros directly after a letter (INV042 -> INV42) or at the very start.
    s = re.sub(r"(?<=[A-Z])0+(?=[0-9])", "", s)
    s = s.lstrip("0")
    return s or "0"


def normalise_gstin(raw: str) -> str:
    return (raw or "").strip().upper()


def supplier_identity(gstin: str, party_id=None) -> str:
    """Who the invoice is from, in the form the key uses.

    The GSTIN when there is one. An unregistered supplier has none, so the party's own id stands in, prefixed so it can
    never equal a real GSTIN. Adding a GSTIN to the party later changes this value, which is why a bill keeps its key as
    first written and the new one is recorded beside it (see ``ledger.billing``).
    """
    cleaned = normalise_gstin(gstin)
    if cleaned:
        return cleaned
    return f"PARTY:{party_id}" if party_id is not None else ""


def invoice_key(firm_id, supplier: str, invoice_no: str) -> str:
    """An invoice's identity: supplier plus normalised number, hashed for this firm."""
    ident = f"{normalise_gstin(supplier)}|{normalise_invoice_no(invoice_no)}"
    return blind_index(ident, firm_id, INVOICE_KEY_PURPOSE)
