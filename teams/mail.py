"""Invitations by email. Off unless the platform is set up for it (see ``INVITE_EMAIL_ENABLED`` in the settings).

The link in the email is the same single-use link the person would otherwise be given by hand. It is never logged: the text goes to
the mail backend and nowhere else, and a failure is reported without it.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger("autoca.mail")

#: Backends that would put the message (and so the link) in a log or discard it; they never count as "sent".
_NOT_REAL = ("dummy", "console", "locmem", "filebased")


def enabled() -> bool:
    return bool(settings.INVITE_EMAIL_ENABLED) and not any(word in settings.EMAIL_BACKEND for word in _NOT_REAL)


def render(*, firm_name: str, inviter: str, role: str, url: str, expires_days: int) -> tuple[str, str]:
    subject = f"{inviter} invited you to {firm_name}"
    body = (
        f"{inviter} has invited you to join {firm_name} as {role}.\n\n"
        f"Open this link to set up your sign-in:\n{url}\n\n"
        f"The link works once and lasts {expires_days} days. If you were not expecting this, ignore this email.\n"
    )
    return subject, body


def send_invite(*, to: str, firm_name: str, inviter: str, role: str, url: str, expires_days: int) -> bool:
    """Email the invitation. True only if a real backend accepted it; any failure is logged without the link and returns False."""
    if not enabled():
        return False
    subject, body = render(firm_name=firm_name, inviter=inviter, role=role, url=url, expires_days=expires_days)
    try:
        return send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [to], fail_silently=False) == 1
    except Exception:  # noqa: BLE001 -- a mail problem must never block making the invitation
        logger.warning("invitation email could not be sent")
        return False
