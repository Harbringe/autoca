"""A client's books can be signed off, and a sign-off cannot be quietly undone.

``signed_off_through`` is the date up to which a senior has signed the books.
Everything dated on or before it is locked (that lock is installed on the
journal tables by ``ledger.0008``). This migration adds the column and guards
the one way the lock could be dodged without touching the journal at all:
moving the date backwards.

Moving it forward locks more, and any code that has a reason to do that may.
Moving it back -- or clearing it -- unlocks history, so the database refuses
unless the transaction has declared ``app.allow_reopen``. That is a speed bump
rather than a wall, deliberately: a sign-off that could never be undone would
turn one mistaken click into a support incident. What it does guarantee is that
a reopen is *explicit* in the code that does it, and so findable, and that no
ordinary update of a client -- renaming it, changing its lead -- can unlock
anything by accident.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0010_profile"),
    ]

    operations = [
        migrations.AddField(
            model_name="client",
            name="signed_off_through",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.RunSQL(
            sql="""
CREATE OR REPLACE FUNCTION app.client_signoff_guard()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.signed_off_through IS NOT NULL
       AND (NEW.signed_off_through IS NULL OR NEW.signed_off_through < OLD.signed_off_through)
       AND COALESCE(current_setting('app.allow_reopen', true), '') <> 'on'
    THEN
        RAISE EXCEPTION
            'the books are signed off through %; moving that date back is a reopen',
            OLD.signed_off_through
            USING ERRCODE = '42501',
                  HINT = 'Reopen the books explicitly (ledger.books.reopen).';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS client_signoff_guard ON core_client;
CREATE TRIGGER client_signoff_guard
    BEFORE UPDATE OF signed_off_through ON core_client
    FOR EACH ROW EXECUTE FUNCTION app.client_signoff_guard();
""",
            reverse_sql="""
DROP TRIGGER IF EXISTS client_signoff_guard ON core_client;
DROP FUNCTION IF EXISTS app.client_signoff_guard();
""",
        ),
    ]
