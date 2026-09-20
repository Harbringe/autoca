"""Guard rails for the one role in this system that can bypass RLS."""

from __future__ import annotations

from django.core.checks import Tags, Warning, register
from django.db import DEFAULT_DB_ALIAS, DatabaseError, connections

from superadmin.sql import READER_ROLE


@register(Tags.database)
def check_platform_reader_is_contained(app_configs, **kwargs):
    try:
        with connections[DEFAULT_DB_ALIAS].cursor() as cursor:
            cursor.execute(
                "SELECT rolcanlogin FROM pg_roles WHERE rolname = %s", [READER_ROLE]
            )
            row = cursor.fetchone()
            cursor.execute(
                # The test role is a member on purpose: it owns the functions in
                # its scratch database. The serving role must never be.
                "SELECT current_user <> 'autoca_test' AND CASE WHEN EXISTS "
                "(SELECT 1 FROM pg_roles WHERE rolname = %s) "
                "THEN pg_has_role(current_user, %s, 'MEMBER') ELSE false END",
                [READER_ROLE, READER_ROLE],
            )
            app_inherits = cursor.fetchone()[0]
    except DatabaseError:
        return []

    messages = []
    if row and row[0]:
        messages.append(
            Warning(f"{READER_ROLE} can log in. It must be NOLOGIN.", id="superadmin.W001")
        )
    if app_inherits:
        messages.append(
            Warning(
                f"The application's database role is a member of {READER_ROLE}, so it "
                "could SET ROLE to it and bypass RLS. Revoke that membership.",
                id="superadmin.W002",
            )
        )
    return messages
