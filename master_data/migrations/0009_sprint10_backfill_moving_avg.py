"""
Sprint 10 — Backfill Product.moving_average_price.

For each product, compute a weighted average from its batches' purchase_price
and current_quantity.  If a product has no stock, use the latest batch's
purchase_price as a fallback.
"""

from django.db import migrations
from decimal import Decimal


def backfill_moving_average(apps, schema_editor):
    Product = apps.get_model('master_data', 'Product')
    Batch = apps.get_model('inventory', 'Batch')

    for product in Product.objects.all():
        batches = Batch.objects.filter(product=product, current_quantity__gt=0)

        if batches.exists():
            total_value = Decimal('0.00')
            total_qty = 0
            for b in batches:
                total_value += b.current_quantity * b.purchase_price
                total_qty += b.current_quantity

            if total_qty > 0:
                product.moving_average_price = total_value / total_qty
            else:
                product.moving_average_price = Decimal('0.00')
        else:
            # No stock — use latest batch price as fallback
            latest_batch = Batch.objects.filter(product=product).order_by('-id').first()
            if latest_batch:
                product.moving_average_price = latest_batch.purchase_price
            else:
                product.moving_average_price = Decimal('0.00')

        product.save(update_fields=['moving_average_price'])


def reverse_backfill(apps, schema_editor):
    Product = apps.get_model('master_data', 'Product')
    Product.objects.all().update(moving_average_price=Decimal('0.00'))


class Migration(migrations.Migration):

    dependencies = [
        ('master_data', '0008_sprint10_valuation_fields'),
        ('inventory', '0008_sprint10_valuation_fields'),
    ]

    operations = [
        migrations.RunPython(backfill_moving_average, reverse_backfill),
    ]
