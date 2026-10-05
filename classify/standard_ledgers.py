"""Conventional ledger names a model should reach for before inventing one.

Not seeded into any client. These are the names a proposal is steered towards,
so two clients proposing a rent ledger both get "Rent" rather than "Rent Paid"
and "Office Rent A/c". The client's own names still win -- imported from their Tally company, or renamed by a CA
on acceptance when they use a different spelling.
"""

from classify.models import LedgerGroup

G = LedgerGroup

STANDARD_LEDGERS: list[tuple[str, str]] = [
    ("Rent", G.INDIRECT_EXPENSE),
    ("Salaries", G.INDIRECT_EXPENSE),
    ("Wages", G.DIRECT_EXPENSE),
    ("Electricity Charges", G.INDIRECT_EXPENSE),
    ("Telephone & Internet", G.INDIRECT_EXPENSE),
    ("Office Expenses", G.INDIRECT_EXPENSE),
    ("Printing & Stationery", G.INDIRECT_EXPENSE),
    ("Postage & Courier", G.INDIRECT_EXPENSE),
    ("Travelling Expenses", G.INDIRECT_EXPENSE),
    ("Conveyance", G.INDIRECT_EXPENSE),
    ("Fuel Expenses", G.INDIRECT_EXPENSE),
    ("Vehicle Running & Maintenance", G.INDIRECT_EXPENSE),
    ("Repairs & Maintenance", G.INDIRECT_EXPENSE),
    ("Staff Welfare", G.INDIRECT_EXPENSE),
    ("Business Promotion", G.INDIRECT_EXPENSE),
    ("Advertisement", G.INDIRECT_EXPENSE),
    ("Professional Fees", G.INDIRECT_EXPENSE),
    ("Audit Fees", G.INDIRECT_EXPENSE),
    ("Legal Expenses", G.INDIRECT_EXPENSE),
    ("Insurance", G.INDIRECT_EXPENSE),
    ("Software & Subscriptions", G.INDIRECT_EXPENSE),
    ("Membership & Subscription", G.INDIRECT_EXPENSE),
    ("Donations", G.INDIRECT_EXPENSE),
    ("Interest Paid", G.INDIRECT_EXPENSE),
    ("Loan Processing Charges", G.INDIRECT_EXPENSE),
    ("Freight & Cartage", G.DIRECT_EXPENSE),
    ("Purchases", G.DIRECT_EXPENSE),
    ("Sales", G.DIRECT_INCOME),
    ("Service Income", G.DIRECT_INCOME),
    ("Commission Received", G.INDIRECT_INCOME),
    ("Rent Received", G.INDIRECT_INCOME),
    ("Interest Received", G.INDIRECT_INCOME),
    ("Dividend Received", G.INDIRECT_INCOME),
    ("Cashback Received", G.INDIRECT_INCOME),
    ("Discount Received", G.INDIRECT_INCOME),
    ("Miscellaneous Income", G.INDIRECT_INCOME),
    ("GST Paid", G.DUTIES_AND_TAXES),
    ("TDS Payable", G.DUTIES_AND_TAXES),
    # The GST set a purchase or sales voucher posts to (ledger.billing). "GST Paid" above stays for books that
    # already use it.
    ("Input CGST", G.DUTIES_AND_TAXES),
    ("Input SGST", G.DUTIES_AND_TAXES),
    ("Input IGST", G.DUTIES_AND_TAXES),
    ("Output CGST", G.DUTIES_AND_TAXES),
    ("Output SGST", G.DUTIES_AND_TAXES),
    ("Output IGST", G.DUTIES_AND_TAXES),
    ("Input GST (RCM)", G.DUTIES_AND_TAXES),
    ("GST Payable (RCM)", G.DUTIES_AND_TAXES),
    ("TDS Receivable", G.CURRENT_ASSET),
    ("Round Off", G.INDIRECT_EXPENSE),
    ("Advance Tax", G.DUTIES_AND_TAXES),
    ("Professional Tax", G.DUTIES_AND_TAXES),
    ("Income Tax", G.CAPITAL),
    ("Drawings", G.CAPITAL),
    ("Capital Introduced", G.CAPITAL),
    ("Investments - Shares & Mutual Funds", G.INVESTMENT),
    ("Fixed Deposits", G.INVESTMENT),
    ("Credit Card Payable", G.CREDITOR),
    ("Unsecured Loans", G.LOAN),
    ("Secured Loans", G.LOAN),
    ("Sundry Debtors", G.DEBTOR),
    ("Sundry Creditors", G.CREDITOR),
]

#: Groups a model may propose into. Bank and cash ledgers come from statements;
#: Suspense is a seed.
PROPOSABLE_GROUPS = {
    value for value, _ in LedgerGroup.choices
} - {LedgerGroup.BANK, LedgerGroup.CASH, LedgerGroup.SUSPENSE}
