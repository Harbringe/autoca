"""Drop the leftover Django test database on a pooled Postgres.

Only needed when the test database is hosted behind a connection pooler such as
Supabase's Supavisor. The pooler keeps a warm connection to the scratch database
and re-opens it between a ``pg_terminate_backend`` and the ``DROP``, so the
obvious sequence loses the race and the next test run fails with
"database test_postgres already exists".

Setting ``ALLOW_CONNECTIONS false`` first closes that gap.

    .venv/Scripts/python.exe scripts/drop_test_db.py

For day-to-day work prefer ``pytest --reuse-db``, which never creates or drops
the database at all. Reach for this after a schema change, or after an aborted
run has left the database half-migrated. CI does not need it: the service
container has no pooler in front of it.
"""

from __future__ import annotations

import os
import pathlib
import sys
import time

import dj_database_url
import psycopg
from dotenv import load_dotenv

REPO = pathlib.Path(__file__).resolve().parent.parent


def main() -> int:
    load_dotenv(REPO / ".env.test", override=True)

    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL is not set in .env.test", file=sys.stderr)
        return 2

    cfg = dj_database_url.parse(url)
    target = f"test_{cfg['NAME']}"
    params = {
        "host": cfg["HOST"],
        "port": cfg["PORT"] or 5432,
        "user": cfg["USER"],
        "password": cfg["PASSWORD"],
        "dbname": cfg["NAME"],
        "sslmode": "require" if os.environ.get("DATABASE_SSL_REQUIRE", "1") != "0" else "prefer",
        "connect_timeout": 30,
    }

    with psycopg.connect(**params) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", [target])
            if cur.fetchone() is None:
                print(f"{target} does not exist; nothing to do")
                return 0

            cur.execute(f'ALTER DATABASE "{target}" WITH ALLOW_CONNECTIONS false')
            cur.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                [target],
            )
            print(f"blocked new connections, terminated {len(cur.fetchall())} session(s)")

            for attempt in range(6):
                try:
                    cur.execute(f'DROP DATABASE "{target}"')
                    print(f"dropped {target}")
                    return 0
                except psycopg.Error as exc:
                    print(f"  attempt {attempt + 1}: {str(exc).splitlines()[0]}")
                    time.sleep(4)

    print(f"could not drop {target}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
