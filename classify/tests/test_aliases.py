"""Names that reach the model: keyed, per client, and turned back only on our side. No database needed."""

from types import SimpleNamespace

from classify.llm import PARTY_ACCOUNT_LABEL, _Chart, _shown_ledger_name
from classify.pseudonymise import ledger_alias, person_alias

FIRM = "11111111-1111-1111-1111-111111111111"
ONE = SimpleNamespace(pk="aaaaaaaa-0000-0000-0000-000000000001", firm_id=FIRM)
TWO = SimpleNamespace(pk="aaaaaaaa-0000-0000-0000-000000000002", firm_id=FIRM)


def test_a_person_gets_the_same_token_every_time_for_one_client():
    a = person_alias("Suresh Kiran Menon", FIRM, ONE.pk)
    assert a == person_alias("SURESH KIRAN  MENON", FIRM, ONE.pk) and a.startswith("P") and len(a) == 9


def test_the_same_person_is_two_unrelated_tokens_for_two_clients():
    assert person_alias("Suresh Kiran Menon", FIRM, ONE.pk) != person_alias("Suresh Kiran Menon", FIRM, TWO.pk)


def test_a_token_is_not_a_plain_hash_of_the_name():
    import hashlib

    plain = "P" + hashlib.sha256(f"{FIRM}|person|SURESHKIRANMENON".encode()).hexdigest()[:8].upper()
    assert person_alias("Suresh Kiran Menon", FIRM) != plain


def test_a_loan_from_a_person_is_shown_as_a_token_and_a_plain_ledger_is_not():
    token = _shown_ledger_name("Loan from Ramesh Kumar", "LOAN", False, ONE)
    assert token == ledger_alias("Loan from Ramesh Kumar", FIRM, ONE.pk) and "Ramesh" not in token and token.startswith("L")
    assert _shown_ledger_name("Meena Devi Capital", "CAPITAL", False, ONE).startswith("L")
    # Ordinary headings are left alone: the person test errs towards "person" and would hide "Rent" and "Salaries".
    assert _shown_ledger_name("Rent", "INDIRECT_EXPENSE", False, ONE) == "Rent"
    assert _shown_ledger_name("HDFC Bank Term Loan", "LOAN", False, ONE) == "HDFC Bank Term Loan"
    # A party's own account is still hidden outright.
    assert _shown_ledger_name("Ravi Traders", "CREDITOR", False, ONE) == PARTY_ACCOUNT_LABEL


def test_the_model_names_a_loan_by_its_token_and_gets_the_real_ledger_back():
    loan = SimpleNamespace(name="Loan from Ramesh Kumar", group="LOAN", is_active=True, status="ACTIVE", is_party_account=False)
    rent = SimpleNamespace(name="Rent", group="INDIRECT_EXPENSE", is_active=True, status="ACTIVE", is_party_account=False)
    chart = _Chart(ONE, [loan, rent], "Axis Bank")
    chart.status = SimpleNamespace(ACTIVE="ACTIVE", PROPOSED="PROPOSED")

    assert chart.by_name(chart.shown(loan)) is loan
    assert chart.by_name("Rent") is rent
    # The real name of a hidden ledger is not something the model was given, so it is not accepted.
    assert chart.by_name("Loan from Ramesh Kumar") is None
