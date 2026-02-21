"""
Sprint 12 — AR/AP & Tax Ledger Integration Tests.

Validates:
  1. Sales Invoice submit creates AR debit, Revenue + Tax credits.
  2. Purchase Invoice submit creates AP credit, Inventory + Tax debits.
  3. Customer Payment creates Cash/Bank debit, AR credit.
  4. Supplier Payment creates AP debit, Cash/Bank credit.
  5. Cancel reverses all AR/AP GL entries.
  6. Global double-entry balance holds across full lifecycle.
"""

from decimal import Decimal
from datetime import date

from django.test import TestCase

from accounting.models import Account, GLEntry
from accounting.services import (
    make_gl_entries,
    post_sales_invoice_gl,
    post_purchase_invoice_gl,
    post_customer_payment_gl,
    post_supplier_payment_gl,
    reverse_document_gl,
)
from inventory.models import Batch, StockBin
from inventory.services import get_default_warehouse
from master_data.models import Category, Customer, Manufacturer, Product, Supplier
from transactions.models import (
    SalesInvoice, SalesItem,
    PurchaseInvoice, PurchaseItem,
    CustomerPayment, SupplierPayment,
)


def _seed_stockbin(batch):
    """Ensure a StockBin exists for the default warehouse."""
    wh = get_default_warehouse()
    StockBin.objects.get_or_create(
        warehouse=wh, batch=batch,
        defaults={'actual_qty': batch.current_quantity},
    )


class Sprint12SalesInvoiceGLTests(TestCase):
    """Test AR / Revenue / Tax GL entries on Sales Invoice submission."""

    def setUp(self):
        self.category = Category.objects.create(name='S12 Seeds', cgst_rate=9, sgst_rate=9)
        self.manufacturer = Manufacturer.objects.create(name='S12 Mfr')
        self.product = Product.objects.create(
            name='S12 Product', category=self.category,
            unit_type='Kg', manufacturer=self.manufacturer,
        )
        self.customer = Customer.objects.create(name='S12 Customer')
        self.batch = Batch.objects.create(
            product=self.product, batch_number='S12_B001',
            current_quantity=100, purchase_price=Decimal('80.00'),
            base_selling_price=Decimal('100.00'), mrp=Decimal('120.00'),
        )
        _seed_stockbin(self.batch)

    def _create_sales_invoice(self, taxable, cgst, sgst, grand_total, qty=1):
        """Helper: create a DRAFT SalesInvoice with one item."""
        invoice = SalesInvoice.objects.create(
            customer=self.customer,
            total_taxable=taxable,
            total_cgst=cgst,
            total_sgst=sgst,
            grand_total=grand_total,
        )
        SalesItem.objects.create(
            invoice=invoice, batch=self.batch,
            quantity=qty, unit_price=grand_total / qty,
            tax_rate=Decimal('18.00'),
            tax_amount=cgst + sgst,
            total_amount=grand_total,
        )
        return invoice

    def test_submit_creates_ar_revenue_tax_entries(self):
        """₹100 sale with ₹18 tax → Dr AR ₹118, Cr Revenue ₹100, Cr CGST ₹9, Cr SGST ₹9."""
        invoice = self._create_sales_invoice(
            taxable=Decimal('100.00'),
            cgst=Decimal('9.00'),
            sgst=Decimal('9.00'),
            grand_total=Decimal('118.00'),
            qty=1,
        )
        invoice.submit()

        gl_entries = GLEntry.objects.filter(
            reference_type='SalesInvoice', reference_id=invoice.id
        )

        # Stock GL (COGS/Stock In Hand) + AR/Revenue/Tax = 2 + 4 = 6
        # But we check AR entries specifically
        ar_entry = gl_entries.get(account__name='Accounts Receivable')
        self.assertEqual(ar_entry.debit, Decimal('118.00'))
        self.assertEqual(ar_entry.credit, Decimal('0.00'))

        revenue_entry = gl_entries.get(account__name='Sales Revenue')
        self.assertEqual(revenue_entry.debit, Decimal('0.00'))
        self.assertEqual(revenue_entry.credit, Decimal('100.00'))

        cgst_entry = gl_entries.get(account__name='CGST Payable')
        self.assertEqual(cgst_entry.credit, Decimal('9.00'))

        sgst_entry = gl_entries.get(account__name='SGST Payable')
        self.assertEqual(sgst_entry.credit, Decimal('9.00'))

    def test_ar_entries_balance(self):
        """Total AR/Revenue/Tax debits must equal credits."""
        invoice = self._create_sales_invoice(
            taxable=Decimal('100.00'),
            cgst=Decimal('9.00'),
            sgst=Decimal('9.00'),
            grand_total=Decimal('118.00'),
            qty=1,
        )
        invoice.submit()

        gl_entries = GLEntry.objects.filter(
            reference_type='SalesInvoice', reference_id=invoice.id
        )
        total_debit = sum(e.debit for e in gl_entries)
        total_credit = sum(e.credit for e in gl_entries)
        self.assertEqual(total_debit, total_credit,
                         f"Unbalanced! Dr={total_debit}, Cr={total_credit}")

    def test_cancel_reverses_ar_entries(self):
        """Cancelling a submitted invoice removes AR/Revenue/Tax GL entries."""
        invoice = self._create_sales_invoice(
            taxable=Decimal('100.00'),
            cgst=Decimal('9.00'),
            sgst=Decimal('9.00'),
            grand_total=Decimal('118.00'),
            qty=1,
        )
        invoice.submit()
        self.assertTrue(
            GLEntry.objects.filter(
                reference_type='SalesInvoice', reference_id=invoice.id,
                account__name='Accounts Receivable'
            ).exists()
        )

        invoice.cancel()

        # AR entries should be removed (stock cancel entries remain under a different ref type)
        self.assertFalse(
            GLEntry.objects.filter(
                reference_type='SalesInvoice', reference_id=invoice.id
            ).exists()
        )

    def test_zero_total_creates_no_ar_entries(self):
        """A zero-value invoice should produce no AR GL entries."""
        invoice = self._create_sales_invoice(
            taxable=Decimal('0.00'), cgst=Decimal('0.00'),
            sgst=Decimal('0.00'), grand_total=Decimal('0.00'), qty=1,
        )
        # Can't submit a zero-stock invoice normally, so test the service directly
        result = post_sales_invoice_gl(invoice)
        self.assertEqual(result, [])


class Sprint12PurchaseInvoiceGLTests(TestCase):
    """Test AP / Inventory / Tax GL entries on Purchase Invoice submission."""

    def setUp(self):
        self.category = Category.objects.create(name='S12P Seeds', cgst_rate=9, sgst_rate=9)
        self.manufacturer = Manufacturer.objects.create(name='S12P Mfr')
        self.product = Product.objects.create(
            name='S12P Product', category=self.category,
            unit_type='Kg', manufacturer=self.manufacturer,
        )
        self.supplier = Supplier.objects.create(name='S12P Supplier')
        self.batch = Batch.objects.create(
            product=self.product, batch_number='S12P_B001',
            current_quantity=0, purchase_price=Decimal('100.00'),
            base_selling_price=Decimal('150.00'), mrp=Decimal('200.00'),
        )
        _seed_stockbin(self.batch)

    def _create_purchase_invoice(self, basic_rate, tax_amount, total_amount, qty=10):
        """Helper: create a DRAFT PurchaseInvoice with one item."""
        invoice = PurchaseInvoice.objects.create(
            supplier=self.supplier,
            invoice_number=f'INV-S12-{PurchaseInvoice.objects.count()}',
            date=date.today(),
            total_amount=total_amount,
        )
        PurchaseItem.objects.create(
            invoice=invoice, batch=self.batch,
            quantity=qty, basic_rate=basic_rate,
            tax_amount=tax_amount,
            selling_price=Decimal('150.00'),
            profit_margin=Decimal('20.00'),
            total_amount=total_amount,
        )
        return invoice

    def test_submit_creates_ap_inventory_tax_entries(self):
        """₹1000 base + ₹180 tax = ₹1180 total →
        Dr SRNB ₹1000, Dr CGST_Rcv ₹90, Dr SGST_Rcv ₹90, Cr AP ₹1180."""
        invoice = self._create_purchase_invoice(
            basic_rate=Decimal('100.00'),
            tax_amount=Decimal('180.00'),
            total_amount=Decimal('1180.00'),
            qty=10,
        )
        invoice.submit()

        gl_entries = GLEntry.objects.filter(
            reference_type='PurchaseInvoice', reference_id=invoice.id
        )

        ap_entry = gl_entries.get(account__name='Accounts Payable')
        self.assertEqual(ap_entry.credit, Decimal('1180.00'))

        # Sprint 13: Stock GL entries are on PurchaseReceipt, not PurchaseInvoice
        # So only AP GL entries (SRNB debit, AP credit, tax) are on the invoice
        srnb_entry = gl_entries.get(account__name='Stock Received But Not Billed')
        self.assertEqual(srnb_entry.debit, Decimal('1000.00'))

        cgst_entry = gl_entries.get(account__name='CGST Receivable')
        self.assertEqual(cgst_entry.debit, Decimal('90.00'))

        sgst_entry = gl_entries.get(account__name='SGST Receivable')
        self.assertEqual(sgst_entry.debit, Decimal('90.00'))

    def test_ap_entries_balance(self):
        """Total AP/Inventory/Tax debits must equal credits."""
        invoice = self._create_purchase_invoice(
            basic_rate=Decimal('100.00'),
            tax_amount=Decimal('180.00'),
            total_amount=Decimal('1180.00'),
            qty=10,
        )
        invoice.submit()

        gl_entries = GLEntry.objects.filter(
            reference_type='PurchaseInvoice', reference_id=invoice.id
        )
        total_debit = sum(e.debit for e in gl_entries)
        total_credit = sum(e.credit for e in gl_entries)
        self.assertEqual(total_debit, total_credit,
                         f"Unbalanced! Dr={total_debit}, Cr={total_credit}")

    def test_cancel_reverses_ap_entries(self):
        """Cancelling a submitted purchase removes AP/Tax GL entries."""
        invoice = self._create_purchase_invoice(
            basic_rate=Decimal('100.00'),
            tax_amount=Decimal('180.00'),
            total_amount=Decimal('1180.00'),
            qty=10,
        )
        invoice.submit()
        invoice.cancel()

        self.assertFalse(
            GLEntry.objects.filter(
                reference_type='PurchaseInvoice', reference_id=invoice.id
            ).exists()
        )


class Sprint12CustomerPaymentGLTests(TestCase):
    """Test Cash / AR GL entries on Customer Payment creation."""

    def setUp(self):
        self.category = Category.objects.create(name='S12Pay Seeds', cgst_rate=9, sgst_rate=9)
        self.manufacturer = Manufacturer.objects.create(name='S12Pay Mfr')
        self.product = Product.objects.create(
            name='S12Pay Product', category=self.category,
            unit_type='Kg', manufacturer=self.manufacturer,
        )
        self.customer = Customer.objects.create(name='S12Pay Customer')
        self.batch = Batch.objects.create(
            product=self.product, batch_number='S12PAY_B001',
            current_quantity=100, purchase_price=Decimal('80.00'),
            base_selling_price=Decimal('100.00'), mrp=Decimal('120.00'),
        )
        _seed_stockbin(self.batch)

    def test_customer_payment_creates_cash_debit_ar_credit(self):
        """₹118 customer payment → Dr Cash/Bank ₹118, Cr AR ₹118."""
        invoice = SalesInvoice.objects.create(
            customer=self.customer,
            total_taxable=Decimal('100.00'),
            total_cgst=Decimal('9.00'),
            total_sgst=Decimal('9.00'),
            grand_total=Decimal('118.00'),
        )
        SalesItem.objects.create(
            invoice=invoice, batch=self.batch,
            quantity=1, unit_price=Decimal('118.00'),
            tax_rate=Decimal('18.00'), tax_amount=Decimal('18.00'),
            total_amount=Decimal('118.00'),
        )
        invoice.submit()

        payment = CustomerPayment.objects.create(
            invoice=invoice,
            amount=Decimal('118.00'),
            payment_date=date.today(),
            payment_mode='CASH',
        )

        gl_entries = GLEntry.objects.filter(
            reference_type='CustomerPayment', reference_id=payment.id
        )
        self.assertEqual(gl_entries.count(), 2)

        cash_entry = gl_entries.get(account__name='Cash / Bank')
        self.assertEqual(cash_entry.debit, Decimal('118.00'))

        ar_entry = gl_entries.get(account__name='Accounts Receivable')
        self.assertEqual(ar_entry.credit, Decimal('118.00'))

    def test_payment_reversal_creates_opposite_entries(self):
        """Negative payment reversal → Dr AR, Cr Cash/Bank."""
        invoice = SalesInvoice.objects.create(
            customer=self.customer,
            total_taxable=Decimal('100.00'),
            total_cgst=Decimal('9.00'),
            total_sgst=Decimal('9.00'),
            grand_total=Decimal('118.00'),
        )

        reversal = CustomerPayment.objects.create(
            invoice=invoice,
            amount=Decimal('-50.00'),
            payment_date=date.today(),
            payment_mode='CASH',
            notes='Reversal',
        )

        gl_entries = GLEntry.objects.filter(
            reference_type='CustomerPayment', reference_id=reversal.id
        )
        self.assertEqual(gl_entries.count(), 2)

        ar_entry = gl_entries.get(account__name='Accounts Receivable')
        self.assertEqual(ar_entry.debit, Decimal('50.00'))

        cash_entry = gl_entries.get(account__name='Cash / Bank')
        self.assertEqual(cash_entry.credit, Decimal('50.00'))


class Sprint12SupplierPaymentGLTests(TestCase):
    """Test AP / Cash GL entries on Supplier Payment creation."""

    def setUp(self):
        self.supplier = Supplier.objects.create(name='S12SP Supplier')
        self.category = Category.objects.create(name='S12SP Seeds', cgst_rate=9, sgst_rate=9)
        self.manufacturer = Manufacturer.objects.create(name='S12SP Mfr')
        self.product = Product.objects.create(
            name='S12SP Product', category=self.category,
            unit_type='Kg', manufacturer=self.manufacturer,
        )
        self.batch = Batch.objects.create(
            product=self.product, batch_number='S12SP_B001',
            current_quantity=0, purchase_price=Decimal('100.00'),
            base_selling_price=Decimal('150.00'), mrp=Decimal('200.00'),
        )
        _seed_stockbin(self.batch)

    def test_supplier_payment_creates_ap_debit_cash_credit(self):
        """₹1000 supplier payment → Dr AP ₹1000, Cr Cash/Bank ₹1000."""
        invoice = PurchaseInvoice.objects.create(
            supplier=self.supplier,
            invoice_number='INV-S12SP-001',
            date=date.today(),
            total_amount=Decimal('1000.00'),
        )

        payment = SupplierPayment.objects.create(
            invoice=invoice,
            amount=Decimal('1000.00'),
            payment_date=date.today(),
            payment_mode='BANK',
        )

        gl_entries = GLEntry.objects.filter(
            reference_type='SupplierPayment', reference_id=payment.id
        )
        self.assertEqual(gl_entries.count(), 2)

        ap_entry = gl_entries.get(account__name='Accounts Payable')
        self.assertEqual(ap_entry.debit, Decimal('1000.00'))

        cash_entry = gl_entries.get(account__name='Cash / Bank')
        self.assertEqual(cash_entry.credit, Decimal('1000.00'))


class Sprint12FullLifecycleGLTest(TestCase):
    """Verify full lifecycle GL balance: invoice + payment + cancel."""

    def setUp(self):
        self.category = Category.objects.create(name='S12Life Seeds', cgst_rate=9, sgst_rate=9)
        self.manufacturer = Manufacturer.objects.create(name='S12Life Mfr')
        self.product = Product.objects.create(
            name='S12Life Product', category=self.category,
            unit_type='Kg', manufacturer=self.manufacturer,
        )
        self.customer = Customer.objects.create(name='S12Life Customer')
        self.supplier = Supplier.objects.create(name='S12Life Supplier')
        self.batch = Batch.objects.create(
            product=self.product, batch_number='S12LIFE_B001',
            current_quantity=100, purchase_price=Decimal('100.00'),
            base_selling_price=Decimal('150.00'), mrp=Decimal('200.00'),
        )
        _seed_stockbin(self.batch)

    def test_global_debits_equal_credits(self):
        """After sale + payment + purchase + supplier payment: global dr == cr."""
        from django.db.models import Sum

        # 1. Create and submit a sale: ₹118
        sale = SalesInvoice.objects.create(
            customer=self.customer,
            total_taxable=Decimal('100.00'),
            total_cgst=Decimal('9.00'),
            total_sgst=Decimal('9.00'),
            grand_total=Decimal('118.00'),
        )
        SalesItem.objects.create(
            invoice=sale, batch=self.batch,
            quantity=5, unit_price=Decimal('23.60'),
            tax_rate=Decimal('18.00'), tax_amount=Decimal('18.00'),
            total_amount=Decimal('118.00'),
        )
        sale.submit()

        # 2. Customer pays ₹118
        CustomerPayment.objects.create(
            invoice=sale,
            amount=Decimal('118.00'),
            payment_date=date.today(),
            payment_mode='CASH',
        )

        # 3. Create and submit a purchase: ₹1180
        purchase = PurchaseInvoice.objects.create(
            supplier=self.supplier,
            invoice_number='INV-S12LIFE-001',
            date=date.today(),
            total_amount=Decimal('1180.00'),
        )
        PurchaseItem.objects.create(
            invoice=purchase, batch=self.batch,
            quantity=10, basic_rate=Decimal('100.00'),
            tax_amount=Decimal('180.00'),
            selling_price=Decimal('150.00'),
            profit_margin=Decimal('20.00'),
            total_amount=Decimal('1180.00'),
        )
        purchase.submit()

        # 4. Supplier payment: ₹1180
        SupplierPayment.objects.create(
            invoice=purchase,
            amount=Decimal('1180.00'),
            payment_date=date.today(),
            payment_mode='BANK',
        )

        # VERIFY: Global balance
        totals = GLEntry.objects.aggregate(
            total_debit=Sum('debit'),
            total_credit=Sum('credit'),
        )
        self.assertEqual(
            totals['total_debit'],
            totals['total_credit'],
            f"GL unbalanced! Dr={totals['total_debit']}, Cr={totals['total_credit']}",
        )

    def test_sale_submit_then_cancel_clears_ar(self):
        """Sale submit + cancel: AR entries are cleaned up, only stock cancel entries remain."""
        from django.db.models import Sum

        sale = SalesInvoice.objects.create(
            customer=self.customer,
            total_taxable=Decimal('200.00'),
            total_cgst=Decimal('18.00'),
            total_sgst=Decimal('18.00'),
            grand_total=Decimal('236.00'),
        )
        SalesItem.objects.create(
            invoice=sale, batch=self.batch,
            quantity=2, unit_price=Decimal('118.00'),
            tax_rate=Decimal('18.00'), tax_amount=Decimal('36.00'),
            total_amount=Decimal('236.00'),
        )
        sale.submit()
        sale.cancel()

        # No SalesInvoice GL entries should remain (AR reversed)
        self.assertEqual(
            GLEntry.objects.filter(reference_type='SalesInvoice', reference_id=sale.id).count(),
            0,
        )

        # Sprint 13: Cancel stock entries are on DeliveryNote, not SalesInvoice
        self.assertTrue(
            GLEntry.objects.filter(reference_type='DeliveryNoteCancel').exists()
        )

        # Global balance should still hold
        totals = GLEntry.objects.aggregate(
            total_debit=Sum('debit'),
            total_credit=Sum('credit'),
        )
        self.assertEqual(totals['total_debit'], totals['total_credit'])
