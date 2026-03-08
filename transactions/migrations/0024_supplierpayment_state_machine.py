from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('transactions', '0023_sprint_returns_model_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='supplierpayment',
            name='status',
            field=models.CharField(
                choices=[('SUBMITTED', 'Submitted'), ('CANCELLED', 'Cancelled')],
                default='SUBMITTED',
                max_length=20,
            ),
        ),
    ]
