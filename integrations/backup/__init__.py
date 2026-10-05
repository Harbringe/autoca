"""Database backups in S3.

The nightly job (deploy/backup.sh) and the restore drill call the small tool in :mod:`.s3`. It lives under
``integrations/`` because it is the only code that talks to S3 and CloudWatch for this purpose, and the
adapter boundary (see integrations/tests/test_adapter_swap.py) keeps vendor SDKs in here.
"""
