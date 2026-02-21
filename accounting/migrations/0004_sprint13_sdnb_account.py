"""
Sprint 13 — Seed 'Stock Delivered But Not Billed' account.

This clearing account is used when goods are delivered (DeliveryNote)
but the Sales Invoice has not yet been created.
"""

from django.db import migrations


ACCOUNTS = [
    ('Stock Delivered But Not Billed', 'ASSET'),
]


def seed_accounts(apps, schema_editor):
    Account = apps.get_model('accounting', 'Account')
    for name, acct_type in ACCOUNTS:
        Account.objects.get_or_create(
            name=name,
            defaults={'account_type': acct_type, 'is_system_account': True},
        )


def reverse_seed(apps, schema_editor):
    Account = apps.get_model('accounting', 'Account')
    Account.objects.filter(name__in=[a[0] for a in ACCOUNTS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('accounting', '0003_sprint12_ar_ap_accounts'),
    ]

    operations = [
        migrations.RunPython(seed_accounts, reverse_seed),
    ]
