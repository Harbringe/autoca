"""Cloudflare R2 storage adapter -- the development-tier backend.

Free tier: 10GB stored, 1M writes and 10M reads per month, and no egress fees.
The zero-egress part is the reason to prefer it over S3 during development:
pulling test documents back down repeatedly costs nothing.

Requires STORAGE_ENDPOINT_URL of the form
https://<account-id>.r2.cloudflarestorage.com and STORAGE_REGION=auto.
"""

from ._s3_compatible import S3CompatibleStorageAdapter


class R2StorageAdapter(S3CompatibleStorageAdapter):
    service_label = "Cloudflare R2"

    def __init__(self, **options):
        options.setdefault("region", "auto")
        if not options.get("endpoint_url"):
            raise ValueError(
                "Cloudflare R2 requires STORAGE_ENDPOINT_URL "
                "(https://<account-id>.r2.cloudflarestorage.com)."
            )
        super().__init__(**options)
