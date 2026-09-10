"""Local KMS adapter -- development only.

What this is: a real envelope-encryption implementation whose master key happens
to sit in an environment variable. Data keys are minted per ciphertext and
wrapped with Fernet, exactly as AWS KMS would wrap them.

What this is NOT: key management. The master key is readable by anything that
can read the process environment, there is no rotation, no audit trail, and no
hardware boundary. It is adequate for development and unacceptable for real
client data.

The point of building it now is that every encrypt/decrypt call site in the
codebase is already correct. Moving to AWS KMS is:

    KMS_BACKEND=integrations.kms.aws.AWSKMSAdapter
    KMS_KEY_ID=arn:aws:kms:ap-south-1:...:key/...

and nothing outside integrations/kms/ moves.

Generate a master key:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""

import base64
import os

from .base import DataKey, EnvelopeError, KMSAdapter


class LocalFernetKMSAdapter(KMSAdapter):
    def __init__(self, master_key=None, **_ignored):
        if not master_key:
            raise ValueError(
                "KMS_LOCAL_MASTER_KEY is not set. Generate one with: python -c "
                '"from cryptography.fernet import Fernet; '
                "print(Fernet.generate_key().decode())\""
            )
        self._master_key = self._normalise(master_key)
        self._fernet = None

    @staticmethod
    def _normalise(master_key):
        raw = master_key.encode() if isinstance(master_key, str) else master_key
        # Accept either a Fernet key (44-char urlsafe b64 of 32 bytes) or raw
        # 32 bytes of base64, so a key generated either way works.
        try:
            decoded = base64.urlsafe_b64decode(raw)
        except (ValueError, TypeError) as exc:
            raise ValueError(
                "KMS_LOCAL_MASTER_KEY is not valid urlsafe base64."
            ) from exc
        if len(decoded) == 32:
            return raw
        raise ValueError(
            "KMS_LOCAL_MASTER_KEY must be a urlsafe-base64 encoding of 32 bytes."
        )

    @property
    def fernet(self):
        if self._fernet is None:
            from cryptography.fernet import Fernet

            self._fernet = Fernet(self._master_key)
        return self._fernet

    def generate_data_key(self):
        plaintext = os.urandom(32)
        return DataKey(plaintext=plaintext, wrapped=self.fernet.encrypt(plaintext))

    def unwrap_data_key(self, wrapped):
        from cryptography.fernet import InvalidToken

        try:
            return self.fernet.decrypt(wrapped)
        except InvalidToken as exc:
            raise EnvelopeError(
                "Could not unwrap the data key. The master key does not match "
                "the one this ciphertext was created with."
            ) from exc
