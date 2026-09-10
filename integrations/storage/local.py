"""Filesystem storage adapter -- tests and offline development only.

Never select this in a deployed environment. It has no durability story and its
"presigned URL" is a file path, not a credential-bearing link.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path

from .base import StorageAdapter, StoredObject


class LocalStorageAdapter(StorageAdapter):
    def __init__(self, root=None, **_ignored):
        self.root = Path(root or ".devdata/storage").resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        # Resolve and confirm containment: a key containing ".." must not be
        # able to escape the storage root and read arbitrary files.
        candidate = (self.root / key).resolve()
        if not candidate.is_relative_to(self.root):
            raise PermissionError(f"Object key {key!r} escapes the storage root.")
        return candidate

    def put(self, key, data, content_type="application/octet-stream"):
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return StoredObject(key=key, size=len(data), content_type=content_type)

    def get(self, key):
        return self._path(key).read_bytes()

    def delete(self, key):
        path = self._path(key)
        if path.exists():
            path.unlink()

    def exists(self, key):
        return self._path(key).exists()

    def presigned_url(self, key, expires_in=300):
        guessed, _ = mimetypes.guess_type(key)
        del guessed, expires_in
        return self._path(key).as_uri()
