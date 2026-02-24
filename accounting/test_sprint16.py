"""
Sprint 16 Test Suite — Tax-Exclusive Valuation & SRNB Reconciliation.

Validates:
1. batch.purchase_price is strictly pre-tax (base rate).
2. PR GL posts Stock In Hand / SRNB at the base amount.
3. PI GL posts SRNB / Tax / AP so that SRNB nets to zero.
4. Full lifecycle: Submit → SRNB clears → Cancel → everything reverses.
5. Moving average uses tax-exclusive prices.
"""
from decimal import Decimal
from django.test import TestCase
from django.db.models import Sum

from master_data.models import Product, Category, Manufacturer
from inventory.models import Batch, Warehouse
from transactions.models import (
    PurchaseInvoice, PurchaseItem, PurchaseReceipt, Supplier,
)
from accounting.models import GLEntry, Account


class Sprint16TaxExclusiveValuationTest(TestCase):
    """Full test suite for Sprint 16: Tax-Exclusive Stock Valuation."""

    @classmethod
    def setUpTestData(cls):
        """Create shared test fixtures."""
        # Ensure required GL accounts exist
        for name in [
            'Stock In Hand', 'Stock Received But Not Billed',
            'Accounts Payable', 'CGST Receivable', 'SGST Receivable',
            'Cost of Goods Sold', 'Sales Revenue',
            'Accounts Receivable', 'CGST Payable', 'SGST Payable',
            'Cash', 'Inventory Adjustment',
        ]:
            Account.objects.get_or_create(name=name, defaults={'account_type': 'ASSET'})

        Warehouse.objects.get_or_create(
            name='Main Warehouse', defaults={'location': 'Default'}
        )

        cls.manufacturer = Manufacturer.objects.create(name='Sprint16Mfg')
        cls.category = Category.objects.create(
            name='Sprint16Cat',
            cgst_rate=Decimal('9.00'),   # 9% CGST
            sgst_rate=Decimal('9.00'),   # 9% SGST  → total_tax = 18%
        )
        cls.product = Product.objects.create(
            name='Sprint16Product',
            category=cls.category,
            manufacturer=cls.manufacturer,
        )
        cls.supplier = Supplier.objects.create(
            name='Sprint16Supplier',
            phone='9999999999',
            gstin='29SPRINT16GST1Z5',
            address='Test Address',
        )

    def _create_draft_purchase(self, qty=100, basic_rate=100):
        """Helper: Create a DRAFT purchase invoice with one item."""
        tax_rate = Decimal('18.00')
        tax_per_unit = Decimal(str(basic_rate)) * (tax_rate / 100)
        total_tax = tax_per_unit * qty
        base_amount = Decimal(str(basic_rate)) * qty
        total_amount = base_amount + total_tax

        batch = Batch.objects.create(
            product=self.product,
            batch_number=f'S16-{Batch.objects.count() + 1}',
            purchase_price=Decimal(str(basic_rate)),  # Sprint 16: Pre-tax!
            mrp=Decimal('150.00'),
            base_selling_price=Decimal('130.00'),
            current_quantity=0,
        )

        invoice = PurchaseInvoice.objects.create(
            supplier=self.supplier,
            invoice_number=f'S16-INV-{PurchaseInvoice.objects.count() + 1}',
            date='2026-02-22',
            total_amount=total_amount,
        )

        PurchaseItem.objects.create(
            invoice=invoice,
            batch=batch,
            quantity=qty,
            basic_rate=Decimal(str(basic_rate)),
            tax_amount=total_tax,
            selling_price=Decimal('130.00'),
            profit_margin=Decimal('30.00'),
            total_amount=total_amount,
        )

        return invoice, batch

    # ── Test 1: batch.purchase_price is pre-tax ──
    def test_batch_purchase_price_is_pretax(self):
        """batch.purchase_price must equal the basic_rate, NOT the tax-inclusive cost."""
        invoice, batch = self._create_draft_purchase(qty=100, basic_rate=100)
        self.assertEqual(batch.purchase_price, Decimal('100'))

    # ── Test 2: PR GL uses base amount ──
    def test_pr_gl_uses_base_amount(self):
        """PurchaseReceipt GL: Dr Stock In Hand 10,000 / Cr SRNB 10,000."""
        invoice, batch = self._create_draft_purchase(qty=100, basic_rate=100)
        invoice.submit()

        pr = invoice.purchase_receipt
        self.assertIsNotNone(pr)

        pr_gl = GLEntry.objects.filter(
            reference_type='PurchaseReceipt', reference_id=pr.pk,
        )

        stock_in_hand_dr = pr_gl.filter(account__name='Stock In Hand').aggregate(
            total=Sum('debit'))['total'] or Decimal('0')
        srnb_cr = pr_gl.filter(account__name='Stock Received But Not Billed').aggregate(
            total=Sum('credit'))['total'] or Decimal('0')

        # 100 units × ₹100 = ₹10,000 (NOT ₹11,800)
        self.assertEqual(stock_in_hand_dr, Decimal('10000'))
        self.assertEqual(srnb_cr, Decimal('10000'))

    # ── Test 3: PI GL clears SRNB ──
    def test_pi_gl_clears_srnb(self):
        """PurchaseInvoice GL: Dr SRNB 10,000 / Dr Tax 1,800 / Cr AP 11,800."""
        invoice, batch = self._create_draft_purchase(qty=100, basic_rate=100)
        invoice.submit()

        pi_gl = GLEntry.objects.filter(
            reference_type='PurchaseInvoice', reference_id=invoice.pk,
        )

        srnb_dr = pi_gl.filter(account__name='Stock Received But Not Billed').aggregate(
            total=Sum('debit'))['total'] or Decimal('0')
        cgst_dr = pi_gl.filter(account__name='CGST Receivable').aggregate(
            total=Sum('debit'))['total'] or Decimal('0')
        sgst_dr = pi_gl.filter(account__name='SGST Receivable').aggregate(
            total=Sum('debit'))['total'] or Decimal('0')
        ap_cr = pi_gl.filter(account__name='Accounts Payable').aggregate(
            total=Sum('credit'))['total'] or Decimal('0')

        self.assertEqual(srnb_dr, Decimal('10000'))
        self.assertEqual(cgst_dr + sgst_dr, Decimal('1800'))
        self.assertEqual(ap_cr, Decimal('11800'))

    # ── Test 4: SRNB balance is exactly ZERO after submit ──
    def test_srnb_balance_is_zero(self):
        """The SRNB clearing account MUST net to zero after PR + PI GL."""
        invoice, batch = self._create_draft_purchase(qty=100, basic_rate=100)
        invoice.submit()

        pr = invoice.purchase_receipt
        # Gather all SRNB entries from both PR and PI
        srnb_entries = GLEntry.objects.filter(
            account__name='Stock Received But Not Billed',
            reference_type__in=['PurchaseReceipt', 'PurchaseInvoice'],
            reference_id__in=[pr.pk, invoice.pk],
        )

        total_debit = srnb_entries.aggregate(s=Sum('debit'))['s'] or Decimal('0')
        total_credit = srnb_entries.aggregate(s=Sum('credit'))['s'] or Decimal('0')

        srnb_balance = total_debit - total_credit
        self.assertEqual(srnb_balance, Decimal('0'),
                         f"SRNB balance should be 0, got {srnb_balance}")

    # ── Test 5: Inventory valued at base amount ──
    def test_inventory_valued_at_base(self):
        """After submit, batch stock value = qty × purchase_price (pre-tax)."""
        invoice, batch = self._create_draft_purchase(qty=100, basic_rate=100)
        invoice.submit()

        batch.refresh_from_db()
        self.assertEqual(batch.current_quantity, 100)
        self.assertEqual(batch.purchase_price, Decimal('100'))

        # Stock value = 100 × 100 = 10,000
        stock_value = batch.current_quantity * batch.purchase_price
        self.assertEqual(stock_value, Decimal('10000'))

    # ── Test 6: Moving average uses pre-tax price ──
    def test_moving_average_pretax(self):
        """Product.moving_average_price should reflect tax-exclusive cost."""
        invoice, batch = self._create_draft_purchase(qty=100, basic_rate=100)
        invoice.submit()

        self.product.refresh_from_db()
        self.assertEqual(self.product.moving_average_price, Decimal('100'))

    # ── Test 7: Full lifecycle with cancellation ──
    def test_full_lifecycle_submit_cancel(self):
        """Submit → verify SRNB=0 → Cancel → verify all GL reversed."""
        invoice, batch = self._create_draft_purchase(qty=100, basic_rate=100)
        invoice.submit()

        # Verify submitted state
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, 'SUBMITTED')

        pr = invoice.purchase_receipt
        self.assertIsNotNone(pr)

        # SRNB = 0
        srnb_entries = GLEntry.objects.filter(
            account__name='Stock Received But Not Billed',
        )
        srnb_bal = (srnb_entries.aggregate(s=Sum('debit'))['s'] or 0) - \
                   (srnb_entries.aggregate(s=Sum('credit'))['s'] or 0)
        self.assertEqual(srnb_bal, 0)

        # Now cancel
        invoice.cancel()
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, 'CANCELLED')

        # After cancel: PI GL wiped, PR GL wiped via PurchaseReceiptCancel
        pi_gl_count = GLEntry.objects.filter(
            reference_type='PurchaseInvoice', reference_id=invoice.pk,
        ).count()
        self.assertEqual(pi_gl_count, 0, "PI GL should be wiped after cancel")

        # Batch quantity back to 0
        batch.refresh_from_db()
        self.assertEqual(batch.current_quantity, 0)

    # ── Test 8: Grand total includes tax for AP ──
    def test_ap_equals_grand_total(self):
        """Accounts Payable credit must equal the full invoice.total_amount (tax-inclusive)."""
        invoice, batch = self._create_draft_purchase(qty=100, basic_rate=100)
        invoice.submit()

        ap_cr = GLEntry.objects.filter(
            reference_type='PurchaseInvoice',
            reference_id=invoice.pk,
            account__name='Accounts Payable',
        ).aggregate(total=Sum('credit'))['total'] or Decimal('0')

        self.assertEqual(ap_cr, invoice.total_amount)

    # ── Test 9: Stock In Hand equals base amount ──
    def test_stock_in_hand_equals_base(self):
        """Stock In Hand debit must equal base_amount (qty × basic_rate)."""
        invoice, batch = self._create_draft_purchase(qty=50, basic_rate=200)
        invoice.submit()

        pr = invoice.purchase_receipt
        sih_dr = GLEntry.objects.filter(
            reference_type='PurchaseReceipt', reference_id=pr.pk,
            account__name='Stock In Hand',
        ).aggregate(total=Sum('debit'))['total'] or Decimal('0')

        # 50 × 200 = 10,000
        self.assertEqual(sih_dr, Decimal('10000'))

    # ── Test 10: Balanced double-entry for PR ──
    def test_pr_gl_balanced(self):
        """PR GL debits must equal credits."""
        invoice, batch = self._create_draft_purchase(qty=100, basic_rate=100)
        invoice.submit()

        pr = invoice.purchase_receipt
        pr_gl = GLEntry.objects.filter(
            reference_type='PurchaseReceipt', reference_id=pr.pk,
        )
        total_dr = pr_gl.aggregate(s=Sum('debit'))['s'] or Decimal('0')
        total_cr = pr_gl.aggregate(s=Sum('credit'))['s'] or Decimal('0')
        self.assertEqual(total_dr, total_cr, f"PR GL unbalanced: Dr {total_dr} ≠ Cr {total_cr}")

    # ── Test 11: Balanced double-entry for PI ──
    def test_pi_gl_balanced(self):
        """PI GL debits must equal credits."""
        invoice, batch = self._create_draft_purchase(qty=100, basic_rate=100)
        invoice.submit()

        pi_gl = GLEntry.objects.filter(
            reference_type='PurchaseInvoice', reference_id=invoice.pk,
        )
        total_dr = pi_gl.aggregate(s=Sum('debit'))['s'] or Decimal('0')
        total_cr = pi_gl.aggregate(s=Sum('credit'))['s'] or Decimal('0')
        self.assertEqual(total_dr, total_cr, f"PI GL unbalanced: Dr {total_dr} ≠ Cr {total_cr}")
