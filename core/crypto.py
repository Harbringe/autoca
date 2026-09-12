"""Application-facing encryption helpers.

Business logic calls ``encrypt_for_firm`` / ``decrypt_for_firm`` and never
touches an adapter or an envelope format directly. Two reasons:

* the encryption context is built in exactly one place, so every ciphertext in
  the system is bound to its firm id without anyone having to remember;
* swapping the KMS backend cannot change these signatures.
"""

from __future__ import annotations

import hashlib
import hmac

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from integrations.registry import get_kms


def firm_context_aad(firm_id, purpose: str = "generic") -> dict:
    """The encryption context bound into every tenant-owned ciphertext.

    ``purpose`` separates key usage domains -- a ciphertext produced for bank
    statements will not decrypt when handed to code expecting GST data, which
    turns a whole class of "wrong blob, right firm" bugs into a hard error.
    """
    return {"firm_id": str(firm_id), "purpose": purpose}


def encrypt_for_firm(plaintext, firm_id, purpose: str = "generic") -> bytes:
    if isinstance(plaintext, str):
        plaintext = plaintext.encode()
    return get_kms().encrypt(plaintext, firm_context_aad(firm_id, purpose))


def decrypt_for_firm(blob: bytes, firm_id, purpose: str = "generic") -> bytes:
    return get_kms().decrypt(blob, firm_context_aad(firm_id, purpose))


def decrypt_text_for_firm(blob: bytes, firm_id, purpose: str = "generic") -> str:
    return decrypt_for_firm(blob, firm_id, purpose).decode()


# ---------------------------------------------------------------------------
# Blind index
# ---------------------------------------------------------------------------


def blind_index(value: str, firm_id, purpose: str = "generic") -> str:
    """A deterministic, firm-scoped fingerprint of ``value``, for matching.

    Encrypting a bank account number or a GSTIN protects it and simultaneously
    destroys the thing the column was for: AES-GCM is randomised, so the same
    account encrypts differently every time and no index, join or uniqueness
    constraint can touch it. The standard answer is a second column holding a
    keyed hash -- equality still works, the value is still not recoverable.

    Three properties are load-bearing:

    * **Keyed, not a plain hash.** Account numbers and GSTINs are drawn from a
      small enough space to enumerate. A bare ``sha256`` of a GSTIN is a lookup
      table away from plaintext; an HMAC under a key an attacker does not have
      is not.
    * **Scoped per firm.** The key is derived from the firm id, so the same
      account number belonging to two firms produces two different indexes.
      Without this, equal fingerprints across the tenant boundary would leak
      that two firms bank with the same party -- a correlation RLS otherwise
      prevents.
    * **Separated by purpose.** An account-number index and a GSTIN index of
      the same digits must not collide.

    This is not encryption and does not replace it. Store both: the ciphertext
    is how the value is read back, this is only how rows are found.
    """
    key = _index_key(firm_id, purpose)
    return hmac.new(key, value.strip().upper().encode(), hashlib.sha256).hexdigest()


def _index_key(firm_id, purpose: str) -> bytes:
    root = getattr(settings, "BLIND_INDEX_KEY", None)
    if not root:
        raise ImproperlyConfigured(
            "BLIND_INDEX_KEY is not set. It keys every deterministic lookup "
            "column for encrypted identifiers; losing or changing it makes "
            "existing rows unfindable, so it is generated once and kept for "
            "the life of the deployment."
        )
    material = f"{firm_id}|{purpose}".encode()
    return hmac.new(root.encode(), material, hashlib.sha256).digest()
