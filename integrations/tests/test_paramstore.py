"""Which settings Parameter Store may set, and that nothing dangerous slips through."""

from __future__ import annotations

import pytest

from integrations import paramstore

PREFIX = "/autoca/prod/"


def p(name, value):
    return {"Name": PREFIX + name, "Value": value}


def test_any_setting_is_returned_by_its_short_name():
    found, skipped = paramstore.settings_from(
        [p("LLM_API_KEY", "sk-abc"), p("LLM_BATCH_SIZE", "40")], PREFIX
    )

    assert found == {"LLM_API_KEY": "sk-abc", "LLM_BATCH_SIZE": "40"} and skipped == []


@pytest.mark.parametrize(
    "name",
    [
        "KMS_LOCAL_MASTER_KEY",
        "BLIND_INDEX_KEY",
        "DJANGO_SECRET_KEY",
        "DATABASE_URL",
        "POSTGRES_PASSWORD",
    ],
)
def test_the_permanent_keys_and_database_credentials_are_seed_only(name):
    found, skipped = paramstore.settings_from([p(name, "value")], PREFIX)

    assert found == {"?" + name: "value"} and skipped == []


def test_a_value_with_a_line_break_is_refused_so_it_cannot_smuggle_in_a_second_setting():
    found, skipped = paramstore.settings_from(
        [p("LLM_API_KEY", "sk-abc\nDJANGO_SECRET_KEY=owned")], PREFIX
    )

    assert found == {} and "LLM_API_KEY" in skipped[0]
    assert "owned" not in " ".join(skipped)


def test_an_empty_value_is_left_out_not_written_over_a_working_setting():
    found, _ = paramstore.settings_from([p("LLM_API_KEY", "")], PREFIX)

    assert found == {}


@pytest.mark.parametrize(
    "name", ["lowercase", "HAS SPACE", "WITH-DASH", "A/B", "1STARTS_WITH_DIGIT"]
)
def test_a_name_that_is_not_a_setting_name_is_left_out(name):
    found, skipped = paramstore.settings_from([p(name, "v")], PREFIX)

    assert found == {} and len(skipped) == 1


def test_the_settings_that_steer_the_pull_itself_cannot_be_set_from_a_parameter():
    found, _ = paramstore.settings_from(
        [p("PARAMETER_PREFIX", "/other/"), p("PARAMETER_REGION", "us-east-1")], PREFIX
    )

    assert found == {}


def test_skipped_notes_name_the_parameter_and_never_its_value():
    _, skipped = paramstore.settings_from([p("bad name", "super-secret-value")], PREFIX)

    assert "super-secret-value" not in skipped[0]


@pytest.mark.parametrize(
    "name",
    [
        "LD_PRELOAD",
        "LD_LIBRARY_PATH",
        "PYTHONPATH",
        "PYTHONSTARTUP",
        "DJANGO_SETTINGS_MODULE",
        "DEBUG",
        "PATH",
        "COMPOSE_FILE",
        "DOCKER_HOST",
        "AWS_ACCESS_KEY_ID",
        "BASH_ENV",
    ],
)
def test_names_that_change_how_a_process_starts_are_never_accepted(name):
    found, skipped = paramstore.settings_from([p(name, "v")], PREFIX)

    assert found == {} and len(skipped) == 1
