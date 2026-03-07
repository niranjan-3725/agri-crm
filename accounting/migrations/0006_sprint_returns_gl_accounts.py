"""
Returns Module — Seed Contra-Revenue and Contra-Expense GL accounts.

Adds the four accounts required for full Credit Note / Debit Note
double-entry accounting on Sales Returns and Purchase Returns:

  Sales Returns          INCOME   (contra-revenue — reduces Sales Revenue)
  Purchase Returns       EXPENSE  (contra-expense — reduces Purchase expense)
  CGST Input Recoverable ASSET    (GST input credit reclaimed on purchase return)
  SGST Input Recoverable ASSET    (GST input credit reclaimed on purchase return)
"""

from django.db import migrations

ACCOUNTS = [
    # Contra-revenue: debited when a customer return reduces recognised revenue
    ('Sales Returns', 'INCOME'),
    # Contra-expense: credited when a supplier return reduces recorded purchases
    ('Purchase Returns', 'EXPENSE'),
    # Input GST credit reclaimed when goods are returned to a supplier
    ('CGST Input Recoverable', 'ASSET'),
    ('SGST Input Recoverable', 'ASSET'),
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
    # Only delete if no GL entries reference them (safe rollback)
    Account.objects.filter(
        name__in=[a[0] for a in ACCOUNTS],
        gl_entries__isnull=True,
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('accounting', '0005_sprint16_tax_exclusive_valuation'),
    ]

    operations = [
        migrations.RunPython(seed_accounts, reverse_seed),
    ]
