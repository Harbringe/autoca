"""Migrations ship before the code that needs them, so they must suit the previous release.

A NOT NULL column with only a Python default broke every production upload (2026-10-01).
"""

import re

from django.apps import apps
from django.db import migrations
from django.db.migrations.loader import MigrationLoader
from django.db.models import NOT_PROVIDED

# Highest migration number per app that predates this rule; older history is not checked.
CHECKED_AFTER = {
    "core": 12,
    "documents": 2,
    "banking": 2,
    "classify": 15,
    "ledger": 8,
    "gst": 3,
    "teams": 5,
    "superadmin": 7,
}

# (app, migration name, model, field) allowed to add a NOT NULL column without db_default.
# Only for a table that is empty by construction, with a reason.
ALLOWED_ADD_FIELDS: set[tuple[str, str, str, str]] = set()

# (app, migration name) allowed to drop or rename: the code that used the column has
# already been released everywhere. Give the reason beside each entry.
ALLOWED_DESTRUCTIVE: set[tuple[str, str]] = set()

OWN_APPS = {cfg.label for cfg in apps.get_app_configs() if cfg.name.split(".")[0] in {
    "core", "api", "integrations", "documents", "banking", "classify", "ledger", "gst", "teams", "superadmin",
}}


def _number(name: str) -> int:
    match = re.match(r"(\d+)_", name)
    return int(match.group(1)) if match else 0


def _operations():
    loader = MigrationLoader(None, ignore_no_migrations=True)
    for (app, name), migration in sorted(loader.disk_migrations.items()):
        if app in OWN_APPS and _number(name) > CHECKED_AFTER.get(app, 0):
            for op in migration.operations:
                yield app, name, op


def _unsafe_add(field) -> bool:
    return not field.null and field.db_default is NOT_PROVIDED


def test_new_migrations_are_backward_compatible():
    problems = []
    for app, name, op in _operations():
        if isinstance(op, migrations.AddField) and _unsafe_add(op.field):
            if (app, name, op.model_name, op.name) not in ALLOWED_ADD_FIELDS:
                problems.append(f"{app}/{name}: AddField {op.model_name}.{op.name} is NOT NULL with no db_default")
        if isinstance(
            op,
            (migrations.RemoveField, migrations.RenameField, migrations.DeleteModel, migrations.RenameModel),
        ) and (app, name) not in ALLOWED_DESTRUCTIVE:
            problems.append(f"{app}/{name}: {type(op).__name__} breaks the release still running")
    assert not problems, "\n".join(problems)


def test_guard_flags_a_python_only_default():
    from django.db import models

    assert _unsafe_add(models.PositiveSmallIntegerField(default=0))
    assert not _unsafe_add(models.PositiveSmallIntegerField(default=0, db_default=0))
    assert not _unsafe_add(models.CharField(max_length=3, null=True))

