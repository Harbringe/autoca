"""A vendor becomes a party, and a party can be recognised by more than one name.

Two changes, and the second is the reason for the first.

**A vendor is only half the relationships a firm's books hold.** The model was
written for the purchase side -- reverse charge, TDS section, "who did we pay"
-- because a bank statement is mostly money going out. But a sales invoice
needs a customer, a loan needs a lender, and payroll needs an employee, and
none of those is a vendor. Rather than grow a second near-identical table per
role, the model gains a ``role`` and keeps one identity per counterparty, which
is also the only shape under which "what is our net position with this party"
is a single query.

**A party is recognised by its spellings, not by its canonical name.** The bank
prints the same payee three ways across three channels, so exact matching on a
canonical name recognises almost nothing. ``PartyAlias`` is the memory of
spellings a person has already confirmed, and ``PartyBankAccount`` is the one
signal strong enough to resolve a counterparty without asking anyone. Neither
is a similarity score: matching may *suggest*, but merging two parties is a
decision a person makes, because a wrong merge silently joins two people's
ledgers and nothing downstream would reveal it.

On the renames below:

* The table moves ``classify_vendor`` -> ``classify_party``. PostgreSQL keeps
  row-level security policies, constraints and indexes across a table rename --
  they are bound to the table's identity, not its name -- so isolation is
  continuous through this migration and does not need re-establishing.
* Constraint names are renamed to match. They are cosmetic to the database and
  load-bearing to the next person writing a composite-key migration, who will
  copy a table list out of ``0009`` and needs the names in it to exist.
* ``CRYPTO_PURPOSE`` deliberately does **not** change. It is mixed into key
  derivation and into the GSTIN blind index, so renaming it would make every
  stored GSTIN undecryptable and every indexed hash unfindable. See the comment
  on the constant.
"""

import uuid

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models

from core.db.rls import ddl_tenant_context_operations

#: Tables the composite foreign keys below must read to validate themselves.
#: FORCE is lifted across them for the length of this migration only; see the
#: comment at the point of use.
_UNFORCED = [
    "classify_party",
    "classify_party_alias",
    "classify_party_bank_account",
]


class Migration(migrations.Migration):

    dependencies = [
        ("classify", "0010_classification_ledger_matches_its_client"),
        ("core", "0010_profile"),
        # Every migration that names ``classify.vendor`` has to have run before
        # the name stops existing. ``ledger.0001`` creates JournalLine with a
        # key to it, and nothing else orders the two apps against each other --
        # left to itself the planner is free to rename first and then fail to
        # build a table that refers to the old name. This edge is what makes the
        # ordering a fact rather than a coincidence.
        ("ledger", "0004_journal_lines_stay_in_one_clients_books"),
    ]

    operations = [
        # First, and it has to be first. Django holds a migration's foreign key
        # SQL in ``deferred_sql`` and flushes it when the schema editor closes,
        # after every operation below has run -- so the two new tables' keys to
        # core_client, core_firm and core_user are created at the very end. Each
        # one is validated by a join against a FORCE ROW LEVEL SECURITY table,
        # which raises without a tenant context. A context set here is
        # transaction-scoped, and a migration is one transaction, so it is still
        # in force at that flush.
        #
        # Its documented caveat -- that the scan then sees zero rows and
        # validates nothing -- is harmless here precisely because these tables
        # are being created empty in this migration. There is nothing for it to
        # have missed. The composite keys further down are handled differently,
        # and the comment there says why.
        *ddl_tenant_context_operations(),
        # -- the rename itself ------------------------------------------------
        migrations.RenameModel(old_name="Vendor", new_name="Party"),
        migrations.AlterModelTable(name="party", table="classify_party"),
        # Each rename below is a state change paired with a bare
        # ``RENAME COLUMN``, rather than Django's ``RenameField`` alone.
        #
        # ``RenameField`` does more than rename: its schema editor drops every
        # foreign key on the column and recreates it afterwards. Recreating one
        # makes PostgreSQL validate it, and validation is a join across two
        # FORCE ROW LEVEL SECURITY tables, run from a migration that holds no
        # tenant context -- so the policy refuses it and the migration dies.
        #
        # ``ALTER TABLE ... RENAME COLUMN`` is catalogue-only: no rows are read,
        # no constraint is dropped, and PostgreSQL rewrites the dependent keys
        # itself because they track column numbers rather than names. The
        # composite keys from 0009 therefore survive continuously, which matters
        # -- they are what keeps one client's rules off another client's ledgers,
        # and a window where they were absent would be a window where that
        # guarantee was not being enforced.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RenameField(
                    model_name="classificationrule", old_name="vendor", new_name="party"
                ),
                migrations.RenameField(
                    model_name="transactionclassification",
                    old_name="vendor",
                    new_name="party",
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql=[
                        "ALTER TABLE classify_rule RENAME COLUMN vendor_id TO party_id;",
                        "ALTER TABLE classify_transaction_classification "
                        "RENAME COLUMN vendor_id TO party_id;",
                    ],
                    reverse_sql=[
                        "ALTER TABLE classify_transaction_classification "
                        "RENAME COLUMN party_id TO vendor_id;",
                        "ALTER TABLE classify_rule RENAME COLUMN party_id TO vendor_id;",
                    ],
                ),
            ],
        ),
        # No AlterField restating these foreign keys. ``RenameModel`` already
        # retargets every key that pointed at Vendor, and ``RenameField`` already
        # renames the column. Restating them would make Django drop and recreate
        # a constraint that is already correct, and recreating a foreign key
        # makes PostgreSQL validate it -- a scan of a FORCE ROW LEVEL SECURITY
        # table from a migration with no tenant context, which the policy
        # refuses. The keys survive this migration untouched, which is also why
        # the guarantee they carry is never briefly absent.
        migrations.AlterField(
            model_name="party",
            name="client",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="parties",
                to="core.client",
            ),
        ),
        # -- what a party now carries ----------------------------------------
        migrations.AddField(
            model_name="party",
            name="role",
            field=models.CharField(
                choices=[
                    ("VENDOR", "Supplier"),
                    ("CUSTOMER", "Customer"),
                    ("BOTH", "Both supplier and customer"),
                    ("OTHER", "Other (lender, employee, related party)"),
                ],
                default="VENDOR",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="party",
            name="notes",
            field=models.TextField(blank=True, default=""),
        ),
        # No backfill statement follows, and that is not an omission. Every row
        # that exists today came from the purchase side, so VENDOR is the
        # correct value for all of them -- and ``AddField`` with a default
        # writes that value into every existing row as part of the ALTER.
        #
        # An explicit ``UPDATE`` afterwards would be worse than redundant: this
        # table is FORCE ROW LEVEL SECURITY, a migration runs with no tenant
        # context, and the policy would refuse the statement with "tenant
        # context missing". Data manipulation on a forced table has to lift
        # FORCE for the length of the migration the way 0009 does. DDL does
        # not, which is why everything here is DDL.
        # -- names that referred to the old one -------------------------------
        migrations.RemoveConstraint(
            model_name="party", name="uniq_vendor_name_per_client"
        ),
        migrations.AddConstraint(
            model_name="party",
            constraint=models.UniqueConstraint(
                fields=("firm", "client", "canonical_name"),
                name="uniq_party_name_per_client",
            ),
        ),
        # These two were written in raw SQL by 0009 and are not in Django's
        # model state, so they are renamed the same way they were made.
        migrations.RunSQL(
            sql=[
                "ALTER TABLE classify_party "
                "RENAME CONSTRAINT uniq_vendor_client_id TO uniq_party_client_id;",
                "ALTER TABLE classify_rule "
                "RENAME CONSTRAINT rule_vendor_same_client TO rule_party_same_client;",
            ],
            reverse_sql=[
                "ALTER TABLE classify_rule "
                "RENAME CONSTRAINT rule_party_same_client TO rule_vendor_same_client;",
                "ALTER TABLE classify_party "
                "RENAME CONSTRAINT uniq_party_client_id TO uniq_vendor_client_id;",
            ],
        ),
        # -- the two new tables ------------------------------------------------
        migrations.CreateModel(
            name="PartyAlias",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(default=django.utils.timezone.now, editable=False),
                ),
                ("alias_normalised", models.CharField(max_length=255)),
                ("alias_display", models.CharField(max_length=255)),
                (
                    "source",
                    models.CharField(
                        choices=[
                            ("BANK_NARRATION", "From a bank narration"),
                            ("INVOICE", "From an invoice"),
                            ("MANUAL", "Entered by hand"),
                        ],
                        default="BANK_NARRATION",
                        max_length=16,
                    ),
                ),
                ("confirmed_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "client",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="party_aliases",
                        to="core.client",
                    ),
                ),
                (
                    "confirmed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="confirmed_aliases",
                        to="core.user",
                    ),
                ),
                (
                    "firm",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="%(class)ss",
                        to="core.firm",
                    ),
                ),
                (
                    "party",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="aliases",
                        to="classify.party",
                    ),
                ),
            ],
            options={"db_table": "classify_party_alias", "ordering": ["alias_display"]},
        ),
        migrations.CreateModel(
            name="PartyBankAccount",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(default=django.utils.timezone.now, editable=False),
                ),
                ("account_hash", models.CharField(db_index=True, max_length=64)),
                ("last4", models.CharField(blank=True, max_length=4)),
                ("ifsc", models.CharField(blank=True, max_length=16)),
                (
                    "source",
                    models.CharField(
                        choices=[
                            ("BANK_NARRATION", "From a bank narration"),
                            ("INVOICE", "From an invoice"),
                            ("MANUAL", "Entered by hand"),
                        ],
                        default="BANK_NARRATION",
                        max_length=16,
                    ),
                ),
                ("confirmed_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "client",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="party_bank_accounts",
                        to="core.client",
                    ),
                ),
                (
                    "confirmed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="confirmed_accounts",
                        to="core.user",
                    ),
                ),
                (
                    "firm",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="%(class)ss",
                        to="core.firm",
                    ),
                ),
                (
                    "party",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="bank_accounts",
                        to="classify.party",
                    ),
                ),
            ],
            options={"db_table": "classify_party_bank_account", "ordering": ["last4"]},
        ),
        migrations.AddIndex(
            model_name="partyalias",
            index=models.Index(
                fields=["firm", "client", "alias_normalised"], name="idx_alias_lookup"
            ),
        ),
        migrations.AddConstraint(
            model_name="partyalias",
            constraint=models.UniqueConstraint(
                fields=("firm", "client", "alias_normalised"), name="uniq_alias_per_client"
            ),
        ),
        migrations.AddConstraint(
            model_name="partybankaccount",
            constraint=models.UniqueConstraint(
                fields=("firm", "client", "account_hash"),
                name="uniq_party_account_per_client",
            ),
        ),
        # An alias names a party of its own client, enforced where it cannot be
        # bypassed -- the same composite-key argument 0009 makes for rules.
        #
        # FORCE is lifted around it for the same reason 0009 lifts it. Adding a
        # foreign key makes PostgreSQL validate it, and it runs that validation
        # even when the referencing table is empty: the query still joins
        # ``classify_party``, whose policy calls ``app.current_firm_id()``, which
        # raises in a migration that has no tenant context. An empty result set
        # does not save it, because the policy is evaluated before the rows are.
        #
        # The tenant context at the top would be enough to stop this raising,
        # but it would also reduce the check to nothing: under that context the
        # scan sees one synthetic firm's rows. Lifting FORCE instead exempts the
        # owner from the policy entirely, so the validation runs against every
        # row there is. Today both tables are empty and the two approaches agree;
        # the difference is that this one keeps agreeing if they ever are not.
        #
        # ``NO FORCE`` exempts only the table's owner -- the role running the
        # migration, already trusted with DDL -- and leaves the policies in place
        # for every application role throughout. ALTER TABLE is transactional, so
        # a failure below rolls the exemption back with everything else.
        migrations.RunSQL(
            sql=[f"ALTER TABLE {t} NO FORCE ROW LEVEL SECURITY;" for t in _UNFORCED],
            reverse_sql=[f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY;" for t in _UNFORCED],
        ),
        migrations.RunSQL(
            sql=[
                "ALTER TABLE classify_party_alias "
                "ADD CONSTRAINT alias_party_same_client "
                "FOREIGN KEY (client_id, party_id) "
                "REFERENCES classify_party (client_id, id) "
                "ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED;",
                "ALTER TABLE classify_party_bank_account "
                "ADD CONSTRAINT account_party_same_client "
                "FOREIGN KEY (client_id, party_id) "
                "REFERENCES classify_party (client_id, id) "
                "ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED;",
            ],
            reverse_sql=[
                "ALTER TABLE classify_party_bank_account "
                "DROP CONSTRAINT account_party_same_client;",
                "ALTER TABLE classify_party_alias DROP CONSTRAINT alias_party_same_client;",
            ],
        ),
        migrations.RunSQL(
            sql=[f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY;" for t in _UNFORCED],
            reverse_sql=[f"ALTER TABLE {t} NO FORCE ROW LEVEL SECURITY;" for t in _UNFORCED],
        ),
    ]
