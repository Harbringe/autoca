"""The assistant as a background worker: reads waiting rows for every client without anyone having a page open.

Runs as its own container next to the web app (``assistant`` in compose.prod.yaml). Each pass looks at every firm for
clients with rows queued for the model and asks ``process_next_batch`` for one small batch per client, which is the very
call the browser used to make. That call is built for several callers at once (rows are claimed with ``SKIP LOCKED``, a
rate limit becomes a firm-wide pause kept in the shared cache), so the worker needs no coordination of its own. Auto-posting,
the three-tries rule and the pause behave exactly as before.

Idle, it looks again every ``--idle`` seconds; after a pass that read rows, ``--busy`` seconds. A firm that is paused (rate
limit, daily limit, provider down) is skipped until its pause is over. Stop it with Ctrl-C or SIGTERM.
"""

from __future__ import annotations

import logging
import signal
import time

from django.core.management.base import BaseCommand

from classify.models import ModelState, TransactionClassification
from classify.queue import process_next_batch
from core.db.session import firm_context
from core.models import Client

logger = logging.getLogger("autoca.assistant")


def firm_ids() -> list:
    """Every firm, from the platform's read-only view: the worker has no tenant until it enters one."""
    from superadmin.models import PlatformFirm

    return list(PlatformFirm.objects.filter(is_active=True).values_list("pk", flat=True))


def clients_waiting(firm_id) -> list[Client]:
    with firm_context(firm_id):
        ids = set(
            TransactionClassification.objects.filter(
                ledger__isnull=True, model_state__in=[ModelState.WAITING, ModelState.CLAIMED]
            ).values_list("transaction__bank_account__client_id", flat=True)
        )
        return list(Client.objects.filter(pk__in=ids)) if ids else []


def tick() -> int:
    """One pass over every firm. Returns how many rows were read."""
    read = 0
    for firm_id in firm_ids():
        for client in clients_waiting(firm_id):
            outcome = process_next_batch(client)
            read += outcome.processed
            if outcome.state == "paused" or outcome.reason == "assistant_off":
                break  # the pause is per firm; the rest of its clients would only be told the same
    return read


class Command(BaseCommand):
    help = "Read the rows waiting for the assistant, for every client, until stopped."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Make one pass and exit.")
        parser.add_argument("--idle", type=float, default=8.0, help="Seconds between passes when nothing was read.")
        parser.add_argument("--busy", type=float, default=1.0, help="Seconds between passes while rows are being read.")

    def handle(self, *args, once=False, idle=8.0, busy=1.0, **options):
        stopping = False

        def stop(*_):
            nonlocal stopping
            stopping = True

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        while not stopping:
            try:
                read = tick()
            except Exception:  # never let one bad pass end the worker
                logger.exception("assistant pass failed")
                read = 0
                time.sleep(15)
            if once:
                return
            time.sleep(busy if read else idle)
