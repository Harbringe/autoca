"""Tenant isolation for the GST tables, and immutability for the decision log.

Separate from 0001 for the reason documents/0002 gives: deferred foreign keys
are validated after the migration's operations, by which time FORCE'd policies
would already hide the rows.

``gst_recon_decision`` is append-only, like the books' review records: what a
person decided about an invoice, and who signed a run off, is a fact about the
past and is corrected by a later decision, never by an edit.
"""

from django.db import migrations

from core.db.rls import append_only_operations, rls_operations


class Migration(migrations.Migration):
    dependencies = [("gst", "0001_initial")]

    operations = [
        *rls_operations("gst_registration"),
        *rls_operations("gst_recon_run"),
        *rls_operations("gst_register_invoice"),
        *rls_operations("gst_gstr2b_invoice"),
        *rls_operations("gst_recon_match"),
        *append_only_operations("gst_recon_decision"),
    ]
