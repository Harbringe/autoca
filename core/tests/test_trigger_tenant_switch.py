"""No BEFORE trigger may choose the tenant.

A BEFORE trigger runs before a row's row-level-security policy check. If it set the transaction's tenant from the incoming
row's own ``firm_id``, the check would then compare the row with itself and pass for any firm. The guard against that has
to be in the database, because the only other protection (``firm_context`` refusing to be re-entered) is in Python.

This reads the catalogue, so it covers every trigger that exists now and any added later.
"""

from __future__ import annotations

import pytest
from django.db import connection

pytestmark = pytest.mark.django_db

BEFORE_ROW_TRIGGERS_THAT_NAME_A_TENANT = """
SELECT c.relname || '.' || t.tgname
  FROM pg_trigger t
  JOIN pg_proc p ON p.oid = t.tgfoid
  JOIN pg_class c ON c.oid = t.tgrelid
 WHERE NOT t.tgisinternal
   AND (t.tgtype & 2) = 2                       -- BEFORE
   AND p.prosrc ILIKE '%%set_config%%'
 ORDER BY 1
"""


def test_no_before_trigger_sets_the_tenant_context():
    with connection.cursor() as cursor:
        cursor.execute(BEFORE_ROW_TRIGGERS_THAT_NAME_A_TENANT)
        offenders = [row[0] for row in cursor.fetchall()]

    assert offenders == [], (
        "These BEFORE triggers call set_config, so they can pick the tenant the policy check then trusts: "
        f"{offenders}. Only a deferred trigger, which runs after the check, may set it."
    )


def test_the_deferred_triggers_that_do_set_it_are_deferred_not_before():
    """The pattern is allowed only where it is safe: after the row has passed its policy check."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT c.relname || '.' || t.tgname, t.tgdeferrable, (t.tgtype & 2) = 2
              FROM pg_trigger t
              JOIN pg_proc p ON p.oid = t.tgfoid
              JOIN pg_class c ON c.oid = t.tgrelid
             WHERE NOT t.tgisinternal AND p.prosrc ILIKE '%%set_config%%'
            """
        )
        rows = cursor.fetchall()

    assert rows, "expected the commit-time balance and allocation checks to exist"
    for name, deferrable, is_before in rows:
        assert deferrable and not is_before, f"{name} sets the tenant but is not a deferred AFTER trigger"
