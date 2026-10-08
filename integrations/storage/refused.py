"""A storage adapter that refuses everything, for a server on a PC that is wired to the live database (config/settings/live.py).

Live rows point at files in the server's bucket. A PC that wrote a file elsewhere would leave a document row whose evidence
exists on one laptop only, and a PC that read the bucket would need the server's credentials. So neither is allowed: pages
that need a file fail with this message, and nothing is written.
"""

from __future__ import annotations

from .base import StorageAdapter

MESSAGE = "Files are not available when the app runs on a PC against the live database. Use the live site to upload or open a file."


class RefusedStorageAdapter(StorageAdapter):
    def __init__(self, **_ignored):
        pass

    def put(self, key, data, content_type="application/octet-stream"):
        raise PermissionError(MESSAGE)

    def get(self, key):
        raise PermissionError(MESSAGE)

    def delete(self, key):
        raise PermissionError(MESSAGE)

    def exists(self, key):
        raise PermissionError(MESSAGE)

    def presigned_url(self, key, expires_in=300):
        raise PermissionError(MESSAGE)
