"""The EPFO ECR text file for a month, from the PF working, for a person to upload on the EPFO unified portal.

One line per member, fields separated by ``#~#``: UAN, member name, gross wages, EPF wages, EPS wages, EDLI wages, EPF contribution (the
member's 12%), EPS contribution (8.33% of the pension wages), the employer's EPF share (the rest of its contribution), days without pay and
refund of advances. Amounts are whole rupees. A member without a UAN cannot be put in the file, so the file is refused and they are named.
Days without pay and refunds are not in the books and go in as zero. The portal's own check runs when it is uploaded.
"""

from __future__ import annotations

from ledger import pf_esi

SEPARATOR = "#~#"


class EcrError(ValueError):
    """The file cannot be made; the message names what to put right."""


def _rupees(paise: int) -> int:
    return round(paise / 100)


def build(client, year: int, month: int) -> str:
    work = pf_esi.build(client, year, month)
    if not work["has_run"]:
        raise EcrError("No salary run is booked for that month.")
    members = [r for r in work["rows"] if r["pf_employee_paise"] or r["pf_employer_paise"]]
    if not members:
        raise EcrError("Nobody has PF deducted in that month.")
    no_uan = [r["employee"] for r in members if not r["uan"]]
    if no_uan:
        raise EcrError("These members have no UAN on file: " + ", ".join(no_uan) + ".")
    lines = []
    for r in members:
        wages = r["pf_wages_paise"]
        eps_wages = min(wages, pf_esi.PF_WAGE_CEILING)
        lines.append(
            SEPARATOR.join(
                str(x)
                for x in (
                    r["uan"], " ".join(r["employee"].split()).upper(), _rupees(r["gross_paise"]), _rupees(wages), _rupees(eps_wages), _rupees(eps_wages),
                    _rupees(r["pf_employee_paise"]), _rupees(r["eps_paise"]), _rupees(r["epf_paise"]), 0, 0,
                )
            )
        )
    return "\n".join(lines) + "\n"
