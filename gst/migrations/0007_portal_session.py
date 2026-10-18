from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("gst", "0006_gstin_check_rls")]

    operations = [
        migrations.AddField(model_name="gstregistration", name="portal_username_enc", field=models.BinaryField(blank=True, null=True)),
        migrations.AddField(model_name="gstregistration", name="portal_session_enc", field=models.BinaryField(blank=True, null=True)),
        migrations.AddField(model_name="gstregistration", name="portal_session_expires", field=models.DateTimeField(blank=True, null=True)),
    ]
