"""
accounting.models
~~~~~~~~~~~~~~~~~

Sprint 9: General Ledger — Double-Entry Accounting Models.

Provides an ``Account`` chart-of-accounts and an ``GLEntry`` model
that records every financial posting as a balanced debit/credit pair.
"""

from django.db import models


class Account(models.Model):
    """A named account in the Chart of Accounts."""

    ACCOUNT_TYPE_CHOICES = [
        ('ASSET', 'Asset'),
        ('LIABILITY', 'Liability'),
        ('EQUITY', 'Equity'),
        ('INCOME', 'Income'),
        ('EXPENSE', 'Expense'),
    ]

    name = models.CharField(max_length=100, unique=True)
    account_type = models.CharField(max_length=20, choices=ACCOUNT_TYPE_CHOICES)
    is_system_account = models.BooleanField(
        default=False,
        help_text="System accounts cannot be deleted.",
    )

    class Meta:
        ordering = ['account_type', 'name']

    def __str__(self):
        return f"{self.name} ({self.get_account_type_display()})"

    def delete(self, *args, **kwargs):
        if self.is_system_account:
            from django.core.exceptions import ValidationError
            raise ValidationError(
                f"Cannot delete system account '{self.name}'."
            )
        super().delete(*args, **kwargs)


class GLEntry(models.Model):
    """A single line in a General Ledger posting.

    Every stock movement generates **two** GLEntry rows (debit + credit)
    that must always balance to zero.  This is enforced by
    ``make_gl_entries()`` before saving.
    """

    account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name='gl_entries',
    )
    debit = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
        help_text="Debit amount (positive or zero).",
    )
    credit = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
        help_text="Credit amount (positive or zero).",
    )
    posting_date = models.DateTimeField(auto_now_add=True)
    reference_type = models.CharField(
        max_length=50,
        help_text="Source document type, e.g. 'PurchaseInvoice'.",
    )
    reference_id = models.PositiveIntegerField(
        help_text="PK of the source document.",
    )
    remarks = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(
                fields=['reference_type', 'reference_id'],
                name='idx_gl_ref_doc',
            ),
        ]

    def __str__(self):
        side = f"Dr {self.debit}" if self.debit else f"Cr {self.credit}"
        return (
            f"GL #{self.pk}: {self.account.name} | {side} "
            f"[{self.reference_type} #{self.reference_id}]"
        )
