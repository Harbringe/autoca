"""AWS S3 storage adapter -- the beta-tier backend.

This file is the whole cost of moving object storage from Cloudflare R2 to AWS.
Switch by setting:

    STORAGE_BACKEND=integrations.storage.s3.S3StorageAdapter
    STORAGE_REGION=ap-south-1
    STORAGE_ENDPOINT_URL=          (unset -- boto3 resolves the AWS endpoint)

No code outside this directory changes. That property is asserted by
integrations/tests/test_adapter_swap.py.
"""

from ._s3_compatible import S3CompatibleStorageAdapter


class S3StorageAdapter(S3CompatibleStorageAdapter):
    service_label = "AWS S3"

    def __init__(self, **options):
        # Unlike R2, S3 resolves its own endpoint from the region.
        options["endpoint_url"] = options.get("endpoint_url") or None
        if not options.get("region") or options["region"] == "auto":
            raise ValueError("AWS S3 requires a real STORAGE_REGION, e.g. ap-south-1.")
        super().__init__(**options)
