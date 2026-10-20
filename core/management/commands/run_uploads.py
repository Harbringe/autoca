"""The reader: takes statement uploads waiting in the queue and reads them, so the web app never has to.

Runs as its own container next to the web app (``worker`` in compose.prod.yaml), the same image and settings as ``assistant``. Each
loop looks at the queue, takes back jobs whose reader stopped, and runs the next waiting job (see ``core.jobqueue`` for how a job is
claimed, kept on a lease and finished). One job at a time unless ``--concurrency`` says otherwise: the server has two CPUs, and reading
a long statement uses one of them for the better part of a minute.

``--check`` is the container's health check: it exits 0 only if some reader has looked at the queue recently, which a process stuck
waiting on the database does not do. Stop the reader with Ctrl-C or SIGTERM; it finishes the job it is on first.
"""

from __future__ import annotations

import logging
import os
import signal
import socket
import threading
import time

from django.core.management.base import BaseCommand
from django.db import connections

from core import jobqueue

logger = logging.getLogger("autoca.jobqueue")


class Command(BaseCommand):
    help = "Read the statement uploads waiting in the queue."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="One pass, then exit (for tests and checks).")
        parser.add_argument("--check", action="store_true", help="Exit 0 if a reader has looked at the queue in the last two minutes, 1 if not.")
        parser.add_argument("--idle", type=float, default=2.0, help="Seconds between looks while nothing is waiting.")
        parser.add_argument("--concurrency", type=int, default=1, help="Jobs read at once.")

    def handle(self, *args, once=False, check=False, idle=2.0, concurrency=1, **options):
        import banking.upload_jobs  # noqa: F401 -- registers the statement reader

        if check:
            status = jobqueue.worker_status()
            self.stdout.write(f"queue poll {status['poll_age']}s ago, last job heartbeat {status['beat_age']}s ago, job {status['current']}")
            raise SystemExit(0 if jobqueue.reader_running() else 1)

        stopping = threading.Event()

        def stop(*_):
            stopping.set()

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        host = f"{socket.gethostname()}:{os.getpid()}"

        def loop(number: int) -> None:
            worker_id = f"{host}:{number}"
            try:
                while not stopping.is_set():
                    try:
                        outcome = jobqueue.run_once(worker_id)
                    except Exception:  # never let one bad pass end the reader
                        logger.exception("reader pass failed")
                        outcome = None
                        time.sleep(15)
                    if once:
                        return
                    if outcome is None:
                        stopping.wait(idle)
            finally:
                connections.close_all()

        if concurrency <= 1:
            loop(1)
            return
        threads = [threading.Thread(target=loop, args=(n + 1,), name=f"reader-{n + 1}") for n in range(concurrency)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
