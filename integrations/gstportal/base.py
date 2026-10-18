"""Reaching the GST portal as the taxpayer, through a GST Suvidha Provider.

The taxpayer enables API access on the portal, gives their portal username, and enters the OTP the portal sends them; the provider
then holds a session (a token valid some hours, renewable until the limit the taxpayer set). AutoCA keeps only that session token,
encrypted, and never the portal password. What this layer does today: start the sign-in, finish it, keep the session alive, and
download GSTR-2B. Filing would be added here, behind a person's confirmation.
"""

from __future__ import annotations

import abc
import datetime
from dataclasses import dataclass


class PortalError(RuntimeError):
    """The provider or the portal refused or could not be reached. The message is for a person."""


class PortalSessionExpired(PortalError):
    """The session is no longer valid: sign in again with a new OTP."""


class PortalNotReady(PortalError):
    """The portal has nothing to give for that month yet (GSTR-2B is not generated, or has no details)."""


@dataclass(frozen=True)
class PortalSession:
    token: str
    expires_at: datetime.datetime


class GstPortal(abc.ABC):
    @abc.abstractmethod
    def request_otp(self, gstin: str, username: str) -> None:
        """Ask the portal to send the taxpayer an OTP."""

    @abc.abstractmethod
    def verify_otp(self, gstin: str, username: str, otp: str) -> PortalSession: ...

    @abc.abstractmethod
    def refresh(self, token: str) -> PortalSession:
        """Extend a live session without the taxpayer. Raises ``PortalSessionExpired`` when it can no longer be."""

    @abc.abstractmethod
    def fetch_gstr2b(self, token: str, year: int, month: int) -> bytes:
        """The month's GSTR-2B as a JSON document in the portal's own shape (``{"data": {gstin, rtnprd, docdata...}}``)."""
