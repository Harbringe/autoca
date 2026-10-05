"""Synthetic people and clients for the CA reviewer (web/qa).

Creates one firm that is plainly fake -- "QA Associates (synthetic)" -- with a
firm administrator, a Senior CA and a staff member, and three clients arranged so
that each role sees something different. Nothing here resembles a real client or
a real person, so a reviewer (human or agent) can click through every screen
without touching anyone's data.

    python scripts/qa_seed.py            # create, or reuse the firm from last time
    python scripts/qa_seed.py --reset    # put the clients back to the three seeded ones
    python scripts/qa_seed.py --teardown # try to remove the firm, its people and clients

The audit trail is append-only by design (Indian company law), so once the firm has
team events -- and seeding creates some -- the database refuses to delete the firm.
`--teardown` therefore cannot always succeed; `--reset` is what to use between review
rounds, and the firm itself stays as a clearly-labelled synthetic tenant.

The dev database is shared, so this leaves a marker file (web/qa/.qa-firm) naming
the firm it made, and `--teardown` only ever removes that firm.

The password below is for these throwaway accounts only. Never reuse it.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

import django  # noqa: E402

django.setup()

from django_otp.plugins.otp_totp.models import TOTPDevice  # noqa: E402

from core.db.session import firm_context  # noqa: E402
from core.models import Client, Firm, FirmMembership, Role, User  # noqa: E402
from core.provisioning import create_client, create_firm, create_user  # noqa: E402
from teams import service  # noqa: E402

MARKER = ROOT / "web" / "qa" / ".qa-firm"
PASSWORD = "qa-synthetic-Passw0rd-2026"  # noqa: S105
FIRM_NAME = "QA Associates (synthetic)"

PEOPLE = [
    # key, email, name, role
    ("admin", "qa.admin@autoca.test", "Anita Admin", Role.FIRM_ADMIN),
    ("senior", "qa.senior@autoca.test", "Sanjay Senior", Role.SENIOR_CA),
    ("staff", "qa.staff@autoca.test", "Sunita Staff", Role.STAFF),
    ("reader", "qa.reader@autoca.test", "Rohan Reader", Role.READ_ONLY),
    # Only for the second-factor journey (web/qa/journeys/mfa.mjs): its authenticator
    # enrolment is reset on every seed, so the other three are never affected by it.
    ("mfa", "qa.mfa@autoca.test", "Mona Authenticator", Role.STAFF),
]


def seed() -> dict:
    firm_id = json.loads(MARKER.read_text())["firm"] if MARKER.exists() else None
    firm = create_firm(FIRM_NAME, firm_id=firm_id) if not firm_id else _existing(firm_id)
    MARKER.parent.mkdir(parents=True, exist_ok=True)
    MARKER.write_text(json.dumps({"firm": str(firm.pk)}))

    members: dict[str, FirmMembership] = {}
    with firm_context(firm.pk):
        for key, email, name, role in PEOPLE:
            user = User.objects.filter(email=email).first() or create_user(email, PASSWORD, name)
            user.set_password(PASSWORD)
            user.save()
            member, _ = FirmMembership.objects.get_or_create(
                firm=firm, user=user, defaults={"role": role}
            )
            member.role = role
            member.is_active = True
            member.is_owner = key == "admin"
            member.scope_all_clients = key == "admin"
            member.save()
            members[key] = member
            if key == "mfa":
                TOTPDevice.objects.filter(user=user).delete()
        members["senior"].manager = members["admin"]
        members["senior"].save(update_fields=["manager"])
        members["staff"].manager = members["senior"]
        members["staff"].save(update_fields=["manager"])

        fy = datetime.date(2025, 4, 1)
        clients = {}
        for name in ("QA Sharma Traders", "QA Gupta Exports", "QA Patel & Sons"):
            clients[name] = Client.objects.filter(name=name).first() or create_client(firm, name, fy)

        admin = members["admin"]
        service.set_lead(admin, clients["QA Sharma Traders"], members["senior"])
        service.set_lead(admin, clients["QA Gupta Exports"], members["senior"])
        service.assign(admin, clients["QA Sharma Traders"], members["staff"])
        service.assign(admin, clients["QA Sharma Traders"], members["mfa"])
        service.assign(admin, clients["QA Sharma Traders"], members["reader"])
        # Patel has no lead and no staff: the admin sees it, the others do not.

    return {"firm": str(firm.pk), "password": PASSWORD, "people": {k: e for k, e, _, _ in PEOPLE}}


def _existing(firm_id):
    with firm_context(firm_id):
        firm = Firm.objects.filter(pk=firm_id).first()
    return firm or create_firm(FIRM_NAME, firm_id=firm_id)


def reset() -> None:
    """Remove every client a reviewer added, keeping the three seeded ones."""
    firm_id = json.loads(MARKER.read_text())["firm"]
    # The statement-review client holds posted books, which are permanent; it is never reset.
    keep = ("QA Sharma Traders", "QA Gupta Exports", "QA Patel & Sons", "QA Statement Review")
    removed = kept = 0
    with firm_context(firm_id):
        for client in Client.objects.exclude(name__in=keep):
            try:
                client.delete()
                removed += 1
            except Exception:  # posted books or their audit trail refuse it, on purpose
                kept += 1
    print(f"Removed {removed} extra client(s); {kept} could not be removed (they hold posted books).")


def teardown() -> None:
    if not MARKER.exists():
        print("Nothing to remove: no marker file.")
        return
    firm_id = json.loads(MARKER.read_text())["firm"]
    emails = [email for _, email, _, _ in PEOPLE]
    try:
        with firm_context(firm_id):
            Client.objects.all().delete()
            FirmMembership.objects.all().delete()
            Firm.objects.filter(pk=firm_id).delete()
    except Exception as error:  # the append-only audit trail refuses, on purpose
        print(f"Could not remove the firm: {str(error).splitlines()[0]}")
        print("Use --reset to clear reviewer-made clients; the synthetic firm stays.")
        return
    User.objects.filter(email__in=emails).delete()
    # People the invitation journey (web/qa/journeys/invite.mjs) created.
    User.objects.filter(email__startswith="qa.invited.").delete()
    MARKER.unlink()
    print(f"Removed {FIRM_NAME} and its people.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--teardown", action="store_true")
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()
    if args.teardown:
        teardown()
    elif args.reset:
        reset()
    else:
        print(json.dumps(seed(), indent=2))
