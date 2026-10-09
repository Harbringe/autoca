"""The cash flow statement agrees with the balance sheet whenever the books balance. Pure arithmetic: no database."""

import random

from ledger.nce_cashflow import cash_flow

ASSET_LINES = ("NCA.PPE", "NCA.INTANG", "NCA.CWIP", "NCA.INV", "NCA.LOANS", "NCA.OTH", "CA.INV", "CA.STOCK", "CA.REC", "CA.LOANS", "CA.OTH")
LIABILITY_LINES = ("NCL.BORR", "NCL.OTH", "NCL.PROV", "CL.BORR", "CL.PAY", "CL.OTH", "CL.PROV")


def _year(rng, owners):
    """Line totals for one year that balance: cash is whatever makes assets equal liabilities plus owners' funds."""
    totals = {c: rng.randint(0, 5_000_000) for c in ASSET_LINES + LIABILITY_LINES}
    cash = sum(totals[c] for c in LIABILITY_LINES) + owners - sum(totals[c] for c in ASSET_LINES)
    totals["CA.CASH"] = cash
    return totals


def test_a_balanced_pair_of_years_leaves_nothing_unexplained():
    for seed in range(200):
        rng = random.Random(seed)  # noqa: S311 -- test data, not a secret
        owners_prev = rng.randint(10_000_000, 50_000_000)
        pbt = rng.randint(-2_000_000, 8_000_000)
        tax = max(0, rng.randint(-100_000, 1_000_000))
        net = pbt - tax
        injected = rng.randint(-3_000_000, 3_000_000)
        owners_cur = owners_prev + net + injected
        prev, cur = _year(rng, owners_prev), _year(rng, owners_cur)
        cur["PL.DEP"], cur["PL.FIN"], cur["PL.TAXC"] = rng.randint(0, 900_000), rng.randint(0, 600_000), tax
        interest = rng.randint(0, 400_000)

        flow = cash_flow(cur, prev, profit_before_tax=pbt, net_profit=net, interest_income=interest, owners_funds_cur=owners_cur, owners_funds_prev=owners_prev)

        assert flow.unexplained_paise == 0, seed
        assert flow.opening_paise == prev["CA.CASH"] and flow.closing_paise == cur["CA.CASH"]
        assert flow.operating_paise + flow.investing_paise + flow.financing_paise == cur["CA.CASH"] - prev["CA.CASH"]
        assert not any(r.key == "N.diff" for r in flow.rows)


def test_capital_introduced_is_the_change_in_owners_funds_other_than_the_profit():
    flow = cash_flow(
        {"CA.CASH": 1_000}, {"CA.CASH": 0}, profit_before_tax=0, net_profit=0, interest_income=0, owners_funds_cur=700, owners_funds_prev=0
    )
    capital = next(r for r in flow.rows if r.key == "C.cap")
    assert capital.paise == 700


def test_interest_is_moved_from_operating_to_investing():
    cur = {"CA.CASH": 120}
    flow = cash_flow(cur, {}, profit_before_tax=100, net_profit=100, interest_income=20, owners_funds_cur=100, owners_funds_prev=0)
    by_key = {r.key: r.paise for r in flow.rows}
    assert by_key["A.int"] == -20 and by_key["B.int"] == 20
    assert by_key["A.op"] == 80 and flow.investing_paise == 20


def test_a_difference_the_books_cannot_explain_is_shown_not_hidden():
    flow = cash_flow({"CA.CASH": 500}, {}, profit_before_tax=100, net_profit=100, interest_income=0, owners_funds_cur=100, owners_funds_prev=0)
    assert flow.unexplained_paise == 400
    assert next(r for r in flow.rows if r.key == "N.diff").paise == 400


def test_first_year_starts_from_nothing():
    flow = cash_flow({"CA.CASH": 100, "CA.REC": 50, "CL.PAY": 30, "EQ.CAP": 120}, {}, profit_before_tax=0, net_profit=0, interest_income=0, owners_funds_cur=120, owners_funds_prev=0)
    assert flow.opening_paise == 0 and flow.unexplained_paise == 0
