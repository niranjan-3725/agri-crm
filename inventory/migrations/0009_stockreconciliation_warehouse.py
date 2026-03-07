"""
Sprint 15 — INV-03: Add warehouse FK to StockReconciliation.

Existing rows are left with warehouse=NULL (null=True, blank=True).
A future data-migration can backfill them by looking up the linked
StockMovement (reference_document_type='StockReconciliation',
reference_document_id=recon.pk).
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0008_sprint10_valuation_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='stockreconciliation',
            name='warehouse',
            field=models.ForeignKey(
                blank=True,
                help_text='Warehouse where the physical stock count was performed.',
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='reconciliations',
                to='inventory.warehouse',
            ),
        ),
    ]
