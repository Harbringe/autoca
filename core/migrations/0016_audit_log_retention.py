"""Lets an old audit-log row be deleted, and only an old one.

``0013_audit_log_append_only`` made ``core_audit_log`` refuse UPDATE and DELETE outright, on the same footing as the
journal: the application role has no grant to try either, and a trigger refuses both regardless of role, as a second,
independent guarantee. That is still exactly right for UPDATE -- an audit row is never corrected, only superseded by
a later one -- but held absolutely for DELETE as well, there would be no way to ever retire old rows at all, so the
table grows forever, which is its own problem (storage, and a log so large nobody reads it).

This migration replaces just that table's trigger with one that keeps UPDATE refused unconditionally, and allows
DELETE only when the row being removed is already at least ``RETENTION_FLOOR_DAYS`` old. That is a floor, not a
policy: it does not delete anything itself, it only says what the database will allow a deletion of, so a retention
job (``core.management.commands.trim_audit_log``, run on the privileged ``owner`` connection -- the application role
still has no DELETE grant on this table at all) cannot remove anything newer than the floor even if it is buggy, is
asked to with a shorter window, or is run by the wrong account. The job's own default window is the same
``RETENTION_FLOOR_DAYS`` days; the floor is what makes that a guarantee rather than a convention.
"""

from django.db import migrations

RETENTION_FLOOR_DAYS = 30

GUARD = f"""
CREATE OR REPLACE FUNCTION app.core_audit_log_immutable()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'core_audit_log is append-only: rows cannot be changed once written'
            USING ERRCODE = '42501';
    END IF;

    IF TG_OP = 'DELETE' THEN
        IF OLD.created_at > now() - interval '{RETENTION_FLOOR_DAYS} days' THEN
            RAISE EXCEPTION
                'core_audit_log rows may only be removed once at least {RETENTION_FLOOR_DAYS} days old (retention floor); this one is dated %', OLD.created_at
                USING ERRCODE = '42501';
        END IF;
        RETURN OLD;
    END IF;

    RETURN NEW;
END;
$$;
"""

REVERSE_TO_ABSOLUTE = """
CREATE OR REPLACE FUNCTION app.core_audit_log_immutable()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'core_audit_log is append-only: rows cannot be % once written', lower(TG_OP)
        USING ERRCODE = '42501';
END;
$$;
"""


class Migration(migrations.Migration):
    dependencies = [("core", "0015_client_nce_settings")]

    operations = [migrations.RunSQL(sql=GUARD, reverse_sql=REVERSE_TO_ABSOLUTE)]
