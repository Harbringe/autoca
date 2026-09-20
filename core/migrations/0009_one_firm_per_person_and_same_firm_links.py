"""A person belongs to one firm, and every link inside a firm stays inside it.

Two things the application believed and the database did not check.

**One firm per person.** The old constraint was on the pair (firm, user), which
says a person may hold at most one membership *per firm* -- so the same account
could work at two firms at once. That is now wrong by decision: an account
belongs to exactly one firm. The single exception is the platform owner, who
belongs to none, and that is precisely what marks them as the platform owner
(see superadmin/models.py).

**Same-firm links.** Three foreign keys point from one firm-scoped row to
another, and nothing made the two agree:

* a membership's ``manager``, the senior CA whose team they are on;
* a client's ``lead``, the senior CA responsible for it;
* a client assignment, which names both a client and a member.

``core/models.py`` says so outright next to ``Client.lead``: a foreign key
check is not subject to row-level security and would accept another firm's
membership. Until now the rule was held by ``teams/service.py``, which every
write went through. The Django admin does not: a ModelAdmin form writes the row
directly. Adding those pages without this migration would hand someone a form
that puts one firm's senior CA in charge of another firm's client.

So the rule moves into PostgreSQL, the same way firm isolation and the
classification rules' client scoping already live there. Each composite key
carries ``firm_id`` alongside the reference, so the referenced row must belong
to the same firm by construction rather than by anyone remembering to check.
"""

from django.db import migrations, models

#: Tables this migration reads and validates in full.
#:
#: Under FORCE row-level security the migrating role sees no rows without a
#: tenant context, so a foreign key added here would be marked valid having
#: checked nothing -- and these are exactly the keys whose whole purpose is to
#: check existing data. NO FORCE exempts only the table's owner, the role
#: running the migration, and leaves the policies in place for every
#: application role. ALTER TABLE is transactional, so a failure rolls the
#: exemption back with everything else.
_UNFORCED = ["core_firm_membership", "core_client", "core_client_assignment", "core_firm"]


def _force(state):
    return [f"ALTER TABLE {table} {state} ROW LEVEL SECURITY;" for table in _UNFORCED]


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0008_firm_owner"),
    ]

    operations = [
        migrations.RunSQL(sql=_force("NO FORCE"), reverse_sql=_force("FORCE")),
        migrations.RemoveConstraint(
            model_name="firmmembership",
            name="uniq_membership_per_firm_user",
        ),
        migrations.AddConstraint(
            model_name="firmmembership",
            constraint=models.UniqueConstraint(fields=["user"], name="uniq_membership_per_user"),
        ),
        migrations.RunSQL(
            sql=[
                # A composite foreign key needs a unique index to point at.
                # Redundant as keys, since id is unique alone; they exist so the
                # references below can carry firm_id with them.
                "ALTER TABLE core_firm_membership "
                "ADD CONSTRAINT uniq_membership_firm_id UNIQUE (firm_id, id);",
                "ALTER TABLE core_client "
                "ADD CONSTRAINT uniq_client_firm_id UNIQUE (firm_id, id);",
                # A member reports to a member of their own firm.
                #
                # NO ACTION rather than SET NULL throughout: a composite SET NULL
                # nulls every referencing column, firm_id included, and firm_id is
                # NOT NULL. Django's own on_delete clears the reference first, and
                # these are deferred to commit, so a delete still works and lands
                # with the reference already gone.
                "ALTER TABLE core_firm_membership "
                "ADD CONSTRAINT membership_manager_same_firm "
                "FOREIGN KEY (firm_id, manager_id) "
                "REFERENCES core_firm_membership (firm_id, id) "
                "ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;",
                # A client is led by a member of the firm that owns the client.
                "ALTER TABLE core_client "
                "ADD CONSTRAINT client_lead_same_firm "
                "FOREIGN KEY (firm_id, lead_id) "
                "REFERENCES core_firm_membership (firm_id, id) "
                "ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;",
                # An assignment names a client and a member of its own firm.
                "ALTER TABLE core_client_assignment "
                "ADD CONSTRAINT assignment_client_same_firm "
                "FOREIGN KEY (firm_id, client_id) "
                "REFERENCES core_client (firm_id, id) "
                "ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;",
                "ALTER TABLE core_client_assignment "
                "ADD CONSTRAINT assignment_member_same_firm "
                "FOREIGN KEY (firm_id, membership_id) "
                "REFERENCES core_firm_membership (firm_id, id) "
                "ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;",
            ],
            reverse_sql=[
                "ALTER TABLE core_client_assignment DROP CONSTRAINT assignment_member_same_firm;",
                "ALTER TABLE core_client_assignment DROP CONSTRAINT assignment_client_same_firm;",
                "ALTER TABLE core_client DROP CONSTRAINT client_lead_same_firm;",
                "ALTER TABLE core_firm_membership DROP CONSTRAINT membership_manager_same_firm;",
                "ALTER TABLE core_client DROP CONSTRAINT uniq_client_firm_id;",
                "ALTER TABLE core_firm_membership DROP CONSTRAINT uniq_membership_firm_id;",
            ],
        ),
        migrations.RunSQL(sql=_force("FORCE"), reverse_sql=_force("NO FORCE")),
    ]
