"""Object storage interface.

Dev:  Cloudflare R2  (10GB, 1M writes / 10M reads per month, zero egress)
Beta: AWS S3

Both speak the S3 API, which is why this interface is shaped the way it is --
the beta adapter is a credentials-and-endpoint change, not a rewrite. Resist any
temptation to expose R2- or S3-specific concepts (storage classes, bucket
policies, multipart handles) through this interface; the moment one leaks, the
swap stops being free.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass


@dataclass(frozen=True)
class StoredObject:
    key: str
    size: int
    content_type: str


class StorageAdapter(abc.ABC):
    """Content-addressed blob storage, scoped by caller-supplied key prefix.

    Keys are always built by ``tenant_key()`` so a firm's objects live under a
    path segment that includes its firm id. Storage is a second isolation
    boundary that RLS does not cover -- the database will not stop code from
    reading the wrong bucket key, so the key convention has to.
    """

    @staticmethod
    def tenant_key(firm_id, *parts: str) -> str:
        """Build a firm-prefixed object key.

        Every write goes through this. A key that does not start with a firm id
        is a bug, and ``verify_tenant_key`` will say so.
        """
        cleaned = [str(p).strip("/") for p in parts if str(p).strip("/")]
        return "/".join(["firms", str(firm_id), *cleaned])

    @staticmethod
    def verify_tenant_key(key: str, firm_id) -> str:
        prefix = f"firms/{firm_id}/"
        if not key.startswith(prefix):
            raise PermissionError(
                f"Object key {key!r} is outside firm {firm_id}'s prefix. Refusing."
            )
        return key

    @abc.abstractmethod
    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> StoredObject:
        ...

    @abc.abstractmethod
    def get(self, key: str) -> bytes:
        ...

    @abc.abstractmethod
    def delete(self, key: str) -> None:
        ...

    @abc.abstractmethod
    def exists(self, key: str) -> bool:
        ...

    @abc.abstractmethod
    def presigned_url(self, key: str, expires_in: int = 300) -> str:
        """Short-lived read URL. Keep ``expires_in`` small; these are bearer tokens."""

    @property
    def name(self) -> str:
        return type(self).__name__
