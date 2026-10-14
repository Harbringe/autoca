from classify.engine import BARE_NAME_CONFIDENCE, is_bare_name
from classify.treatment import HIGH_CONFIDENCE, REVIEW_ADVISED


def test_a_one_word_payee_is_a_bare_name():
    assert is_bare_name("ashok")
    assert not is_bare_name("ashok kumar")
    assert not is_bare_name("7eleven")


def test_a_rule_learned_from_a_bare_name_only_suggests():
    assert REVIEW_ADVISED <= BARE_NAME_CONFIDENCE < HIGH_CONFIDENCE
