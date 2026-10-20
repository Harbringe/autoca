"""How fast the assistant worker gets through a big queue, with a fake model that answers at once.

    python /scale/assistant.py --rows 5000 --parallel 4

Marks up to --rows undecided rows (spread over the filled firms) as waiting, then runs the worker's own pass (``tick``) until the
queue is empty or --max-seconds is up, and says how many rows a second that was and how many went straight into the books.
Needs LLM_BACKEND=fake_llm.FakeLLMAdapter (scale.sh sets it) and refuses to run against any database but the scratch one.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import uuid

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
django.setup()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from django.conf import settings  # noqa: E402

from classify.management.commands.run_assistant import tick  # noqa: E402
from classify.models import ModelState, TransactionClassification  # noqa: E402
from classify.queue import mark_waiting  # noqa: E402
from core.db.session import firm_context  # noqa: E402
from integrations.registry import get_llm  # noqa: E402

NAMESPACE = uuid.UUID("5ca1e000-0000-4000-8000-000000000001")


def main() -> None:
    db = settings.DATABASES["default"]
    if db["NAME"] != "autoca_scale_test" or db["HOST"] != "db":
        sys.exit(f"Refusing: only the scratch database, not {db['NAME']} on {db['HOST']}.")
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=5000, help="undecided rows to queue for the assistant")
    ap.add_argument("--firms", type=int, default=2)
    ap.add_argument("--parallel", type=int, default=4, help="batches read at once for each client, as the worker runs")
    ap.add_argument("--max-seconds", type=float, default=900)
    args = ap.parse_args()
    if not get_llm().is_available:
        sys.exit("The fake model is not on: run through scale.sh (it sets LLM_BACKEND=fake_llm.FakeLLMAdapter).")

    per_firm = max(1, args.rows // args.firms)
    queued = 0
    for f in range(args.firms):
        firm_id = uuid.uuid5(NAMESPACE, f"firm-{f}")
        with firm_context(firm_id):
            ids = list(TransactionClassification.objects.filter(ledger__isnull=True).values_list("pk", flat=True)[:per_firm])
            queued += mark_waiting(TransactionClassification.objects.filter(pk__in=ids))
    print(f"queued {queued:,} rows for the assistant", flush=True)

    started = time.monotonic()
    read = passes = 0
    while time.monotonic() - started < args.max_seconds:
        got = tick(args.parallel)
        passes += 1
        read += got
        elapsed = time.monotonic() - started
        if passes % 5 == 0 or got == 0:
            print(f"  pass {passes}: {read:,} rows read in {elapsed:.0f}s ({read / max(elapsed, 1):.1f} rows/s)", flush=True)
        if got == 0:
            break
    elapsed = time.monotonic() - started

    done = declined = left = 0
    for f in range(args.firms):
        with firm_context(uuid.uuid5(NAMESPACE, f"firm-{f}")):
            done += TransactionClassification.objects.filter(model_state=ModelState.DONE).count()
            declined += TransactionClassification.objects.filter(model_state=ModelState.DECLINED).count()
            left += TransactionClassification.objects.filter(model_state__in=[ModelState.WAITING, ModelState.CLAIMED]).count()
    print(f"\nread {read:,} rows in {elapsed:.0f}s = {read / max(elapsed, 1):.1f} rows/s with {args.parallel} batches at once")
    print(f"database now: {done:,} done, {declined:,} declined, {left:,} still waiting")


if __name__ == "__main__":
    main()
