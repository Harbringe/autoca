"""GSTIN lookup interface.

One call: what does the GST portal say about this GSTIN. The answer informs a person; it never changes the books, and the books
never wait on it (a portal that is down or wrong must not stop booking). Which provider answers is a settings choice, as with the
model: a new provider is one file here and one line in settings.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass


class GstinLookupError(RuntimeError):
    """The provider could not be reached or gave nothing usable. Callers show the last answer, if any."""


class GstinLookupUnavailable(GstinLookupError):
    """No provider is configured."""


class GstinNotFound(GstinLookupError):
    """The portal has no record of this GSTIN."""


@dataclass(frozen=True)
class TaxpayerDetails:
    gstin: str
    legal_name: str = ""
    trade_name: str = ""
    #: The portal's wording, e.g. "Active", "Cancelled", "Suspended".
    status: str = ""
    registration_type: str = ""
    address: str = ""
    state: str = ""
    pincode: str = ""
    registered_on: str = ""
    cancelled_on: str = ""


class GstinVerifier(abc.ABC):
    @abc.abstractmethod
    def lookup(self, gstin: str) -> TaxpayerDetails:
        """Return the portal's details, or raise ``GstinNotFound`` / ``GstinLookupError``."""
