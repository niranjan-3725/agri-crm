"""
Migration 0025: Add status field to CustomerPayment.

All existing rows default to 'SUBMITTED' — they were created and GL-posted
atomically, so they are valid submitted payments.  There are no DRAFT rows.

Playbook reference: Rule 13.1 — CustomerPayment must have a status field.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('transactions', '0024_supplierpayment_state_machine'),
    ]

    operations = [
        migrations.AddField(
            model_name='customerpayment',
            name='status',
            field=models.CharField(
                choices=[('SUBMITTED', 'Submitted'), ('CANCELLED', 'Cancelled')],
                default='SUBMITTED',
                max_length=20,
            ),
        ),
    ]
