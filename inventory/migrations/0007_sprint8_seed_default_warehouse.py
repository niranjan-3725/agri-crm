"""
Sprint 8 — Data migration: seed the default 'Main Warehouse'.

1. Creates a 'Main Warehouse' record.
2. For every Batch with current_quantity > 0, creates a StockBin in the
   default warehouse with actual_qty = batch.current_quantity.
3. Back-fills existing StockMovement rows with the default warehouse FK.
"""

from django.db import migrations


def seed_default_warehouse(apps, schema_editor):
    Warehouse = apps.get_model('inventory', 'Warehouse')
    Batch = apps.get_model('inventory', 'Batch')
    StockBin = apps.get_model('inventory', 'StockBin')
    StockMovement = apps.get_model('inventory', 'StockMovement')

    # 1. Create the default warehouse
    main_wh, _ = Warehouse.objects.get_or_create(
        name='Main Warehouse',
        defaults={'location': 'Default location', 'is_active': True},
    )

    # 2. Create StockBin rows from existing Batch data
    for batch in Batch.objects.all():
        StockBin.objects.get_or_create(
            warehouse=main_wh,
            batch=batch,
            defaults={'actual_qty': batch.current_quantity},
        )

    # 3. Back-fill StockMovement.warehouse for all existing rows
    StockMovement.objects.filter(warehouse__isnull=True).update(warehouse=main_wh)


def reverse_seed(apps, schema_editor):
    """Reverse: delete StockBin rows and the default warehouse."""
    StockBin = apps.get_model('inventory', 'StockBin')
    Warehouse = apps.get_model('inventory', 'Warehouse')
    StockMovement = apps.get_model('inventory', 'StockMovement')

    StockMovement.objects.filter(warehouse__name='Main Warehouse').update(warehouse=None)
    StockBin.objects.filter(warehouse__name='Main Warehouse').delete()
    Warehouse.objects.filter(name='Main Warehouse').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0006_sprint8_warehouse_stockbin'),
    ]

    operations = [
        migrations.RunPython(seed_default_warehouse, reverse_seed),
    ]
