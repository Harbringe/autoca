"""A rule, its ledger and its party all belong to the same client.

Row-level security is firm-scoped, and rightly so: one firm reading another
firm's rows is impossible in the database whatever the application does. Inside
a firm it says nothing, because two clients of one firm are one tenant to
PostgreSQL. Yet a CA firm's liability rests on its clients' books being
separate, and a rule is the one object that could join them: it names a ledger,
and a ledger belongs to exactly one client.

So this is enforced the way firm isolation is -- in PostgreSQL, not in
application code that a future ``objects.create`` can walk past. A composite
foreign key on ``(client_id, ledger_id)`` makes the ledger's client and the
rule's client the same value, checked on every write.

Two consequences:

* ``classify_rule.client_id`` becomes NOT NULL. A firm-wide rule was always
  incoherent -- it would have to name one client's ledger and would then post
  every other client's transactions into it -- and, under MATCH SIMPLE, a NULL
  in a referencing column satisfies a composite foreign key trivially, which
  would reopen the very hole the key exists to close.
* ``classify_ledger_account`` and ``classify_vendor`` gain a UNIQUE
  ``(client_id, id)``. Redundant as a key, since ``id`` is unique alone; it is
  there because a foreign key needs a unique index to point at.
"""

from django.db import migrations, models
import django.db.models.deletion

#: Tables this migration must read and validate in full.
#:
#: The usual helper, ``core.db.rls.ddl_tenant_context_operations``, gives a
#: migration one firm's context so foreign key validation does not raise. Its
#: own docstring names the cost: under that context the validation scan sees
#: zero rows, so the constraint is marked valid without having checked
#: anything. This migration adds the key that keeps two clients' books apart,
#: and a key validated against no rows is exactly the reassurance we must not
#: accept -- it would report success over whatever mismatched rows already
#: exist.
#:
#: So rather than narrow the migration to one firm, lift FORCE for its length.
#: ``NO FORCE`` exempts only the table's owner, the role running the migration,
#: which is already trusted with DDL; the policies stay in place for every
#: application role throughout. ``ALTER TABLE`` is transactional in PostgreSQL
#: and a migration is one transaction, so a failure anywhere below rolls the
#: exemption back along with everything else.
_UNFORCED = [
    "classify_rule",
    "classify_ledger_account",
    "classify_vendor",
    "core_client",
    "classify_transaction_classification",
    "banking_statement_transaction",
    "banking_bank_account",
]


def _force(state):
    return [f"ALTER TABLE {table} {state} ROW LEVEL SECURITY;" for table in _UNFORCED]


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0008_firm_owner"),
        ("classify", "0008_book_narration_and_open_question"),
    ]

    operations = [
        migrations.RunSQL(sql=_force("NO FORCE"), reverse_sql=_force("FORCE")),
        # Any surviving firm-wide rule is, by the argument above, one that would
        # post other clients' money into a single client's ledger. There is no
        # client it could be reassigned to that would preserve its meaning,
        # because it never had a coherent one.
        migrations.RunSQL(
            sql=[
                # Rows a firm-wide rule already placed. Where it put one
                # client's transaction into another client's ledger, the
                # placement is not merely unexplained, it is wrong: unbook it
                # and return it to the review queue, which is where a row with
                # no defensible ledger belongs.
                """
                UPDATE classify_transaction_classification tc
                   SET ledger_id   = NULL,
                       rule_id     = NULL,
                       vendor_id   = NULL,
                       needs_review = true,
                       confidence  = 0,
                       -- ``ck_unresolved_has_no_ledger`` keeps the method and
                       -- the ledger in step: no ledger means UNRESOLVED.
                       method      = 'UNRESOLVED'
                  FROM classify_ledger_account l,
                       banking_statement_transaction st,
                       banking_bank_account ba
                 WHERE l.id  = tc.ledger_id
                   AND st.id = tc.transaction_id
                   AND ba.id = st.bank_account_id
                   AND ba.client_id <> l.client_id;
                """,
                # Whatever provenance survives, the rule itself is going. This
                # is what the model's own ``on_delete=SET_NULL`` would do.
                """
                UPDATE classify_transaction_classification tc
                   SET rule_id = NULL
                  FROM classify_rule r
                 WHERE r.id = tc.rule_id AND r.client_id IS NULL;
                """,
                "DELETE FROM classify_rule WHERE client_id IS NULL;",
                # The delete queues the referential triggers of every foreign
                # key touching these rows, and PostgreSQL refuses to ALTER a
                # table with trigger events still pending. Firing them now lets
                # the schema changes below proceed in the same transaction.
                "SET CONSTRAINTS ALL IMMEDIATE;",
            ],
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.AlterField(
            model_name="classificationrule",
            name="client",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="classification_rules",
                to="core.client",
            ),
        ),
        migrations.RunSQL(
            sql=[
                "ALTER TABLE classify_ledger_account "
                "ADD CONSTRAINT uniq_ledger_client_id UNIQUE (client_id, id);",
                "ALTER TABLE classify_vendor "
                "ADD CONSTRAINT uniq_vendor_client_id UNIQUE (client_id, id);",
                # A rule's ledger must be a ledger of the rule's own client.
                "ALTER TABLE classify_rule "
                "ADD CONSTRAINT rule_ledger_same_client "
                "FOREIGN KEY (client_id, ledger_id) "
                "REFERENCES classify_ledger_account (client_id, id) "
                "ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED;",
                # And its party must be a party of that client. vendor_id is
                # nullable; under MATCH SIMPLE a NULL there satisfies the key,
                # which is what a rule with no party should do.
                #
                # NO ACTION rather than SET NULL: a composite SET NULL nulls
                # every referencing column, including client_id, which is now
                # NOT NULL. Django's own ``on_delete=SET_NULL`` clears vendor_id
                # first and this constraint is deferred to commit, so deleting a
                # party still works and lands with vendor_id already NULL.
                "ALTER TABLE classify_rule "
                "ADD CONSTRAINT rule_vendor_same_client "
                "FOREIGN KEY (client_id, vendor_id) "
                "REFERENCES classify_vendor (client_id, id) "
                "ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;",
            ],
            reverse_sql=[
                "ALTER TABLE classify_rule DROP CONSTRAINT rule_vendor_same_client;",
                "ALTER TABLE classify_rule DROP CONSTRAINT rule_ledger_same_client;",
                "ALTER TABLE classify_vendor DROP CONSTRAINT uniq_vendor_client_id;",
                "ALTER TABLE classify_ledger_account DROP CONSTRAINT uniq_ledger_client_id;",
            ],
        ),
        migrations.RunSQL(sql=_force("FORCE"), reverse_sql=_force("NO FORCE")),
    ]
