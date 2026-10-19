from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0017_client_profile'),
    ]

    operations = [
        migrations.AddField(
            model_name='client',
            name='assistant_paused_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
