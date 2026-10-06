"""Which settings Parameter Store may set, and that nothing dangerous slips through."""

from __future__ import annotations

from integrations import paramstore

PREFIX = "/autoca/prod/"


def p(name, value):
    return {"Name": PREFIX + name, "Value": value}


def test_a_managed_setting_is_returned_by_its_short_name():
    found, skipped = paramstore.settings_from([p("LLM_API_KEY", "sk-abc")], PREFIX)

    assert found == {"LLM_API_KEY": "sk-abc"} and skipped == []


def test_the_permanent_keys_and_database_passwords_can_never_be_set_from_here():
    parameters = [
        p("KMS_LOCAL_MASTER_KEY", "x"),
        p("BLIND_INDEX_KEY", "x"),
        p("DJANGO_SECRET_KEY", "x"),
        p("DATABASE_URL", "x"),
        p("POSTGRES_PASSWORD", "x"),
    ]

    found, skipped = paramstore.settings_from(parameters, PREFIX)

    assert found == {} and len(skipped) == 5


def test_a_value_with_a_line_break_is_refused_so_it_cannot_smuggle_in_a_second_setting():
    found, skipped = paramstore.settings_from(
        [p("LLM_API_KEY", "sk-abc\nDJANGO_SECRET_KEY=owned")], PREFIX
    )

    assert found == {} and "LLM_API_KEY" in skipped[0]
    assert "owned" not in " ".join(skipped)


def test_an_empty_value_is_left_out_not_written_over_a_working_setting():
    found, _ = paramstore.settings_from([p("LLM_API_KEY", "")], PREFIX)

    assert found == {}


def test_skipped_notes_name_the_parameter_and_never_its_value():
    _, skipped = paramstore.settings_from([p("OTHER", "super-secret-value")], PREFIX)

    assert skipped == ["OTHER (not a managed setting)"] and "super-secret-value" not in skipped[0]


def test_the_list_of_managed_settings_excludes_everything_that_would_lose_data():
    assert not {"KMS_LOCAL_MASTER_KEY", "BLIND_INDEX_KEY", "DJANGO_SECRET_KEY"} & paramstore.MANAGED
