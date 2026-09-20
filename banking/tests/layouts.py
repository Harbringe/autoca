"""Statement layouts from banks other than the one we have a real file for.

Each is a table shaped the way that bank shapes it -- column order, header
wording, date format, and how direction is carried. The figures are invented;
the *shape* is the thing under test, because the shape is what the column
inference has to cope with without being told.

Between them they cover every arrangement seen in Indian retail banking:

* separate Withdrawal/Deposit columns, in either order
* separate Debit/Credit columns with extra columns interleaved
* one Amount column with a Dr/Cr flag beside it
* no header row at all, which some net-banking exports produce

If a fifth arrangement turns up, add it here first. A layout that is in this
file and failing is a bug report; a layout that is only in a customer's inbox
is a support ticket.
"""

from __future__ import annotations

from integrations.pdf.base import PdfDocument, PdfPage


def document(text: str, table: list[list[str]]) -> PdfDocument:
    return PdfDocument(
        engine="layout-fixture",
        page_count=1,
        pages=(PdfPage(page_number=1, text=text, tables=(tuple(tuple(r) for r in table),)),),
    )


# ---------------------------------------------------------------------------
# HDFC: Withdrawal before Deposit, a second "value date" column, dd/mm/yy
# ---------------------------------------------------------------------------

HDFC_TEXT = """HDFC BANK LTD
Statement of account
Account No : 50100123456789
IFSC : HDFC0000123
From : 01/04/2025 To : 30/04/2025
"""

HDFC_TABLE = [
    ["Date", "Narration", "Chq/Ref No", "Value Dt", "Withdrawal Amt.", "Deposit Amt.", "Closing Balance"],
    ["01/04/25", "OPENING BALANCE", "", "", "", "", "25,000.00"],
    ["03/04/25", "UPI-SWIGGY-9876543210", "000000123456", "03/04/25", "450.00", "", "24,550.00"],
    ["07/04/25", "NEFT CR-SBIN0001234-ACME PVT LTD", "N123456789", "07/04/25", "", "1,20,000.00", "1,44,550.00"],
    ["12/04/25", "ATW-4321-CASH WDL", "", "12/04/25", "10,000.00", "", "1,34,550.00"],
    ["19/04/25", "EMI 1234567 HOUSING LOAN", "", "19/04/25", "32,450.50", "", "1,02,099.50"],
    ["28/04/25", "INT.PD:01-04-2025 to 28-04-2025", "", "28/04/25", "", "612.25", "1,02,711.75"],
    ["30/04/25", "CLOSING BALANCE", "", "", "", "", "1,02,711.75"],
]


# ---------------------------------------------------------------------------
# ICICI: a serial number first, "(INR)" suffixes, two date columns
# ---------------------------------------------------------------------------

ICICI_TEXT = """ICICI Bank Limited
Detailed Statement
Account Number: 004501234567
IFSC Code: ICIC0000045
Statement period from 01-04-2025 to 30-04-2025
"""

ICICI_TABLE = [
    ["S No.", "Value Date", "Transaction Date", "Cheque Number", "Transaction Remarks",
     "Withdrawal Amount (INR)", "Deposit Amount (INR)", "Balance (INR)"],
    ["1", "01-04-2025", "01-04-2025", "", "B/F", "", "", "8,450.00"],
    ["2", "04-04-2025", "04-04-2025", "", "UPI/410123456789/Payment to BigBasket", "2,340.00", "", "6,110.00"],
    ["3", "09-04-2025", "09-04-2025", "456123", "CHQ PAID - SELF", "5,000.00", "", "1,110.00"],
    ["4", "15-04-2025", "15-04-2025", "", "SALARY CREDIT APR 2025", "", "85,000.00", "86,110.00"],
    ["5", "22-04-2025", "22-04-2025", "", "ACH D- LIC OF INDIA", "4,782.00", "", "81,328.00"],
    ["6", "29-04-2025", "29-04-2025", "", "NEFT/AXIS/RENT APR", "22,000.00", "", "59,328.00"],
]


# ---------------------------------------------------------------------------
# Kotak: one Amount column with a separate Dr/Cr flag
# ---------------------------------------------------------------------------

KOTAK_TEXT = """Kotak Mahindra Bank
Account Statement
A/c No. 1234567890
IFSC: KKBK0000123
Period: 01-Apr-2025 to 30-Apr-2025
"""

KOTAK_TABLE = [
    ["Sl. No.", "Date", "Description", "Chq / Ref No", "Amount", "Dr / Cr", "Balance"],
    ["1", "02-Apr-2025", "Opening Balance", "", "", "", "1,05,000.00"],
    ["2", "05-Apr-2025", "MB:FT to RAJESH KUMAR", "MB0012345", "15,000.00", "Dr", "90,000.00"],
    ["3", "11-Apr-2025", "IMPS/P2A/510312345678/REFUND", "IMPS9988", "2,500.00", "Cr", "92,500.00"],
    ["4", "18-Apr-2025", "POS 123456 RELIANCE RETAIL", "", "3,299.00", "Dr", "89,201.00"],
    ["5", "25-Apr-2025", "Dividend - TCS LTD", "", "1,840.00", "Cr", "91,041.00"],
    ["6", "30-Apr-2025", "Closing Balance", "", "", "", "91,041.00"],
]


# ---------------------------------------------------------------------------
# SBI: Debit and Credit, no header row at all (a net-banking CSV-style export)
# ---------------------------------------------------------------------------

SBI_TEXT = """STATE BANK OF INDIA
Account Statement
Account No. 30123456789
IFSC: SBIN0001234
From 01-04-2025 to 30-04-2025
"""

SBI_TABLE = [
    ["01-04-2025", "01-04-2025", "BY TRANSFER-UPI/CR/500001/ARJUN", "", "", "3,500.00", "48,200.00"],
    ["06-04-2025", "06-04-2025", "TO TRANSFER-UPI/DR/512999/JIO RECHARGE", "", "799.00", "", "47,401.00"],
    ["14-04-2025", "14-04-2025", "ATM WDL-SBI ATM MG ROAD", "", "6,000.00", "", "41,401.00"],
    ["21-04-2025", "21-04-2025", "BY SALARY-APRIL 2025", "", "", "62,500.00", "1,03,901.00"],
    ["27-04-2025", "27-04-2025", "TO TRANSFER-INB ELECTRICITY BILL", "", "2,145.50", "", "1,01,755.50"],
]


LAYOUTS = {
    "hdfc": (HDFC_TEXT, HDFC_TABLE),
    "icici": (ICICI_TEXT, ICICI_TABLE),
    "kotak": (KOTAK_TEXT, KOTAK_TABLE),
    "sbi": (SBI_TEXT, SBI_TABLE),
}


def layout(name: str) -> PdfDocument:
    text, table = LAYOUTS[name]
    return document(text, table)
