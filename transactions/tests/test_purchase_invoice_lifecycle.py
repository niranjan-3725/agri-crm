"""
Sprint 20 — Purchase Invoice Lifecycle Tests.

Validates the DRAFT → SUBMITTED → CANCELLED state machine and the key
accounting invariant: SRNB (Stock Received But Not Billed) nets to ZERO
after both the PurchaseReceipt stock-GL and the PurchaseInvoice AP-GL
have been posted.

Flow
----
1.  create_purchase view saves invoice in DRAFT state.
    - No GL entries posted.
    - No stock movements created.
2.  submit_purchase_invoice view calls invoice.submit().
    - Auto-creates and submits a PurchaseReceipt (stock + SRNB GL).
    - Posts AP GL: Dr SRNB / Dr CGST Recv / Dr SGST Recv / Cr AP.
    - Net SRNB balance = Cr (from receipt) − Dr (from invoice) = 0.
3.  cancel_purchase_invoice view calls invoice.cancel().
    - Reverses AP GL (reversing entries, originals preserved).
    - Cancels PurchaseReceipt (reverses stock and SRNB GL).
    - status → CANCELLED.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.test import TestCase

from accounting.models import Account, GLEntry
from inventory.models import Batch, StockMovement
from master_data.models import Category, Manufacturer, Product, Supplier
from transactions.models import PurchaseInvoice, PurchaseItem


class PurchaseInvoiceLifecycleTests(TestCase):
    """Integration tests for the PurchaseInvoice state machine."""

    @classmethod
    def setUpTestData(cls):
        """Shared fixtures — created once for the whole TestCase."""
        cls.cat = Category.objects.create(
            name='SP20-Fertilisers',
            cgst_rate=Decimal('9.00'),
            sgst_rate=Decimal('9.00'),
        )
        cls.mfr = Manufacturer.objects.create(name='SP20-Mfr')
        cls.product = Product.objects.create(
            name='SP20-Product',
            hsn_code='31042000',
            unit_type='Bag',
            category=cls.cat,
            manufacturer=cls.mfr,
        )
        cls.supplier = Supplier.objects.create(
            name='Sprint20 Supplier',
            phone='9999999999',
            gstin='27AABCU9603R1ZX',
            address='Test Address, Mumbai',
        )

    def _make_draft_invoice(
        self,
        rate: Decimal = Decimal('100.00'),
        qty: int = 5,
        invoice_suffix: str = '',
    ) -> tuple:
        """Helper: create a DRAFT PurchaseInvoice with a single line item.

        Returns (invoice, batch) so callers can inspect stock state.
        """
        batch = Batch.objects.create(
            product=self.product,
            batch_number=f'B-SP20-{Batch.objects.count()}{invoice_suffix}',
            purchase_price=rate,
            mrp=Decimal('150.00'),
            base_selling_price=Decimal('140.00'),
            current_quantity=0,
        )

        # Mirrors what create_purchase view does: qty × (rate + tax) per unit
        tax_rate = self.cat.total_tax          # 18 (Decimal)
        tax_per_unit = rate * (tax_rate / Decimal('100'))
        total_tax = tax_per_unit * qty
        net_cost_per_unit = rate + tax_per_unit
        total_line = net_cost_per_unit * qty

        invoice = PurchaseInvoice.objects.create(
            supplier=self.supplier,
            invoice_number=f'SP20-INV-{PurchaseInvoice.objects.count()}{invoice_suffix}',
            date='2026-03-04',
            total_amount=total_line,
        )
        PurchaseItem.objects.create(
            invoice=invoice,
            batch=batch,
            quantity=qty,
            basic_rate=rate,
            tax_amount=total_tax,
            selling_price=Decimal('140.00'),
            profit_margin=Decimal('18.00'),
            total_amount=total_line,
        )
        return invoice, batch

    # ------------------------------------------------------------------
    # 1. DRAFT State: no ledger impact
    # ------------------------------------------------------------------

    def test_create_sets_draft_status(self):
        """Newly created invoice must be DRAFT — no ledger impact."""
        invoice, _ = self._make_draft_invoice()
        self.assertEqual(
            invoice.status, 'DRAFT',
            "create_purchase must save invoice as DRAFT, never auto-submit.",
        )

    def test_draft_has_no_gl_entries(self):
        """A DRAFT invoice must NOT post any GL entries."""
        invoice, _ = self._make_draft_invoice()
        gl_count = GLEntry.objects.filter(
            reference_type='PurchaseInvoice',
            reference_id=invoice.pk,
        ).count()
        self.assertEqual(
            gl_count, 0,
            "DRAFT invoice must not post GL entries — ledger must be untouched.",
        )

    def test_draft_has_no_stock_movements(self):
        """A DRAFT invoice must NOT create any stock movements."""
        invoice, batch = self._make_draft_invoice()
        sm_count = StockMovement.objects.filter(batch=batch).count()
        self.assertEqual(
            sm_count, 0,
            "DRAFT invoice must not move stock.",
        )
        batch.refresh_from_db()
        self.assertEqual(
            batch.current_quantity, 0,
            "Batch.current_quantity must remain 0 for a DRAFT invoice.",
        )

    # ------------------------------------------------------------------
    # 2. SUBMITTED State: GL and stock posted
    # ------------------------------------------------------------------

    def test_submit_transitions_to_submitted(self):
        """submit() must transition DRAFT → SUBMITTED."""
        invoice, _ = self._make_draft_invoice()
        invoice.submit()
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, 'SUBMITTED')

    def test_submit_auto_creates_purchase_receipt(self):
        """submit() without a linked receipt must auto-create one."""
        invoice, _ = self._make_draft_invoice()
        self.assertIsNone(
            invoice.purchase_receipt,
            "Pre-submit: invoice must not yet have a receipt.",
        )
        invoice.submit()
        invoice.refresh_from_db()
        self.assertIsNotNone(invoice.purchase_receipt)
        self.assertEqual(invoice.purchase_receipt.status, 'SUBMITTED')

    def test_submit_increases_stock(self):
        """submit() must increase batch.current_quantity by the invoiced qty."""
        invoice, batch = self._make_draft_invoice(qty=5)
        invoice.submit()
        batch.refresh_from_db()
        self.assertEqual(batch.current_quantity, 5)

    def test_submit_posts_ap_gl_entries(self):
        """submit() must post AP GL entries for the PurchaseInvoice."""
        invoice, _ = self._make_draft_invoice()
        invoice.submit()
        gl_count = GLEntry.objects.filter(
            reference_type='PurchaseInvoice',
            reference_id=invoice.pk,
        ).count()
        self.assertGreater(
            gl_count, 0,
            "submit() must post AP GL entries (SRNB Dr + Tax Dr + AP Cr).",
        )

    def test_submit_posts_balanced_gl_entries(self):
        """AP GL entries must be perfectly balanced (debits == credits)."""
        invoice, _ = self._make_draft_invoice()
        invoice.submit()
        ap_entries = GLEntry.objects.filter(
            reference_type='PurchaseInvoice',
            reference_id=invoice.pk,
        )
        total_debit = ap_entries.aggregate(d=Sum('debit'))['d'] or Decimal('0')
        total_credit = ap_entries.aggregate(c=Sum('credit'))['c'] or Decimal('0')
        self.assertEqual(
            total_debit, total_credit,
            f"AP GL entries must balance. Dr={total_debit}, Cr={total_credit}.",
        )

    # ------------------------------------------------------------------
    # 3. SRNB Clearing Assertion — Core Sprint 20 Test
    # ------------------------------------------------------------------

    def test_srnb_nets_to_zero_after_invoice_submitted(self):
        """Core Sprint 20: SRNB must net to ZERO after both GLS are posted.

        Sequence:
          PurchaseReceipt.submit() → Dr Stock In Hand / Cr SRNB   (stock GL)
          PurchaseInvoice.submit() → Dr SRNB / Cr AP              (AP GL)

        The two SRNB entries cancel: net balance = Cr − Dr = 0.
        """
        invoice, _ = self._make_draft_invoice(
            rate=Decimal('100.00'), qty=5,
        )
        invoice.submit()

        srnb = Account.objects.get(name='Stock Received But Not Billed')
        srnb_entries = GLEntry.objects.filter(account=srnb)

        total_debit = srnb_entries.aggregate(d=Sum('debit'))['d'] or Decimal('0')
        total_credit = srnb_entries.aggregate(c=Sum('credit'))['c'] or Decimal('0')

        self.assertEqual(
            total_debit,
            total_credit,
            f"SRNB must net to zero after PurchaseInvoice submitted. "
            f"Dr={total_debit}, Cr={total_credit}. "
            "Possible cause: post_stock_gl and post_purchase_invoice_gl "
            "are using different base amounts.",
        )

    def test_srnb_nets_to_zero_for_multiple_independent_invoices(self):
        """SRNB must remain zero when multiple invoices are each submitted."""
        invoice1, _ = self._make_draft_invoice(
            rate=Decimal('100.00'), qty=3, invoice_suffix='-A',
        )
        invoice2, _ = self._make_draft_invoice(
            rate=Decimal('200.00'), qty=2, invoice_suffix='-B',
        )
        invoice1.submit()
        invoice2.submit()

        srnb = Account.objects.get(name='Stock Received But Not Billed')
        srnb_entries = GLEntry.objects.filter(account=srnb)

        total_debit = srnb_entries.aggregate(d=Sum('debit'))['d'] or Decimal('0')
        total_credit = srnb_entries.aggregate(c=Sum('credit'))['c'] or Decimal('0')

        self.assertEqual(
            total_debit,
            total_credit,
            "SRNB must net to zero across multiple submitted invoices.",
        )

    # ------------------------------------------------------------------
    # 4. CANCELLED State: entries reversed, stock restored
    # ------------------------------------------------------------------

    def test_cancel_transitions_to_cancelled(self):
        """cancel() must transition SUBMITTED → CANCELLED."""
        invoice, _ = self._make_draft_invoice()
        invoice.submit()
        invoice.cancel()
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, 'CANCELLED')

    def test_cancel_creates_reversing_gl_entries_not_deletes(self):
        """cancel() must DOUBLE the AP GL row count via reversing entries.

        The original AP entries must be preserved for audit compliance.
        """
        invoice, _ = self._make_draft_invoice()
        invoice.submit()

        original_count = GLEntry.objects.filter(
            reference_type='PurchaseInvoice',
            reference_id=invoice.pk,
        ).count()
        self.assertGreater(original_count, 0)

        invoice.cancel()

        final_count = GLEntry.objects.filter(
            reference_type='PurchaseInvoice',
            reference_id=invoice.pk,
        ).count()
        self.assertEqual(
            final_count, original_count * 2,
            "cancel() must add reversing entries without deleting originals.",
        )

    def test_cancel_nets_ap_gl_to_zero(self):
        """After cancellation the AP GL net for this invoice must be zero."""
        invoice, _ = self._make_draft_invoice()
        invoice.submit()
        invoice.cancel()

        ap_entries = GLEntry.objects.filter(
            reference_type='PurchaseInvoice',
            reference_id=invoice.pk,
        )
        total_debit = ap_entries.aggregate(d=Sum('debit'))['d'] or Decimal('0')
        total_credit = ap_entries.aggregate(c=Sum('credit'))['c'] or Decimal('0')
        self.assertEqual(
            total_debit, total_credit,
            "AP GL must net to zero after cancellation.",
        )

    def test_cancel_reverses_stock(self):
        """cancel() must restore batch.current_quantity to its pre-purchase value."""
        invoice, batch = self._make_draft_invoice(qty=5)
        invoice.submit()
        batch.refresh_from_db()
        self.assertEqual(batch.current_quantity, 5, "Stock should be 5 after submit.")

        invoice.cancel()
        batch.refresh_from_db()
        self.assertEqual(
            batch.current_quantity, 0,
            "Stock must return to 0 after invoice is cancelled.",
        )

    def test_draft_invoice_cannot_be_cancelled(self):
        """Calling cancel() on a DRAFT invoice must raise ValidationError."""
        invoice, _ = self._make_draft_invoice()
        with self.assertRaises(ValidationError):
            invoice.cancel()

    def test_cancelled_invoice_cannot_be_resubmitted(self):
        """Calling submit() on a CANCELLED invoice must raise ValidationError."""
        invoice, _ = self._make_draft_invoice()
        invoice.submit()
        invoice.cancel()
        with self.assertRaises(ValidationError):
            invoice.submit()
