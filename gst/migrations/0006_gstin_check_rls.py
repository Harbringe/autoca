"""Tenant isolation for the GSTIN check table (separate from 0005 for the reason 0002 gives)."""

from django.db import migrations

from core.db.rls import rls_operations


class Migration(migrations.Migration):
    dependencies = [("gst", "0005_gstin_check")]

    operations = [*rls_operations("gst_gstin_check")]
