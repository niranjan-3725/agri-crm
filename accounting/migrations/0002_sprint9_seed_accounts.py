"""
Sprint 9 — Seed the essential Chart of Accounts.

Creates four system accounts required by the GL Posting Engine:
  1. Stock In Hand (Asset)
  2. Cost of Goods Sold (Expense)
  3. Stock Received But Not Billed (Liability)
  4. Inventory Adjustment (Expense)
"""

from django.db import migrations


ACCOUNTS = [
    ('Stock In Hand', 'ASSET'),
    ('Cost of Goods Sold', 'EXPENSE'),
    ('Stock Received But Not Billed', 'LIABILITY'),
    ('Inventory Adjustment', 'EXPENSE'),
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
        ('accounting', '0001_sprint9_gl_models'),
    ]

    operations = [
        migrations.RunPython(seed_accounts, reverse_seed),
    ]
