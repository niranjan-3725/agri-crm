"""
Sprint 11 — Migrate existing ACTIVE documents to SUBMITTED.

All existing documents with status='ACTIVE' already have ledger impact
(stock was mutated when they were created). They are SUBMITTED in the
new state machine terminology.
"""

from django.db import migrations


def active_to_submitted(apps, schema_editor):
    for model_name in ('PurchaseInvoice', 'SalesInvoice', 'SalesReturn', 'PurchaseReturn'):
        Model = apps.get_model('transactions', model_name)
        Model.objects.filter(status='ACTIVE').update(status='SUBMITTED')


def submitted_to_active(apps, schema_editor):
    for model_name in ('PurchaseInvoice', 'SalesInvoice', 'SalesReturn', 'PurchaseReturn'):
        Model = apps.get_model('transactions', model_name)
        Model.objects.filter(status='SUBMITTED').update(status='ACTIVE')


class Migration(migrations.Migration):

    dependencies = [
        ('transactions', '0019_sprint11_document_state_machine'),
    ]

    operations = [
        migrations.RunPython(active_to_submitted, submitted_to_active),
    ]
