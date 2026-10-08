from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('classify', '0022_ledger_nce_line'),
    ]

    operations = [
        migrations.AddField(
            model_name='ledgeraccount',
            name='nce_section',
            field=models.CharField(blank=True, db_default='', default='', max_length=80),
        ),
        migrations.AddField(
            model_name='party',
            name='msme',
            field=models.BooleanField(db_default=False, default=False),
        ),
        migrations.AddField(
            model_name='party',
            name='udyam_no',
            field=models.CharField(blank=True, db_default='', default='', max_length=19),
        ),
    ]
