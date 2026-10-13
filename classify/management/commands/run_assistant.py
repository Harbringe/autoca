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
from concurrent.futures import ThreadPoolExecutor

from django.core.management.base import BaseCommand
from django.db import connection, connections

from classify.models import ModelState, TransactionClassification
from classify.queue import process_next_batch
from core.db.session import firm_context
from core.models import Client

logger = logging.getLogger("autoca.assistant")


def firm_ids() -> list:
    """Every active firm's id. The worker has no tenant until it enters one, and the platform admin's views are gated on a
    signed-in person (they return nothing here), so it asks a database function that hands out only the ids."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT t.id FROM app.active_firm_ids() AS t(id)")
        return [row[0] for row in cursor.fetchall()]


def clients_waiting(firm_id) -> list[Client]:
    with firm_context(firm_id):
        ids = set(
            TransactionClassification.objects.filter(
                ledger__isnull=True, model_state__in=[ModelState.WAITING, ModelState.CLAIMED]
            ).values_list("transaction__bank_account__client_id", flat=True)
        )
        return list(Client.objects.filter(pk__in=ids)) if ids else []


def _one_batch(client):
    """One batch on a worker thread, which has a database connection of its own and gives it back when done."""
    try:
        return process_next_batch(client)
    finally:
        connections.close_all()


def tick(parallel: int = 1) -> int:
    """One pass over every firm. Returns how many rows were read.

    ``parallel`` batches are read at once for each client with rows waiting: a call to the model takes ten seconds or more,
    so one at a time is the slowest way through a long statement. Several at once is what ``process_next_batch`` is built for
    (rows are claimed with ``SKIP LOCKED``, and a pause is firm-wide), so they take different rows and stop together on a pause.
    """
    waiting = [client for firm_id in firm_ids() for client in clients_waiting(firm_id)]
    if parallel <= 1:
        read = 0
        paused_firms = set()
        for client in waiting:
            if client.firm_id in paused_firms:
                continue  # the pause is per firm; the rest of its clients would only be told the same
            outcome = process_next_batch(client)
            read += outcome.processed
            if outcome.state == "paused" or outcome.reason == "assistant_off":
                paused_firms.add(client.firm_id)
        return read

    read = 0
    with ThreadPoolExecutor(max_workers=parallel) as pool:
        jobs = [pool.submit(_one_batch, client) for client in waiting for _ in range(parallel)]
        for job in jobs:
            try:
                read += job.result().processed
            except Exception:  # one failed batch must not lose the others' count or end the pass
                logger.exception("assistant batch failed")
    return read


class Command(BaseCommand):
    help = "Read the rows waiting for the assistant, for every client, until stopped."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Make one pass and exit.")
        parser.add_argument("--idle", type=float, default=8.0, help="Seconds between passes when nothing was read.")
        parser.add_argument("--busy", type=float, default=1.0, help="Seconds between passes while rows are being read.")
        parser.add_argument("--parallel", type=int, default=4, help="Batches read at once for a client with rows waiting.")

    def handle(self, *args, once=False, idle=8.0, busy=1.0, parallel=4, **options):
        stopping = False

        def stop(*_):
            nonlocal stopping
            stopping = True

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        while not stopping:
            try:
                read = tick(parallel)
            except Exception:  # never let one bad pass end the worker
                logger.exception("assistant pass failed")
                read = 0
                time.sleep(15)
            if once:
                return
            time.sleep(busy if read else idle)
