"""A statement read from page images is trusted only if it proves out, like any other."""

from __future__ import annotations

import datetime
import json

import pytest

from banking import scan
from banking.parsers.base import BalanceChainError, StatementParseError
from integrations.llm.base import LLMResponse, LLMUnavailable
from integrations.pdf.base import PdfDocument, PdfPage

HEADER = {
    "statement_type": "bank",
    "bank_name": "Test Bank",
    "account_number": "1000 0000 0001",
    "account_holder": "TEST TRADERS",
    "ifsc": "TEST0000001",
    "period_start": "01-04-2025",
    "period_end": "30-04-2025",
    "opening_balance": "1,000.00",
    "closing_balance": "1,750.00",
}
ROWS = [
    {
        "date": "02-04-2025",
        "narration": "UPI/SHOP",
        "debit": "",
        "credit": "1,000.00",
        "balance": "2,000.00",
    },
    {
        "date": "05-04-2025",
        "narration": "RENT",
        "debit": "250.00",
        "credit": "",
        "balance": "1,750.00",
    },
]


def reply(**over):
    return {**HEADER, "transactions": ROWS, **over}


def text_page(n, text="x"):
    return PdfPage(page_number=n, text=text)


class FakeVision:
    """Answers each call with the next reply and remembers what it was sent."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def complete_json_with_images(self, system, user, images, *, max_tokens=4096):
        self.calls.append((user, len(images)))
        return LLMResponse(text=json.dumps(self.replies.pop(0)), model="fake")


@pytest.fixture(autouse=True)
def drawn_pages(monkeypatch, settings):
    settings.VISION_PAGES_PER_CALL = 3
    monkeypatch.setattr(scan, "render_pages", lambda data, dpi=None: [b"png"] * 3)


def document(pages=3):
    return PdfDocument(
        engine="fixture",
        page_count=pages,
        pages=tuple(PdfPage(page_number=i + 1) for i in range(pages)),
    )


def test_a_page_with_no_text_calls_for_vision_and_a_full_text_document_does_not():
    assert scan.needs_vision(document())
    full = PdfDocument(engine="f", page_count=2, pages=(text_page(1), text_page(2)))
    assert not scan.needs_vision(full)
    partial = PdfDocument(engine="f", page_count=2, pages=(text_page(1), PdfPage(page_number=2)))
    assert scan.needs_vision(partial)


def test_a_scan_that_adds_up_is_read(settings):
    settings.VISION_PAGES_PER_CALL = 2
    parsed = scan.read_statement(
        b"pdf", document(), FakeVision(reply(transactions=ROWS[:1]), reply(transactions=ROWS[1:]))
    )

    assert len(parsed) == 2
    assert parsed.account_number == "100000000001" and parsed.ifsc == "TEST0000001"
    assert parsed.opening_balance_paise == 100000 and parsed.closing_balance_paise == 175000
    assert parsed.period_start == datetime.date(2025, 4, 1)


def test_the_pages_go_in_groups_and_later_groups_say_they_continue(settings):
    settings.VISION_PAGES_PER_CALL = 2
    vision = FakeVision(reply(transactions=ROWS[:1]), {"transactions": ROWS[1:]})
    scan.read_statement(b"pdf", document(), vision)

    assert [n for _, n in vision.calls] == [2, 1]
    assert "continuing" not in vision.calls[0][0] and "continuing" in vision.calls[1][0]


def test_one_misread_digit_breaks_the_chain_and_nothing_is_accepted():
    wrong = [ROWS[0], {**ROWS[1], "balance": "1,570.00"}]

    with pytest.raises(BalanceChainError) as refused:
        scan.read_statement(b"pdf", document(), FakeVision(reply(transactions=wrong)))

    assert "does not add up" in str(refused.value)


def test_a_row_missing_its_balance_refuses_the_whole_scan():
    rows = [ROWS[0], {**ROWS[1], "balance": ""}]

    with pytest.raises(StatementParseError) as refused:
        scan.read_statement(b"pdf", document(), FakeVision(reply(transactions=rows)))

    assert "1 row(s)" in str(refused.value)


def test_an_unreadable_account_number_is_refused_not_guessed():
    with pytest.raises(StatementParseError, match="account number"):
        scan.read_statement(b"pdf", document(), FakeVision(reply(account_number="")))


def test_the_opening_balance_is_worked_back_from_the_first_row_when_not_printed():
    parsed = scan.read_statement(
        b"pdf", document(), FakeVision(reply(opening_balance="", closing_balance=""))
    )

    assert parsed.opening_balance_paise == 100000 and parsed.closing_balance_paise == 175000


def test_a_loan_or_card_scan_is_not_read_as_a_bank_account():
    with pytest.raises(StatementParseError, match="card"):
        scan.read_statement(b"pdf", document(), FakeVision(reply(statement_type="card")))


def test_a_provider_that_cannot_read_images_says_so_in_plain_words():
    class Blind:
        def complete_json_with_images(self, *args, **kwargs):
            raise LLMUnavailable("no model")

    with pytest.raises(StatementParseError, match="not set up"):
        scan.read_statement(b"pdf", document(), Blind())


def test_a_reply_that_is_not_json_is_refused():
    class Garbled:
        def complete_json_with_images(self, *args, **kwargs):
            return LLMResponse(text="not json", model="m")

    with pytest.raises(StatementParseError, match="understandable"):
        scan.read_statement(b"pdf", document(), Garbled())


def test_a_real_pdf_is_drawn_one_png_per_page(monkeypatch):
    import io

    import pypdfium2 as pdfium

    monkeypatch.undo()  # the autouse stand-in for drawing is only for the tests above
    pdf = pdfium.PdfDocument.new()
    pdf.new_page(300, 400)
    pdf.new_page(300, 400)
    buffer = io.BytesIO()
    pdf.save(buffer)
    pdf.close()

    images = scan.render_pages(buffer.getvalue(), dpi=72)

    assert len(images) == 2 and all(i.startswith(b"\x89PNG") for i in images)
