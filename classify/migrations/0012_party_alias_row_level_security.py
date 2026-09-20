"""Tenant isolation for the two tables 0011 created.

Separate from the migration that created them, and that separation is not
stylistic. Django flushes a migration's deferred SQL -- which is where foreign
key constraints live -- when the schema editor closes, so a policy added in the
same migration as ``CreateModel`` is applied *before* the foreign keys are.
Adding a foreign key then makes PostgreSQL validate against a table that is
already FORCE ROW LEVEL SECURITY, from a migration with no tenant context, and
it dies with ``tenant context missing``. ``core.db.rls.rls_operations`` says so
in its own docstring; this file is what obeying it looks like.

``classify_party`` itself needs nothing here: it kept the policy it was given
as ``classify_vendor`` in 0004, because PostgreSQL binds a policy to a table's
identity rather than to its name.
"""

from django.db import migrations

from core.db.rls import rls_operations


class Migration(migrations.Migration):

    dependencies = [
        ("classify", "0011_vendor_becomes_party"),
    ]

    operations = [
        *rls_operations("classify_party_alias"),
        *rls_operations("classify_party_bank_account"),
    ]
