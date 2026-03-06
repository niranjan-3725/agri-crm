"""
accounting/test_sdnb_sales_flow.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Sprint 17: Integration tests for the SDNB clearing pattern.

Verifies the Definition of Done:
  Sale: 10 units @ ₹100 sell / ₹50 MAP cost

  DeliveryNote.submit():
    Dr  Stock Delivered But Not Billed  500
    Cr  Stock In Hand                   500

  SalesInvoice.submit():
    Dr  Cost of Goods Sold              500   ← SDNB clearance
    Cr  Stock Delivered But Not Billed  500
    Dr  Accounts Receivable             1000  ← revenue entry
    Cr  Sales Revenue                   1000

  Net SDNB balance = 0 once invoice is submitted.
  Over-billing guard raises ValidationError.
"""

from decimal import Decimal

from django.test import TestCase
from django.core.exceptions import ValidationError

from accounting.models import Account, GLEntry
from accounting.services import post_sdnb_clearance_gl
from inventory.models import Batch, Warehouse, StockBin
from master_data.models import Category, Customer, Manufacturer, Product
from transactions.models import (
    DeliveryNote, DeliveryNoteItem,
    SalesInvoice, SalesItem,
    SalesOrder, SalesOrderItem,
    Quotation,
)


# ── Helpers ────────────────────────────────────────────────────────────────

def _gl_balance(account_name: str, reference_type: str = None, reference_id: int = None) -> Decimal:
    """Return net balance (debits - credits) for an account."""
    qs = GLEntry.objects.filter(account__name=account_name)
    if reference_type:
        qs = qs.filter(reference_type=reference_type)
    if reference_id is not None:
        qs = qs.filter(reference_id=reference_id)
    total_debit  = sum(e.debit  for e in qs) or Decimal('0')
    total_credit = sum(e.credit for e in qs) or Decimal('0')
    return total_debit - total_credit


def _setup_world():
    """Create the minimum master data needed by all test cases."""
    # GL accounts (normally seeded by migrations)
    for name, acct_type in [
        ('Stock In Hand',                  'ASSET'),
        ('Stock Delivered But Not Billed', 'ASSET'),
        ('Cost of Goods Sold',             'EXPENSE'),
        ('Accounts Receivable',            'ASSET'),
        ('Sales Revenue',                  'INCOME'),
        ('CGST Payable',                   'LIABILITY'),
        ('SGST Payable',                   'LIABILITY'),
        ('Inventory Adjustment',           'EXPENSE'),
    ]:
        Account.objects.get_or_create(name=name, defaults={'account_type': acct_type, 'is_system_account': True})

    cat = Category.objects.create(name='Fertiliser', cgst_rate=Decimal('0'), sgst_rate=Decimal('0'))
    mfr = Manufacturer.objects.create(name='AgroMfr')
    product = Product.objects.create(
        name='Urea 50kg', hsn_code='3102', unit_type='Bag',
        category=cat, manufacturer=mfr,
        moving_average_price=Decimal('50.00'),   # MAP = ₹50
    )
    customer = Customer.objects.create(
        name='Ravi Farms', mobile_no='9999999999', address='Village Road'
    )
    wh, _ = Warehouse.objects.get_or_create(
        name='Main Warehouse', defaults={'location': 'Default', 'is_active': True}
    )
    batch = Batch.objects.create(
        product=product, batch_number='B001', mrp=Decimal('120.00'),
        purchase_price=Decimal('50.00'), base_selling_price=Decimal('100.00'),
        current_quantity=50,
    )
    StockBin.objects.get_or_create(
        warehouse=wh, batch=batch, defaults={'actual_qty': 50}
    )
    return product, customer, batch


# ── Test Cases ─────────────────────────────────────────────────────────────

class SDNBDeliveryNoteGLTest(TestCase):
    """DeliveryNote.submit() must post Dr SDNB / Cr Stock In Hand."""

    def setUp(self):
        self.product, self.customer, self.batch = _setup_world()

    def test_delivery_note_posts_sdnb_not_cogs(self):
        """Submitting a DN should credit Stock In Hand and debit SDNB."""
        dn = DeliveryNote.objects.create(customer=self.customer, date='2026-03-06')
        DeliveryNoteItem.objects.create(delivery_note=dn, batch=self.batch, quantity=10)
        dn.submit()

        # SDNB debit = 10 × MAP(50) = 500
        sdnb_balance = _gl_balance('Stock Delivered But Not Billed', 'DeliveryNote', dn.id)
        self.assertEqual(sdnb_balance, Decimal('500.00'),
            "DeliveryNote should debit SDNB ₹500")

        # Stock In Hand credit = 500
        sih_balance = _gl_balance('Stock In Hand', 'DeliveryNote', dn.id)
        self.assertEqual(sih_balance, Decimal('-500.00'),
            "DeliveryNote should credit Stock In Hand ₹500")

        # COGS must NOT be touched at delivery time
        cogs_balance = _gl_balance('Cost of Goods Sold', 'DeliveryNote', dn.id)
        self.assertEqual(cogs_balance, Decimal('0.00'),
            "COGS must not be posted at delivery — only at invoicing")


class SDNBInvoiceFlowTest(TestCase):
    """SalesInvoice.submit() must clear SDNB and post AR/Revenue."""

    def setUp(self):
        self.product, self.customer, self.batch = _setup_world()

    def _make_invoice(self, qty=10, unit_price=Decimal('100.00')):
        """Create and return a DRAFT SalesInvoice (no DeliveryNote yet)."""
        taxable = unit_price * qty
        invoice = SalesInvoice.objects.create(
            customer=self.customer,
            date='2026-03-06',
            total_taxable=taxable,
            total_cgst=Decimal('0.00'),
            total_sgst=Decimal('0.00'),
            grand_total=taxable,
        )
        SalesItem.objects.create(
            invoice=invoice,
            batch=self.batch,
            quantity=qty,
            unit_price=unit_price,
            tax_rate=Decimal('0.00'),
            tax_amount=Decimal('0.00'),
            total_amount=unit_price * qty,
        )
        return invoice

    def test_full_sale_gl_entries(self):
        """10 units @ ₹100 sell / ₹50 MAP produces correct GL across all accounts."""
        invoice = self._make_invoice(qty=10, unit_price=Decimal('100.00'))
        invoice.submit()

        si_id = invoice.id
        dn_id = invoice.delivery_note.id

        # ── Delivery leg (tagged to DeliveryNote) ──
        sdnb_from_dn = _gl_balance('Stock Delivered But Not Billed', 'DeliveryNote', dn_id)
        self.assertEqual(sdnb_from_dn, Decimal('500.00'), "DN: Dr SDNB 500")

        sih_from_dn = _gl_balance('Stock In Hand', 'DeliveryNote', dn_id)
        self.assertEqual(sih_from_dn, Decimal('-500.00'), "DN: Cr SIH 500")

        # ── SDNB clearance leg (tagged to SalesInvoice) ──
        cogs_from_si = _gl_balance('Cost of Goods Sold', 'SalesInvoice', si_id)
        self.assertEqual(cogs_from_si, Decimal('500.00'), "SI: Dr COGS 500")

        sdnb_from_si = _gl_balance('Stock Delivered But Not Billed', 'SalesInvoice', si_id)
        self.assertEqual(sdnb_from_si, Decimal('-500.00'), "SI: Cr SDNB 500")

        # ── Revenue leg (tagged to SalesInvoice) ──
        ar_balance = _gl_balance('Accounts Receivable', 'SalesInvoice', si_id)
        self.assertEqual(ar_balance, Decimal('1000.00'), "SI: Dr AR 1000")

        rev_balance = _gl_balance('Sales Revenue', 'SalesInvoice', si_id)
        self.assertEqual(rev_balance, Decimal('-1000.00'), "SI: Cr Revenue 1000")

    def test_sdnb_account_nets_to_zero_after_invoice(self):
        """Net SDNB balance across both DN and SI entries must be zero."""
        invoice = self._make_invoice(qty=10, unit_price=Decimal('100.00'))
        invoice.submit()

        dn_id = invoice.delivery_note.id
        si_id = invoice.id

        sdnb_net = (
            _gl_balance('Stock Delivered But Not Billed', 'DeliveryNote', dn_id)
            + _gl_balance('Stock Delivered But Not Billed', 'SalesInvoice', si_id)
        )
        self.assertEqual(sdnb_net, Decimal('0.00'),
            "SDNB must net to zero once the invoice is submitted")

    def test_cancel_reverses_all_gl(self):
        """Cancelling a SalesInvoice must reverse all three announcement legs."""
        invoice = self._make_invoice(qty=10, unit_price=Decimal('100.00'))
        invoice.submit()
        invoice.refresh_from_db()
        invoice.cancel()

        si_id = invoice.id

        # After cancel, SI-tagged GL entries should net to zero
        ar_net = _gl_balance('Accounts Receivable', 'SalesInvoice', si_id)
        self.assertEqual(ar_net, Decimal('0.00'), "AR must net to zero after cancel")

        cogs_net = _gl_balance('Cost of Goods Sold', 'SalesInvoice', si_id)
        self.assertEqual(cogs_net, Decimal('0.00'), "COGS must net to zero after cancel")

        sdnb_si_net = _gl_balance('Stock Delivered But Not Billed', 'SalesInvoice', si_id)
        self.assertEqual(sdnb_si_net, Decimal('0.00'), "SDNB (SI leg) must net to zero after cancel")


class OverBillingGuardTest(TestCase):
    """SalesInvoice.submit() must block billing more units than ordered."""

    def setUp(self):
        self.product, self.customer, self.batch = _setup_world()

    def test_over_billing_raises_validation_error(self):
        """Billing 11 units against a 10-unit SO must raise ValidationError."""
        so = SalesOrder.objects.create(customer=self.customer, date='2026-03-06', grand_total=Decimal('1000'))
        so_item = SalesOrderItem.objects.create(
            sales_order=so, batch=self.batch,
            quantity=10, unit_price=Decimal('100'), amount=Decimal('1000'),
        )
        so.submit()

        invoice = SalesInvoice.objects.create(
            customer=self.customer, date='2026-03-06',
            total_taxable=Decimal('1100'), total_cgst=Decimal('0'),
            total_sgst=Decimal('0'), grand_total=Decimal('1100'),
            sales_order=so,
        )
        SalesItem.objects.create(
            invoice=invoice, batch=self.batch,
            quantity=11,                          # ← 1 more than ordered
            unit_price=Decimal('100'), tax_rate=Decimal('0'),
            tax_amount=Decimal('0'), total_amount=Decimal('1100'),
            sales_order_item=so_item,
        )

        with self.assertRaises(ValidationError) as ctx:
            invoice.submit()

        self.assertIn('Over-billing', str(ctx.exception))

    def test_exact_quantity_succeeds(self):
        """Billing exactly the ordered quantity must succeed."""
        so = SalesOrder.objects.create(customer=self.customer, date='2026-03-06', grand_total=Decimal('1000'))
        so_item = SalesOrderItem.objects.create(
            sales_order=so, batch=self.batch,
            quantity=10, unit_price=Decimal('100'), amount=Decimal('1000'),
        )
        so.submit()

        invoice = SalesInvoice.objects.create(
            customer=self.customer, date='2026-03-06',
            total_taxable=Decimal('1000'), total_cgst=Decimal('0'),
            total_sgst=Decimal('0'), grand_total=Decimal('1000'),
            sales_order=so,
        )
        SalesItem.objects.create(
            invoice=invoice, batch=self.batch,
            quantity=10,
            unit_price=Decimal('100'), tax_rate=Decimal('0'),
            tax_amount=Decimal('0'), total_amount=Decimal('1000'),
            sales_order_item=so_item,
        )
        invoice.submit()    # must not raise
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, 'SUBMITTED')


class QuotationAtomicTest(TestCase):
    """Quotation.submit() and cancel() must be atomic."""

    def setUp(self):
        _, self.customer, _ = _setup_world()

    def test_quotation_submit_sets_status(self):
        q = Quotation.objects.create(customer=self.customer, date='2026-03-06')
        q.submit()
        q.refresh_from_db()
        self.assertEqual(q.status, 'SUBMITTED')

    def test_quotation_cancel_sets_status(self):
        q = Quotation.objects.create(customer=self.customer, date='2026-03-06')
        q.submit()
        q.cancel()
        q.refresh_from_db()
        self.assertEqual(q.status, 'CANCELLED')

    def test_quotation_double_submit_raises(self):
        q = Quotation.objects.create(customer=self.customer, date='2026-03-06')
        q.submit()
        with self.assertRaises(ValidationError):
            q.submit()
