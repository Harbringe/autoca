from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('classify', '0024_classification_ledger_suggestion'),
    ]

    operations = [
        migrations.AddField(
            model_name='party',
            name='pay_account_enc',
            field=models.BinaryField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='party',
            name='pay_account_last4',
            field=models.CharField(blank=True, db_default='', default='', max_length=4),
        ),
        migrations.AddField(
            model_name='party',
            name='pay_ifsc',
            field=models.CharField(blank=True, db_default='', default='', max_length=11),
        ),
        migrations.AddField(
            model_name='party',
            name='pay_account_name',
            field=models.CharField(blank=True, db_default='', default='', max_length=200),
        ),
    ]
