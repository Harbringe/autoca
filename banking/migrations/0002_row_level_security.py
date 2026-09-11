"""Put the banking tables behind tenant isolation.

**This is a separate migration from the one that creates the tables, and it has
to be.** Django opens one schema editor per migration and flushes its deferred
SQL -- which is where foreign key constraints live -- when that editor closes,
after every operation in the migration has run. So an ``rls_operations`` call
appended to a CreateModel migration is applied *before* the foreign keys, and
adding a foreign key makes PostgreSQL run a validation scan over the table:

    SELECT fk.client_id FROM ONLY banking_bank_account fk
    LEFT OUTER JOIN ONLY core_client pk ON pk.id = fk.client_id ...

That scan hits a table that is now FORCE ROW LEVEL SECURITY, from a migration
with no tenant context, and the whole migration dies on

    tenant context missing: app.firm_id is not set for this transaction

which reads like a bug in the tenancy layer rather than an ordering problem.
FORCE is what makes it bite: the owner role running the migration is subject to
the policies too, which is the entire point of FORCE and is not negotiable.

Split the migration and the ordering is explicit rather than emergent.
"""

from django.db import migrations

from core.db.rls import rls_operations, sequence_grant_sql


class Migration(migrations.Migration):
    dependencies = [("banking", "0001_initial")]

    operations = [
        *rls_operations("banking_bank_account"),
        *rls_operations("banking_statement"),
        *rls_operations("banking_statement_transaction"),
        migrations.RunSQL(sql=sequence_grant_sql(), reverse_sql=migrations.RunSQL.noop),
    ]
