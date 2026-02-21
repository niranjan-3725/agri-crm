"""
Sprint 12 — Seed AR/AP, Revenue, Tax, and Cash accounts.

Expands the Chart of Accounts for full double-entry invoice
and payment accounting.
"""

from django.db import migrations


ACCOUNTS = [
    ('Accounts Receivable', 'ASSET'),
    ('Accounts Payable', 'LIABILITY'),
    ('Sales Revenue', 'INCOME'),
    ('CGST Payable', 'LIABILITY'),
    ('SGST Payable', 'LIABILITY'),
    ('CGST Receivable', 'ASSET'),
    ('SGST Receivable', 'ASSET'),
    ('Cash / Bank', 'ASSET'),
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
        ('accounting', '0002_sprint9_seed_accounts'),
    ]

    operations = [
        migrations.RunPython(seed_accounts, reverse_seed),
    ]
