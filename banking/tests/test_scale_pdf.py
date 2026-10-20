"""The scale kit's helpers (scripts/scale/loadlib.py): latency statistics, multipart, and the synthetic statement PDF, which must
be read back by the real reader to exactly the figures it prints. No database."""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

from banking.parsers import PositionalStatementParser, detect_parser
from integrations.pdf.pdfplumber_text import PdfPlumberAdapter

_PATH = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "scale" / "loadlib.py"
_spec = importlib.util.spec_from_file_location("scale_loadlib", _PATH)
loadlib = importlib.util.module_from_spec(_spec)
sys.modules["scale_loadlib"] = loadlib  # a dataclass in the module looks itself up here
_spec.loader.exec_module(loadlib)


def test_the_synthetic_statement_reads_back_to_the_figures_it_prints():
    pdf, facts = loadlib.make_statement_pdf(pages=5, rows_per_page=9, seed=3)
    document = PdfPlumberAdapter().extract(pdf)
    parser = detect_parser(document)
    assert isinstance(parser, PositionalStatementParser)
    parsed = parser.parse(document)  # refuses unless the balance chain and the printed summary hold
    assert len(parsed) == facts["rows"] == 45
    assert (parsed.opening_balance_paise, parsed.closing_balance_paise) == (facts["opening_paise"], facts["closing_paise"])
    assert (parsed.total_debit_paise, parsed.total_credit_paise) == (facts["total_debit_paise"], facts["total_credit_paise"])
    assert parsed.account_number == facts["account_number"]


def test_two_seeds_make_two_different_accounts_and_the_same_seed_the_same_file():
    a, fa = loadlib.make_statement_pdf(pages=2, rows_per_page=5, seed=1)
    b, fb = loadlib.make_statement_pdf(pages=2, rows_per_page=5, seed=2)
    again, _ = loadlib.make_statement_pdf(pages=2, rows_per_page=5, seed=1)
    assert fa["account_number"] != fb["account_number"] and a != b and a == again


def test_percentiles_and_the_table():
    assert loadlib.percentile([], 95) == 0
    assert loadlib.percentile([10, 20, 30, 40, 50], 50) == 30
    assert loadlib.percentile([float(i) for i in range(1, 101)], 95) == 95
    stats = loadlib.Stats()
    for ms in (10, 20, 30):
        stats.record("GET /a", ms, 200)
    stats.record("GET /a", 900, 500)
    stats.record("GET /b", 5, "error")
    assert stats.count() == 5 and stats.count("GET /a") == 4
    assert stats.failures("GET /a") == 1 and stats.failures() == 2
    table = stats.table(10)
    assert "GET /a" in table and "ALL" in table and "requests/s" in table


def test_multipart_carries_the_file_and_the_fields():
    body, content_type = loadlib.encode_multipart({"allow_gap": "true"}, [("file", "s.pdf", b"%PDF-1.4 x", "application/pdf")])
    boundary = content_type.split("boundary=")[1]
    assert body.startswith(f"--{boundary}".encode()) and body.rstrip().endswith(f"--{boundary}--".encode())
    assert b'name="allow_gap"' in body and b'filename="s.pdf"' in body and b"%PDF-1.4 x" in body


@pytest.mark.parametrize("pages", [1, 3])
def test_a_one_page_statement_also_reads(pages):
    pdf, facts = loadlib.make_statement_pdf(pages=pages, rows_per_page=6, seed=5)
    document = PdfPlumberAdapter().extract(pdf)
    assert len(detect_parser(document).parse(document)) == facts["rows"]


def test_simulated_users_work_against_a_server_and_every_request_is_counted():
    import http.server
    import threading

    seen = {"cookies": set(), "paths": set()}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            seen["cookies"].add(self.headers.get("Cookie"))
            seen["paths"].add(self.path)
            body = b'{"ok": true}'
            self.send_response(404 if self.path.startswith("/missing") else 200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        users = [loadlib.SimUser(cookie=f"key{i}", clients=["c1", "c2"]) for i in range(4)]
        mix = [(3, "GET list", "/api/{c}/list"), (1, "GET missing", "/missing/{c}")]
        stats = loadlib.run_phase(
            host="127.0.0.1", port=server.server_address[1], host_header="scale.invalid", users=users, mix=mix, seconds=1.5,
            think=(0.05, 0.1),
        )
    finally:
        server.shutdown()
    assert stats.count() >= 20
    assert stats.failures("GET missing") == stats.count("GET missing") > 0  # a 404 is counted as a failure
    assert stats.failures("GET list") == 0
    assert seen["cookies"] == {f"sessionid=key{i}" for i in range(4)}  # each user sent their own session
    assert any(p.startswith("/api/c") for p in seen["paths"])
