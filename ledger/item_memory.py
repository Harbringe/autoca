"""What a party's invoice lines usually say, remembered from the lines a person has already confirmed.

An invoice prints a long product description with batch codes in it (``FPPUSLH1880000 ULTRATECH SUPER PPC 120 Bags LM HDPE/PP``)
and a quantity that is sometimes missing. When a person corrects a line and books, that correction is kept with the invoice's
reading. The next invoice from the same party that has a line like it gets the description the person chose, its HSN/SAC and
unit when the page had none, and the quantity the party usually sends when the page had none.

Matching is by the words that identify the product, not the exact string, because the codes and counts in it change. Nothing is
learned from a line a person has not confirmed, and nothing here overwrites a figure the invoice printed.

This module is arithmetic on dicts only; ``ledger.invoice_intake`` supplies the confirmed lines and takes the result.
"""

from __future__ import annotations

import re
from collections import Counter

#: Two descriptions are the same product when at least this share of their identifying words agree.
SIMILARITY = 0.75
#: Words that say the pack or the paper, not the product.
_NOISE = frozenset({"bag", "bags", "nos", "no", "pcs", "pc", "unit", "units", "qty", "item", "the", "and", "of"})


def key_words(description: str) -> frozenset[str]:
    """The words that identify a product: letters only, three or more, lower case, without pack and paper words."""
    words = re.findall(r"[a-z]{3,}", str(description or "").lower())
    return frozenset(w for w in words if w not in _NOISE)


def similar(a: str, b: str) -> bool:
    left, right = key_words(a), key_words(b)
    if len(left) < 2 or len(right) < 2:
        return False
    return len(left & right) / len(left | right) >= SIMILARITY


def learn(confirmed_batches: list[list[dict]]) -> list[dict]:
    """Fold the confirmed lines of earlier invoices (newest first) into one entry per product.

    Each entry: the description as the person wrote it, the HSN/SAC and unit last used, and the quantity used most often.
    """
    products: list[dict] = []
    for lines in confirmed_batches:
        for line in lines:
            original = str(line.get("read_description") or line.get("description") or "")
            chosen = str(line.get("description") or "").strip()
            if not original or not chosen:
                continue
            for product in products:
                if similar(product["read"], original) or similar(product["description"], chosen):
                    break
            else:
                product = {"read": original, "description": chosen, "hsn_sac": "", "unit": "", "quantities": Counter()}
                products.append(product)
            if line.get("hsn_sac") and not product["hsn_sac"]:
                product["hsn_sac"] = str(line["hsn_sac"])
            if line.get("unit") and not product["unit"]:
                product["unit"] = str(line["unit"])
            quantity = str(line.get("quantity") or "").strip()
            if quantity:
                product["quantities"][quantity] += 1
    for product in products:
        counted = product.pop("quantities")
        product["usual_quantity"] = counted.most_common(1)[0][0] if counted else ""
    return products


def apply(lines: list[dict], products: list[dict]) -> list[dict]:
    """The invoice's lines with what is remembered filled in, the original wording kept as ``read_description``.

    A printed HSN, unit or quantity always stands; only blanks are filled. ``usual_quantity`` is added so the form can say
    "usually 60" even where the page printed something else.
    """
    out = []
    for line in lines:
        match = next((p for p in products if similar(p["read"], line.get("description", "")) or similar(p["description"], line.get("description", ""))), None)
        new = dict(line)
        new.setdefault("read_description", line.get("description", ""))
        if match is not None:
            new["description"] = match["description"]
            if not new.get("hsn_sac") and match["hsn_sac"]:
                new["hsn_sac"] = match["hsn_sac"]
            if not new.get("unit") and match["unit"]:
                new["unit"] = match["unit"]
            if not new.get("quantity") and match["usual_quantity"]:
                new["quantity"] = match["usual_quantity"]
            new["usual_quantity"] = match["usual_quantity"]
            new["remembered"] = True
        out.append(new)
    return out
