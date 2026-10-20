"""Concurrent users and big uploads against the scratch app (the ``web`` service of compose.scale.yaml), from the tool container.

    python /scale/load.py run --users 5,20,50 --seconds 60      # many people at once, in phases
    python /scale/load.py uploads --concurrency 2 --pages 238   # big statements uploaded at the same time

It signs in as people it creates in the scratch database (second factor included, through the session the app itself reads), so
nothing here can sign in anywhere else. It refuses to run against any database but the scratch one, and talks only to ``web:8000``.
Fake data only: the fill script's firms and clients, and statements made up by loadlib.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import string
import sys
import threading
import time
import uuid

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
django.setup()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import loadlib  # noqa: E402
from django.conf import settings  # noqa: E402
from django.test import Client as DjangoClient  # noqa: E402
from django_otp.plugins.otp_totp.models import TOTPDevice  # noqa: E402

from core.db.session import firm_context  # noqa: E402
from core.models import Client, FirmMembership, Role, User  # noqa: E402

NAMESPACE = uuid.UUID("5ca1e000-0000-4000-8000-000000000001")  # the fill script's
HOST_HEADER = "scale.invalid"
V1 = "/api/v1"

#: What a person does in a working session, weighted by how often (weight, name, path with {c} = one of their clients).
MIX = [
    (4, "GET me", f"{V1}/me/"),
    (4, "GET my work", f"{V1}/me/work/"),
    (6, "GET clients", f"{V1}/clients/"),
    (14, "GET review summary", f"{V1}/clients/{{c}}/review-queue/summary/"),
    (14, "GET review queue (page)", f"{V1}/clients/{{c}}/review-queue/?stage=unresolved&page_size=50"),
    (6, "GET review queue (500)", f"{V1}/clients/{{c}}/review-queue/?page_size=500"),
    (8, "GET statements", f"{V1}/clients/{{c}}/statements/?page_size=100"),
    (8, "GET ledgers", f"{V1}/clients/{{c}}/ledgers/?page_size=200"),
    (6, "GET parties", f"{V1}/clients/{{c}}/parties/?page_size=100"),
    (4, "GET bills", f"{V1}/clients/{{c}}/bills/?page_size=50"),
    (10, "GET trial balance", f"{V1}/clients/{{c}}/reports/trial-balance/?fy=2024"),
    (6, "GET profit and loss", f"{V1}/clients/{{c}}/reports/profit-and-loss/?fy=2024"),
    (6, "GET balance sheet", f"{V1}/clients/{{c}}/reports/balance-sheet/?fy=2024"),
]
P95_LIMIT_MS = 1500
ERROR_LIMIT = 0.01


def guard() -> None:
    db = settings.DATABASES["default"]
    if db["NAME"] != "autoca_scale_test" or db["HOST"] != "db":
        sys.exit(f"Refusing: this runs only against the scratch database autoca_scale_test on host 'db', not {db['NAME']} on {db['HOST']}.")


def make_users(firms: int, count: int) -> list[loadlib.SimUser]:
    """``count`` people spread over the filled firms, each with a signed-in session that has passed the second factor."""
    firm_ids = [uuid.uuid5(NAMESPACE, f"firm-{f}") for f in range(firms)]
    clients_of: dict = {}
    users = []
    for i in range(count):
        firm_id = firm_ids[i % firms]
        email = f"load-{i % firms}-{i}@scale.invalid"
        user = User.objects.filter(email=email).first() or User.objects.create_user(email=email, password=uuid.uuid4().hex)
        with firm_context(firm_id):
            FirmMembership.objects.get_or_create(firm_id=firm_id, user=user, defaults={"role": Role.SENIOR_CA})
            if firm_id not in clients_of:
                clients_of[firm_id] = [str(pk) for pk in Client.objects.values_list("pk", flat=True)]
        if not clients_of[firm_id]:
            sys.exit(f"Firm {firm_id} has no clients: run 'sh scale.sh fill' first (with the same --firms).")
        device, _ = TOTPDevice.objects.get_or_create(user=user, name="scale", confirmed=True)
        http = DjangoClient()
        http.force_login(user)
        session = http.session
        session["otp_device_id"] = device.persistent_id
        session.save()
        csrf = "".join(random.SystemRandom().choice(string.ascii_letters + string.digits) for _ in range(32))
        users.append(loadlib.SimUser(cookie=session.session_key, clients=clients_of[firm_id], csrf=csrf, name=email))
    return users


def target(args) -> tuple[str, int]:
    host, _, port = args.target.partition(":")
    return host, int(port or 8000)


def smoke(args, user: loadlib.SimUser, mix):
    """Ask once for every request in the mix; one the app answers with an error is reported and left out, so a wrong guess of a
    path or a parameter does not pass for slowness."""
    host, port = target(args)
    kept, holder = [], []
    for weight, name, template in mix:
        path = template.format(c=user.clients[0])
        status, ms, _ = loadlib.timed_request(holder, host, port, HOST_HEADER, user, "GET", path)
        if status == 200:
            kept.append((weight, name, template))
        else:
            print(f"  left out: {name} answered {status} ({path})")
    return kept


def cmd_run(args) -> int:
    guard()
    counts = [int(x) for x in args.users.split(",")]
    think = tuple(float(x) for x in args.think.split(","))
    print(f"signing in {max(counts)} simulated people (scratch database only)...", flush=True)
    users = make_users(args.firms, max(counts))
    host, port = target(args)
    mix = smoke(args, users[0], MIX)
    if not mix:
        print("Nothing in the mix worked: is the web service up (sh scale.sh web-up)?")
        return 2
    worst = 0
    for n in counts:
        print(f"\n== {n} people at once for {args.seconds}s (think time {think[0]}-{think[1]}s) ==", flush=True)
        started = time.monotonic()
        stats = loadlib.run_phase(
            host=host, port=port, host_header=HOST_HEADER, users=users[:n], mix=mix, seconds=args.seconds, think=think
        )
        took = time.monotonic() - started
        print(stats.table(took))
        every = stats.all_ms()
        p95 = loadlib.percentile(every, 95)
        errors = stats.failures() / max(1, stats.count())
        ok = p95 <= P95_LIMIT_MS and errors <= ERROR_LIMIT
        print(f"verdict: {'OK' if ok else 'TOO SLOW OR ERRORS'} (p95 {p95:.0f} ms, limit {P95_LIMIT_MS}; errors {errors:.1%}, limit {ERROR_LIMIT:.0%})")
        worst = max(worst, 0 if ok else 1)
        if not ok and args.stop_on_fail:
            print("stopping here: the next phase would only be worse.")
            break
    return worst


def cmd_uploads(args) -> int:
    guard()
    users = make_users(args.firms, args.concurrency)
    host, port = target(args)
    stats = loadlib.Stats()
    outcomes: list[str] = []
    lock = threading.Lock()
    print(f"making {args.concurrency * args.files} statements of {args.pages} pages ({args.pages * args.rows_per_page} rows each)...", flush=True)

    def worker(index: int, user: loadlib.SimUser) -> None:
        holder: list = []
        for k in range(args.files):
            seed = 1000 + index * 100 + k
            pdf, facts = loadlib.make_statement_pdf(pages=args.pages, rows_per_page=args.rows_per_page, seed=seed)
            body, content_type = loadlib.encode_multipart({}, [("file", f"scale-{seed}.pdf", pdf, "application/pdf")])
            client_id = user.clients[(index + k) % len(user.clients)]
            status, ms, data = loadlib.timed_request(
                holder, host, port, HOST_HEADER, user, "POST", f"{V1}/clients/{client_id}/statements/upload/", body, content_type, timeout=900
            )
            stats.record("POST upload", ms, status)
            note = f"{len(pdf) / 1e6:.1f} MB, {facts['rows']} rows -> HTTP {status} in {ms / 1000:.1f}s"
            if status in (200, 202):
                try:
                    job = json.loads(data)
                    result = job.get("result") or {}
                    note += f", job {job.get('status')}, rows saved {result.get('rows_created')}"
                    if job.get("status") != "SUCCEEDED" or result.get("rows_created") != facts["rows"]:
                        note += f"  <-- WRONG ({job.get('error_code') or job.get('error') or 'row count differs'})"
                        with lock:
                            stats.record("upload wrong result", ms, "wrong")
                except ValueError:
                    note += ", unreadable answer"
            with lock:
                outcomes.append(f"  user {index + 1} file {k + 1}: {note}")

    started = time.monotonic()
    threads = [threading.Thread(target=worker, args=(i, u)) for i, u in enumerate(users)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    took = time.monotonic() - started
    print("\n".join(sorted(outcomes)))
    print(stats.table(took))
    return 1 if stats.failures() else 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="web:8000", help="host:port of the scratch app")
    ap.add_argument("--firms", type=int, default=2, help="how many firms the fill made (the same --firms)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run")
    run.add_argument("--users", default="5,20,50", help="people at once, one phase for each")
    run.add_argument("--seconds", type=float, default=60)
    run.add_argument("--think", default="1,4", help="seconds a person waits between requests: low,high")
    run.add_argument("--stop-on-fail", action="store_true")
    up = sub.add_parser("uploads")
    up.add_argument("--concurrency", type=int, default=2, help="uploads at the same time")
    up.add_argument("--files", type=int, default=1, help="statements each person uploads, one after another")
    up.add_argument("--pages", type=int, default=238)
    up.add_argument("--rows-per-page", type=int, default=11)
    args = ap.parse_args()
    sys.exit(cmd_run(args) if args.cmd == "run" else cmd_uploads(args))


if __name__ == "__main__":
    main()
