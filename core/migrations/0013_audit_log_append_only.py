"""The audit log can only be added to, in the database and not only in Python.

``AuditLog.save()`` refuses an edit, but ``QuerySet.update()`` and ``.delete()`` go round it, so a bug or an injection in the
web process could rewrite or erase the record of who did what. The journal and the other ledgers of record already hold this
in the database; this brings the audit log to the same footing: the app role may select and insert, and a trigger refuses
anything else.
"""

from django.db import migrations

from core.db.rls import append_only_operations


class Migration(migrations.Migration):
    dependencies = [("core", "0012_client_business_profile")]

    operations = [*append_only_operations("core_audit_log")]
