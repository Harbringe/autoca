"""Settings for the automated test suite.

The suite MUST run against a real PostgreSQL. Row-level security is the entire
tenant-isolation boundary, and no other engine can enforce or even express it,
so a SQLite fallback would let un-isolated code pass CI silently. There is
deliberately no fallback here.

In CI this points at an ephemeral Postgres service container (see
.github/workflows/ci.yml), not at the shared Supabase dev project.
"""

from .base import *  # noqa: F401,F403
from .base import DATABASES, env_bool

DEBUG = False
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]

# WhiteNoise serves collected static files, which tests never build.
MIDDLEWARE = [m for m in MIDDLEWARE if "whitenoise" not in m]  # noqa: F405
STORAGES = {  # noqa: F405
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

if not env_bool("DATABASE_SSL_REQUIRE", False):
    for alias in DATABASES:
        DATABASES[alias].setdefault("OPTIONS", {}).pop("sslmode", None)

for _alias in DATABASES:
    if DATABASES[_alias]["ENGINE"] != "django.db.backends.postgresql":
        raise RuntimeError(
            "The test suite requires PostgreSQL. Row-level security is the "
            "tenant isolation boundary and cannot be tested on any other engine."
        )

# Fast, deterministic hashing in tests. argon2id is still exercised directly by
# core/tests/test_auth.py so the production hasher stays covered.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

CELERY_TASK_ALWAYS_EAGER = True

# A fixed dev master key so envelope-encryption round-trips are reproducible.
INTEGRATION_OPTIONS["kms"]["master_key"] = (  # noqa: F405
    "dGVzdC1vbmx5LW1hc3Rlci1rZXktMzItYnl0ZXMtISE="
)
INTEGRATIONS["storage"] = "integrations.storage.local.LocalStorageAdapter"  # noqa: F405
INTEGRATIONS["queue"] = "integrations.queue.eager.EagerQueueAdapter"  # noqa: F405
