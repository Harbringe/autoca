from classify.scoring import (
    Evidence,
    confidence,
    first_word_counts,
    name_specificity,
    verdict,
    wilson_lower,
)


def run(n, spec, base=0.0, agree=None):
    return confidence(Evidence(n if agree is None else agree, n, spec, base))


def test_more_agreeing_decisions_earn_more_trust():
    scores = [run(n, 0.5) for n in (1, 2, 4, 8, 16)]
    assert scores == sorted(scores) and scores[0] < scores[-1]


def test_a_common_first_name_needs_a_long_record_before_it_acts_alone():
    assert verdict(run(1, 0.1)) == "ask"
    assert verdict(run(5, 0.1)) == "suggest"
    assert verdict(run(12, 0.1)) == "place"


def test_a_specific_name_is_trusted_sooner_than_a_bare_one():
    assert run(1, 0.8) > run(1, 0.1)
    assert verdict(run(1, 0.8)) == "suggest"
    assert verdict(run(8, 1.0)) == "place"


def test_a_mixed_history_does_not_act_alone():
    assert verdict(run(6, 0.8, agree=4)) == "ask"
    assert run(6, 0.8, agree=5) < run(6, 0.8)


def test_a_ledger_most_rows_go_to_anyway_earns_less():
    assert run(3, 0.8, base=0.7) < run(3, 0.8, base=0.1)


def test_no_decisions_earn_nothing_from_history():
    assert wilson_lower(0, 0) == 0.0
    assert 0.0 <= confidence(Evidence(0, 0, 0.0)) <= 0.01


def test_specificity_depends_on_how_many_payees_share_the_first_word():
    payees = first_word_counts(["Abdul", "Abdul Khan", "ABDUL RAZAK", "Airtel"])
    assert payees["abdul"] == 3
    assert name_specificity("Abdul", payees) < name_specificity("Airtel", payees)
    assert name_specificity("Abdul Khan", payees) == 0.8
    assert name_specificity("Abdul", payees, has_gstin=True) == 1.0
