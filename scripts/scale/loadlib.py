"""Pure helpers for the scale kit's load, upload and assistant tests. No Django, no network, so they can be tested anywhere.

* ``Stats``: latency samples per request name, with the table the tests print.
* ``encode_multipart``: a multipart/form-data body for a file upload, with the standard library only.
* ``make_statement_pdf``: a synthetic multi-page bank statement in the layout of an e-statement that prints its columns as one block
  per page (so it is read by word position), with made-up names and figures, a valid running balance and a printed summary.
"""

from __future__ import annotations

import datetime
import http.client
import math
import random
import threading
import time
import uuid
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# latency statistics
# ---------------------------------------------------------------------------


def percentile(values: list[float], p: float) -> float:
    """The p-th percentile (0-100) by the nearest-rank method; 0 for no samples."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, math.ceil(p / 100 * len(ordered)))
    return ordered[rank - 1]


class Stats:
    """Latency in milliseconds and the status of every request, kept per request name."""

    def __init__(self) -> None:
        self.ms: dict[str, list[float]] = {}
        self.status: dict[str, dict[str, int]] = {}

    def record(self, name: str, ms: float, status: int | str) -> None:
        self.ms.setdefault(name, []).append(ms)
        bucket = self.status.setdefault(name, {})
        bucket[str(status)] = bucket.get(str(status), 0) + 1

    def count(self, name: str | None = None) -> int:
        if name is not None:
            return len(self.ms.get(name, []))
        return sum(len(v) for v in self.ms.values())

    def failures(self, name: str | None = None) -> int:
        """Requests that did not get a 2xx or 3xx answer (a refused connection counts, as status ``error``)."""
        names = [name] if name is not None else list(self.status)
        bad = 0
        for n in names:
            for status, count in self.status.get(n, {}).items():
                if not (status.isdigit() and 200 <= int(status) < 400):
                    bad += count
        return bad

    def all_ms(self) -> list[float]:
        return [x for v in self.ms.values() for x in v]

    def table(self, seconds: float) -> str:
        head = f"{'request':<34}{'n':>6}{'err':>5}{'p50 ms':>9}{'p95 ms':>9}{'p99 ms':>9}{'max ms':>9}"
        lines = [head, "-" * len(head)]
        for name in sorted(self.ms, key=lambda n: -percentile(self.ms[n], 95)):
            v = self.ms[name]
            lines.append(
                f"{name:<34}{len(v):>6}{self.failures(name):>5}{percentile(v, 50):>9.0f}{percentile(v, 95):>9.0f}"
                f"{percentile(v, 99):>9.0f}{max(v):>9.0f}"
            )
        total = self.count()
        every = self.all_ms()
        lines.append("-" * len(head))
        lines.append(
            f"{'ALL':<34}{total:>6}{self.failures():>5}{percentile(every, 50):>9.0f}{percentile(every, 95):>9.0f}"
            f"{percentile(every, 99):>9.0f}{max(every) if every else 0:>9.0f}"
        )
        if seconds > 0:
            lines.append(f"throughput: {total / seconds:.1f} requests/s over {seconds:.0f}s")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# multipart
# ---------------------------------------------------------------------------


def encode_multipart(fields: dict[str, str], files: list[tuple[str, str, bytes, str]]) -> tuple[bytes, str]:
    """``(body, content_type)`` for a form with text ``fields`` and ``files`` of ``(field, filename, data, content_type)``."""
    boundary = "----scale" + uuid.uuid4().hex
    out = bytearray()
    for key, value in fields.items():
        out += f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode()
    for name, filename, data, content_type in files:
        out += (
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode()
        out += data + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={boundary}"


# ---------------------------------------------------------------------------
# a synthetic statement
# ---------------------------------------------------------------------------

_GLYPH = {**{str(d): 0.556 for d in range(10)}, ",": 0.278, ".": 0.278, "-": 0.333}
FONT_SIZE = 7.0
PAGE_HEIGHT = 842.0
HEADER_TOP = 233.6
STEP = 17.2

#: Each is one unbroken token, as the real layout prints them, and short enough to stay left of the reference column.
NARRATIONS = [
    "UPI-{n}-{r}@YBL-{ref}",
    "NEFTCR-SBIN0020054-{n}TRADERS-{ref}",
    "CASHDEPOSITBY-SELF-TESTVILLE-{ref}",
    "FT-{ref}-{n}FERTILIZERSLTD",
    "ATWDL-TESTVILLE-{ref}",
]
NAMES = ["ASHA", "RAVI", "MEERA", "KARTIK", "SUNITA", "VIKRAM", "LATA", "NILESH"]


def _width(text: str) -> float:
    return sum(_GLYPH.get(c, 0.556) for c in text) * FONT_SIZE


def _money(paise: int) -> str:
    sign = "-" if paise < 0 else ""
    whole, frac = divmod(abs(paise), 100)
    return f"{sign}{whole:,}.{frac:02d}"


def _esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


class _Page:
    def __init__(self) -> None:
        self.ops: list[str] = []

    def text(self, x: float, top: float, text: str) -> None:
        self.ops.append(f"BT /F1 {FONT_SIZE} Tf {x:.2f} {PAGE_HEIGHT - top:.2f} Td ({_esc(text)}) Tj ET")

    def right(self, edge: float, top: float, text: str) -> None:
        self.text(edge - _width(text), top, text)


def _assemble(pages: list[_Page]) -> bytes:
    """A PDF 1.4 file: one Helvetica font and a content stream per page."""
    objects: list[bytes] = []

    def add(body: str | bytes) -> int:
        objects.append(body if isinstance(body, bytes) else body.encode("latin-1"))
        return len(objects)

    catalog = add("")  # filled in below once the page ids are known
    tree = add("")
    font = add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    page_ids = []
    for page in pages:
        stream = "\n".join(page.ops).encode("latin-1")
        content = add(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        page_ids.append(
            add(
                f"<< /Type /Page /Parent {tree} 0 R /MediaBox [0 0 595 {int(PAGE_HEIGHT)}] "
                f"/Resources << /Font << /F1 {font} 0 R >> >> /Contents {content} 0 R >>"
            )
        )
    objects[catalog - 1] = f"<< /Type /Catalog /Pages {tree} 0 R >>".encode()
    kids = " ".join(f"{i} 0 R" for i in page_ids)
    objects[tree - 1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode()

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root {catalog} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def make_statement_pdf(
    *, pages: int = 40, rows_per_page: int = 11, account_number: str | None = None, seed: int = 1
) -> tuple[bytes, dict]:
    """A synthetic overdraft statement. Returns ``(pdf_bytes, facts)`` with the figures it prints, for checking a read against.

    Names, narrations and amounts are invented. The balance is negative throughout (an overdraft) and every row's balance follows
    from the one before, so the statement proves itself the way a real one does.
    """
    rng = random.Random(seed)  # noqa: S311 -- fake data, not secrets
    account_number = account_number or f"5020{rng.randrange(10**10):010d}"
    start, end = datetime.date(2025, 4, 1), datetime.date(2026, 3, 31)
    total_rows = pages * rows_per_page
    span = (end - start).days
    opening = balance = -rng.randrange(10_000_000, 90_000_000) * 100
    drs = crs = debits = credits = 0

    rows = []
    for i in range(total_rows):
        day = start + datetime.timedelta(days=span * i // max(1, total_rows - 1))
        amount = rng.randrange(500, 3_000_000)  # paise
        debit = rng.random() < 0.4
        balance += -amount if debit else amount
        if debit:
            drs, debits = drs + 1, debits + amount
        else:
            crs, credits = crs + 1, credits + amount
        ref = f"{rng.randrange(10**12):012d}"
        narration = rng.choice(NARRATIONS).format(n=rng.choice(NAMES), r=rng.randrange(10**9), ref=ref)
        rows.append((day, narration, ref, debit, amount, balance, rng.random() < 0.5))

    out_pages: list[_Page] = []
    per = rows_per_page
    for number in range(pages):
        page = _Page()
        page.text(34, 100, "Statementofaccount")
        page.text(34, 120, "AccountBranch : TESTVILLE")
        page.text(34, 140, "M/S. SCALE TEST TRADERS")
        page.text(34, 160, f"AccountNo : {account_number} OTHER")
        page.text(34, 180, "RTGS/NEFTIFSC: SCAL0001234")
        page.text(34, 215.5, f"StatementFrom : {start:%d/%m/%Y} To : {end:%d/%m/%Y}")
        for x, label in (
            (40, "Date"), (144, "Narration"), (284, "Chq./Ref.No."), (362, "ValueDt"),
            (405, "WithdrawalAmt."), (491, "DepositAmt."), (564, "ClosingBalance"),
        ):
            page.text(x, HEADER_TOP, label)
        top = HEADER_TOP + STEP
        for day, narration, ref, debit, amount, bal, wraps in rows[number * per : (number + 1) * per]:
            stamp = f"{day:%d/%m/%y}"
            page.text(34, top, stamp)
            page.text(68, top, narration)
            page.text(293, top, ref)
            page.text(362, top, stamp)
            page.right(470 if debit else 548, top, _money(amount))
            page.right(627, top, _money(bal))
            top += STEP
            if wraps:
                page.text(68, top, "PAYMENTFROMPHONE")
                top += STEP
        if number == pages - 1:
            top += STEP
            page.text(68, top, "STATEMENTSUMMARY :-")
            page.text(132, top + STEP, "OpeningBalance")
            for x, label in ((290, "DrCount"), (361, "CrCount"), (425, "Debits"), (501, "Credits"), (572, "ClosingBal")):
                page.text(x, top + STEP, label)
            page.text(137, top + 2 * STEP, _money(opening))
            for x, value in ((300, str(drs)), (369, str(crs)), (411, _money(debits)), (489, _money(credits)), (567, _money(balance))):
                page.text(x, top + 2 * STEP, value)
        out_pages.append(page)

    facts = {
        "account_number": account_number,
        "rows": total_rows,
        "debits": drs,
        "credits": crs,
        "total_debit_paise": debits,
        "total_credit_paise": credits,
        "opening_paise": opening,
        "closing_paise": balance,
        "pages": pages,
    }
    return _assemble(out_pages), facts


# ---------------------------------------------------------------------------
# simulated users
# ---------------------------------------------------------------------------

@dataclass
class SimUser:
    """One simulated person: their session cookie and the clients (ids) they work on."""

    cookie: str
    clients: list[str]
    csrf: str = ""
    name: str = "user"
    extra: dict = field(default_factory=dict)


def _headers(user: SimUser, host_header: str, write: bool = False) -> dict[str, str]:
    cookie = f"sessionid={user.cookie}" + (f"; csrftoken={user.csrf}" if user.csrf else "")
    headers = {"Host": host_header, "X-Forwarded-Proto": "https", "Cookie": cookie, "Accept": "application/json"}
    if write:
        headers["X-CSRFToken"] = user.csrf
        headers["Origin"] = f"https://{host_header}"
        headers["Referer"] = f"https://{host_header}/"
    return headers


def timed_request(
    conn_holder: list, host: str, port: int, host_header: str, user: SimUser, method: str, path: str,
    body: bytes | None = None, content_type: str | None = None, timeout: float = 120.0,
) -> tuple[int | str, float, bytes]:
    """One request on the user's own keep-alive connection, whole response read. ``(status, ms, body)``; status is ``error`` if
    the connection failed (the connection is then rebuilt for the next request)."""
    headers = _headers(user, host_header, write=method != "GET")
    if content_type:
        headers["Content-Type"] = content_type
    started = time.perf_counter()
    try:
        if not conn_holder:
            conn_holder.append(http.client.HTTPConnection(host, port, timeout=timeout))
        conn = conn_holder[0]
        conn.request(method, path, body=body, headers=headers)
        response = conn.getresponse()
        data = response.read()
        return response.status, (time.perf_counter() - started) * 1000, data
    except (OSError, http.client.HTTPException):
        for conn in conn_holder:
            try:
                conn.close()
            except OSError:
                pass
        conn_holder.clear()
        return "error", (time.perf_counter() - started) * 1000, b""


def run_phase(
    *, host: str, port: int, host_header: str, users: list[SimUser], mix: list[tuple[int, str, str]], seconds: float,
    think: tuple[float, float] = (1.0, 4.0), stats: Stats | None = None, seed: int = 7,
) -> Stats:
    """Every user works at once for ``seconds``: pick a request from ``mix`` (weight, name, path template with ``{c}`` for one of
    their clients), wait for the answer, think, repeat."""
    stats = stats or Stats()
    deadline = time.monotonic() + seconds
    weights = [w for w, _n, _p in mix]
    lock = threading.Lock()

    def worker(index: int, user: SimUser) -> None:
        rng = random.Random(seed + index)  # noqa: S311
        holder: list = []
        time.sleep(rng.uniform(0, min(2.0, think[1])))  # people do not all click on the same tick
        while time.monotonic() < deadline:
            _w, name, template = rng.choices(mix, weights=weights)[0]
            path = template.format(c=rng.choice(user.clients) if user.clients else "")
            status, ms, _body = timed_request(holder, host, port, host_header, user, "GET", path)
            with lock:
                stats.record(name, ms, status)
            time.sleep(rng.uniform(*think))
        for conn in holder:
            conn.close()

    threads = [threading.Thread(target=worker, args=(i, u), daemon=True) for i, u in enumerate(users)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=seconds + 180)
    return stats
