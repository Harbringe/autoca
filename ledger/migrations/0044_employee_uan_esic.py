from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ledger', '0043_stock_item_aliases'),
    ]

    operations = [
        migrations.AddField(
            model_name='employee',
            name='uan',
            field=models.CharField(blank=True, db_default='', default='', max_length=12),
        ),
        migrations.AddField(
            model_name='employee',
            name='esic_number',
            field=models.CharField(blank=True, db_default='', default='', max_length=17),
        ),
    ]
