"""Root pytest configuration.

``banking.tests.support`` is loaded as a plugin so its fixtures -- chiefly
``fixture_adapters``, which points the pdf and storage adapters at a captured
statement and a temp directory -- are available to the classification suite as
well. The classification tests need real parsed rows to work on, and a second
copy of the same wiring would drift from this one.
"""

import time
import warnings

import psycopg
from psycopg import sql

pytest_plugins = ["banking.tests.support"]


def pytest_sessionstart(session):
    """Drop a test database left behind by the previous run, before Django looks.

    The dev/test Postgres sits behind Supabase's pooler, and a pooler keeps its
    own warm server sessions parked on whichever database a client last used.
    Django's end-of-run DROP therefore fails with "is being accessed by other
    users", the database survives, and the next run dies at setup with
    "already exists". Nothing a teardown fixture can do fixes it: terminating
    the pooler's sessions only makes it open fresh ones.

    So the drop happens at the *start* of the run instead, from a connection to
    the maintenance database, after terminating whatever is parked on the test
    one. ``--reuse-db`` (pytest.ini) then tells Django not to attempt its own
    drop at the end, which is the only part that was ever failing. The schema
    is still rebuilt from migrations on every run, because the database is.

    In CI the database is an ephemeral container and this is a no-op.
    """
    from django.conf import settings

    owner = settings.DATABASES["owner"]
    test_name = settings.DATABASES["default"].get("TEST", {}).get("NAME") or (
        "test_" + settings.DATABASES["default"]["NAME"]
    )
    params = {
        "host": owner["HOST"],
        "port": owner["PORT"] or 5432,
        "user": owner["USER"],
        "password": owner["PASSWORD"],
        "dbname": "postgres",
        **{k: v for k, v in owner.get("OPTIONS", {}).items() if k == "sslmode"},
    }
    try:
        with psycopg.connect(**params, autocommit=True) as conn:
            for _attempt in range(5):
                conn.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = %s AND pid <> pg_backend_pid()",
                    (test_name,),
                )
                try:
                    conn.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(test_name)))
                    return
                except psycopg.errors.ObjectInUse:
                    time.sleep(0.5)
    except psycopg.Error as exc:  # pragma: no cover - environment-specific
        warnings.warn(f"could not clear stale test database {test_name!r}: {exc}", stacklevel=1)


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_throttle_counts():
    """Throttle counts live in the cache, which outlives a test: one test's failed sign-ins must not lock the next out."""
    from django.core.cache import cache

    cache.clear()
    yield
