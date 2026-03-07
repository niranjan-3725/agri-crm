"""
Returns Module Refactor — Model field additions.

BUG-05 fix: Add ``unit_price_at_invoice`` to SalesReturnItem so the GL
engine can compute proportional tax reversals without relying on the
original invoice being intact.

BUG-07 fix: Add ``warehouse`` FK to both SalesReturnItem and
PurchaseReturnItem so multi-warehouse stock routing works correctly.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0008_sprint10_valuation_fields'),
        ('transactions', '0022_sprint14_order_pipeline'),
    ]

    operations = [
        # SalesReturnItem: store the invoiced unit price at return creation
        migrations.AddField(
            model_name='salesreturnitem',
            name='unit_price_at_invoice',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text='Unit price from the original invoice, frozen at return creation.',
                max_digits=12,
                null=True,
            ),
        ),
        # SalesReturnItem: warehouse destination for returned stock
        migrations.AddField(
            model_name='salesreturnitem',
            name='warehouse',
            field=models.ForeignKey(
                blank=True,
                help_text='Warehouse stock returns to. Defaults to primary warehouse if blank.',
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                to='inventory.warehouse',
            ),
        ),
        # PurchaseReturnItem: warehouse source for outgoing stock
        migrations.AddField(
            model_name='purchasereturnitem',
            name='warehouse',
            field=models.ForeignKey(
                blank=True,
                help_text='Warehouse stock leaves from. Defaults to primary warehouse if blank.',
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                to='inventory.warehouse',
            ),
        ),
    ]
