"""
Sprint 24: Data migration — promote existing is_received=True DRAFT invoices to RECEIVED status.

Django CharField choices are not DB-enforced in MySQL, so no schema change is needed.
This purely fixes existing data created by Sprint 23's hybrid pattern where goods were
received but the document was left in DRAFT status (there was no RECEIVED state yet).
"""
from django.db import migrations


def forwards(apps, schema_editor):
    PurchaseInvoice = apps.get_model('transactions', 'PurchaseInvoice')
    updated = PurchaseInvoice.objects.filter(
        is_received=True, status='DRAFT'
    ).update(status='RECEIVED')
    if updated:
        print(f"\nSprint 24 migration: promoted {updated} invoice(s) from DRAFT → RECEIVED.")


def backwards(apps, schema_editor):
    PurchaseInvoice = apps.get_model('transactions', 'PurchaseInvoice')
    PurchaseInvoice.objects.filter(
        is_received=True, status='RECEIVED'
    ).update(status='DRAFT')


class Migration(migrations.Migration):

    dependencies = [
        ('transactions', '0026_purchaseinvoice_is_received'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
