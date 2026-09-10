"""Keep the Supabase free-tier project from pausing.

Free projects pause after 7 days with no activity and need a manual resume from
the dashboard -- which, if it happens the morning of a demo, is a bad morning.
A trivial query resets the clock.

Run it on a schedule (GitHub Actions cron, or Render's free cron) every couple
of days. Uses DATABASE_OWNER_URL because the pooler is not the thing that needs
keeping awake.
"""

import os
import sys

import psycopg


def main() -> int:
    url = os.environ.get("DATABASE_OWNER_URL") or os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_OWNER_URL / DATABASE_URL not set", file=sys.stderr)
        return 2
    try:
        with psycopg.connect(url, connect_timeout=30) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT now()")
                print(f"supabase awake at {cur.fetchone()[0]}")
    except Exception as exc:  # noqa: BLE001 - this is a monitoring script
        print(f"keepalive failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
