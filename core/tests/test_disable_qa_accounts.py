"""The synthetic QA accounts can be found and turned off, and nobody else is touched."""

from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command

from core.models import User

pytestmark = pytest.mark.django_db


def run(*args):
    out = StringIO()
    call_command("disable_qa_accounts", *args, stdout=out)
    return out.getvalue()


@pytest.fixture
def people():
    qa = [User.objects.create_user(email=f"qa.{role}@autoca.test", password="a-throwaway-password-1") for role in ("admin", "reader")]
    other = User.objects.create_user(email="someone@example.test", password="a-real-password-1")
    lookalike = User.objects.create_user(email="qa.admin@autoca.test.example.com", password="a-real-password-2")
    return qa, other, lookalike


def test_by_default_it_only_lists(people):
    qa, other, _ = people
    text = run()
    assert "qa.admin@autoca.test: active" in text and "qa.reader@autoca.test: active" in text and "someone@example.test" not in text
    for user in qa:
        user.refresh_from_db()
        assert user.is_active and user.has_usable_password()


def test_apply_turns_the_qa_accounts_off_and_nothing_else(people):
    qa, other, lookalike = people
    assert "Turned off." in run("--apply")
    for user in qa:
        user.refresh_from_db()
        assert not user.is_active and not user.has_usable_password()
        assert not user.check_password("a-throwaway-password-1")
    for user in (other, lookalike):
        user.refresh_from_db()
        assert user.is_active and user.has_usable_password()


def test_with_none_there_it_says_so():
    assert "No QA accounts here." in run("--apply")
