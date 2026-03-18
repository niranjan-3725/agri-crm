from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('transactions', '0025_customerpayment_status'),
    ]

    operations = [
        migrations.AddField(
            model_name='purchaseinvoice',
            name='is_received',
            field=models.BooleanField(default=False),
        ),
    ]
