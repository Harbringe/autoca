"""Application-facing encryption helpers.

Business logic calls ``encrypt_for_firm`` / ``decrypt_for_firm`` and never
touches an adapter or an envelope format directly. Two reasons:

* the encryption context is built in exactly one place, so every ciphertext in
  the system is bound to its firm id without anyone having to remember;
* swapping the KMS backend cannot change these signatures.
"""

from __future__ import annotations

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
