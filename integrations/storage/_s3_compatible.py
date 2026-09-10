"""Shared S3-protocol implementation.

Cloudflare R2 and AWS S3 differ, for our purposes, in exactly two values: the
endpoint URL and the region. Keeping the protocol code here means the R2 and S3
adapters are thin, and that the "swap" we are paying for architecturally is
visibly a swap rather than a parallel implementation.

``boto3`` is imported here and nowhere else outside ``integrations/``.
"""

from __future__ import annotations

from .base import StorageAdapter, StoredObject


class S3CompatibleStorageAdapter(StorageAdapter):
    #: Subclasses set this so error messages name the real service.
    service_label = "S3-compatible"

    def __init__(
        self,
        bucket=None,
        endpoint_url=None,
        region=None,
        access_key_id=None,
        secret_access_key=None,
        **_ignored,
    ):
        if not bucket:
            raise ValueError(f"{self.service_label}: a bucket name is required.")
        self.bucket = bucket
        self.endpoint_url = endpoint_url
        self.region = region or "auto"
        self._access_key_id = access_key_id
        self._secret_access_key = secret_access_key
        self._client = None

    @property
    def client(self):
        # Lazy: importing boto3 and building a client at settings-load time
        # would make every management command pay for it, and would make the
        # adapter unimportable in environments without credentials.
        if self._client is None:
            import boto3
            from botocore.config import Config

            self._client = boto3.client(
                "s3",
                endpoint_url=self.endpoint_url,
                region_name=self.region,
                aws_access_key_id=self._access_key_id,
                aws_secret_access_key=self._secret_access_key,
                config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
            )
        return self._client

    def put(self, key, data, content_type="application/octet-stream"):
        self.client.put_object(
            Bucket=self.bucket, Key=key, Body=data, ContentType=content_type
        )
        return StoredObject(key=key, size=len(data), content_type=content_type)

    def get(self, key):
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        return response["Body"].read()

    def delete(self, key):
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def exists(self, key):
        from botocore.exceptions import ClientError

        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise
        return True

    def presigned_url(self, key, expires_in=300):
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires_in,
        )
