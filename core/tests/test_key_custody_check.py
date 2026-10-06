"""The deployment check says so while the master key is held by the web process."""

from __future__ import annotations

from core.checks import check_keys_are_not_held_by_the_web_process


def test_the_local_adapter_in_production_is_warned_about(settings):
    settings.DEBUG = False
    settings.INTEGRATIONS = {**settings.INTEGRATIONS, "kms": "integrations.kms.local_fernet.LocalFernetKMSAdapter"}

    messages = check_keys_are_not_held_by_the_web_process(None)

    assert [m.id for m in messages] == ["core.W017"]


def test_a_managed_key_service_is_not_warned_about(settings):
    settings.DEBUG = False
    settings.INTEGRATIONS = {**settings.INTEGRATIONS, "kms": "integrations.kms.aws.AwsKMSAdapter"}

    assert check_keys_are_not_held_by_the_web_process(None) == []


def test_development_is_left_alone(settings):
    settings.DEBUG = True
    settings.INTEGRATIONS = {**settings.INTEGRATIONS, "kms": "integrations.kms.local_fernet.LocalFernetKMSAdapter"}

    assert check_keys_are_not_held_by_the_web_process(None) == []
