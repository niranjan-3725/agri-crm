"""
Sprint 25: Honest Unique Constraint — remove global unique=True on invoice_number
and replace with a conditional UniqueConstraint scoped to SUBMITTED documents only.

This allows users to re-use an invoice number after a previous attempt was CANCELLED,
which matches real-world re-entry workflows (the supplier issues the same number again).

For MySQL (which does not support partial/conditional indexes at the DB level), Django
enforces this constraint at the application layer via validate_unique().
"""
from django.db import migrations, models
import django.db.models.functions


class Migration(migrations.Migration):

    dependencies = [
        ('transactions', '0027_purchaseinvoice_received_status'),
    ]

    operations = [
        # 1. Drop the global UNIQUE INDEX on invoice_number (was unique=True field-level)
        migrations.AlterField(
            model_name='purchaseinvoice',
            name='invoice_number',
            field=models.CharField(max_length=50),
        ),
        # 2. Add the conditional UniqueConstraint: uniqueness only for SUBMITTED docs
        migrations.AddConstraint(
            model_name='purchaseinvoice',
            constraint=models.UniqueConstraint(
                fields=['invoice_number', 'supplier'],
                condition=models.Q(status='SUBMITTED'),
                name='unique_active_invoice',
            ),
        ),
    ]
