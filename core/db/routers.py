"""Database routing between the app role and the owner role.

There is one physical database and two aliases. Reads and writes go through the
low-privilege ``default`` alias; schema changes go through ``owner``. Routing
this explicitly means a stray ``Model.objects.using("owner")`` is visible in
review rather than buried in a settings dict.
"""

from __future__ import annotations


class OwnerMigrationRouter:
    """Send DDL to the owner alias, everything else to the app alias."""

    def db_for_read(self, model, **hints):
        return "default"

    def db_for_write(self, model, **hints):
        return "default"

    def allow_relation(self, obj1, obj2, **hints):
        # Same physical database, so relations across aliases are fine.
        return True

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        # Migrations are applied via `manage.py migrate --database=owner`.
        # Returning True for both aliases keeps the test runner (which migrates
        # the `default` alias) working, while production uses the owner role.
        return db in {"default", "owner"}
