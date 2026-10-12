"""The change marker used to refuse a save over someone else's edit (no database needed)."""

from __future__ import annotations

from types import SimpleNamespace

from api.concurrency import version_of

FIELDS = ("name", "is_active")


def test_the_same_values_give_the_same_version():
    assert version_of(SimpleNamespace(name="A", is_active=True), FIELDS) == version_of(SimpleNamespace(name="A", is_active=True), FIELDS)


def test_a_change_to_an_editable_field_changes_the_version():
    before = version_of(SimpleNamespace(name="A", is_active=True), FIELDS)
    assert version_of(SimpleNamespace(name="B", is_active=True), FIELDS) != before
    assert version_of(SimpleNamespace(name="A", is_active=False), FIELDS) != before


def test_fields_outside_the_list_do_not_matter():
    assert version_of(SimpleNamespace(name="A", is_active=True, row_count=1), FIELDS) == version_of(
        SimpleNamespace(name="A", is_active=True, row_count=9), FIELDS
    )


def test_values_that_would_run_together_stay_apart():
    assert version_of(SimpleNamespace(name="ab", is_active="c"), FIELDS) != version_of(SimpleNamespace(name="a", is_active="bc"), FIELDS)
