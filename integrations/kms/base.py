"""Key management and envelope encryption.

Dev:  a local master key from the environment (LocalFernetKMSAdapter)
Beta: AWS KMS

The envelope format and the AES-GCM data-plane live *here*, in the base class,
and are identical for every backend. A KMS adapter's entire job is two methods:
mint a data key wrapped by the master key, and unwrap one. That split is what
makes the AWS swap safe -- the ciphertext on disk does not change format when
the key manager does, so there is no migration of existing data.

Envelope layout::

    b"ACAE"          4 bytes   magic
    version          1 byte
    len(wrapped)     2 bytes   big-endian
    wrapped_dek      n bytes   the data key, encrypted by the master key
    nonce           12 bytes
    ciphertext       rest      AES-256-GCM, tag appended

The encryption context (see ``encrypt``) is bound in as AES-GCM additional
authenticated data. It always carries the firm id, which means a ciphertext
belonging to firm A **cannot be decrypted while firm B's context is active**,
even if a bug hands the wrong blob to the wrong tenant. That is a second,
cryptographic isolation boundary sitting underneath the RLS one.
"""

from __future__ import annotations

import abc
import json
import os
import struct
from dataclasses import dataclass

MAGIC = b"ACAE"
VERSION = 1
NONCE_BYTES = 12
HEADER = struct.Struct(">4sBH")


class EnvelopeError(RuntimeError):
    """Malformed envelope, wrong key, or mismatched encryption context."""


@dataclass(frozen=True)
class DataKey:
    plaintext: bytes
    wrapped: bytes


class KMSAdapter(abc.ABC):
    """Envelope encryption. Subclasses implement key wrapping only."""

    @abc.abstractmethod
    def generate_data_key(self) -> DataKey:
        """Mint a fresh 32-byte data key plus its master-key-wrapped form."""

    @abc.abstractmethod
    def unwrap_data_key(self, wrapped: bytes) -> bytes:
        """Recover a data key's plaintext from its wrapped form."""

    # -- data plane, identical across backends -----------------------------

    @staticmethod
    def _aad(context: dict | None) -> bytes:
        # Canonical JSON so the AAD is byte-identical on encrypt and decrypt
        # regardless of dict ordering.
        return json.dumps(context or {}, sort_keys=True, separators=(",", ":")).encode()

    def encrypt(self, plaintext: bytes, context: dict | None = None) -> bytes:
        """Encrypt under a fresh data key.

        ``context`` must include ``firm_id`` for anything tenant-owned. Callers
        should use ``core.crypto.firm_context_aad()`` rather than hand-building
        it, so the convention stays uniform.
        """
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        key = self.generate_data_key()
        nonce = os.urandom(NONCE_BYTES)
        ciphertext = AESGCM(key.plaintext).encrypt(nonce, plaintext, self._aad(context))
        return (
            HEADER.pack(MAGIC, VERSION, len(key.wrapped))
            + key.wrapped
            + nonce
            + ciphertext
        )

    def decrypt(self, blob: bytes, context: dict | None = None) -> bytes:
        from cryptography.exceptions import InvalidTag
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        if len(blob) < HEADER.size:
            raise EnvelopeError("Ciphertext is too short to contain an envelope header.")

        magic, version, wrapped_len = HEADER.unpack(blob[: HEADER.size])
        if magic != MAGIC:
            raise EnvelopeError("Not an AutoCA envelope (bad magic).")
        if version != VERSION:
            raise EnvelopeError(f"Unsupported envelope version {version}.")

        offset = HEADER.size
        wrapped = blob[offset : offset + wrapped_len]
        offset += wrapped_len
        nonce = blob[offset : offset + NONCE_BYTES]
        ciphertext = blob[offset + NONCE_BYTES :]
        if len(wrapped) != wrapped_len or len(nonce) != NONCE_BYTES:
            raise EnvelopeError("Truncated envelope.")

        data_key = self.unwrap_data_key(wrapped)
        try:
            return AESGCM(data_key).decrypt(nonce, ciphertext, self._aad(context))
        except InvalidTag as exc:
            raise EnvelopeError(
                "Decryption failed: the ciphertext was tampered with, or the "
                "encryption context does not match the one used to encrypt it "
                "(most often, the wrong firm)."
            ) from exc

    @property
    def name(self) -> str:
        return type(self).__name__
