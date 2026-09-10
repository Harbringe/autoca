"""AWS KMS adapter -- beta-tier placeholder.

Implementation is two calls: GenerateDataKey (KeySpec=AES_256) returns the
plaintext and the CiphertextBlob to store as `wrapped`; Decrypt turns a wrapped
blob back into plaintext. The envelope format in base.py does not change, so
ciphertext written by the local adapter stays readable after re-wrapping the
data keys -- plan a one-time rewrap rather than a decrypt-everything migration.

Set the KMS key's grant to allow only GenerateDataKey and Decrypt for the
application role. It never needs Encrypt.
"""

from .base import DataKey, KMSAdapter


class AWSKMSAdapter(KMSAdapter):
    def __init__(self, key_id=None, region=None, **_ignored):
        self.key_id = key_id
        self.region = region

    def generate_data_key(self) -> DataKey:
        raise NotImplementedError(
            "The AWS KMS adapter is a beta-phase placeholder. Implement with "
            "kms.generate_data_key(KeyId=self.key_id, KeySpec='AES_256')."
        )

    def unwrap_data_key(self, wrapped: bytes) -> bytes:
        raise NotImplementedError(
            "The AWS KMS adapter is a beta-phase placeholder. Implement with "
            "kms.decrypt(CiphertextBlob=wrapped, KeyId=self.key_id)."
        )
