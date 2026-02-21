"""
Sprint 13 — Fulfillment Pipeline & Decoupled Stock Tests.

Validates:
  1. DeliveryNote.submit() deducts physical stock and creates COGS GL entries.
  2. PurchaseReceipt.submit() adds physical stock and creates Inventory GL entries.
  3. SalesInvoice.submit() auto-creates a DeliveryNote, creates AR GL, no direct stock.
  4. PurchaseInvoice.submit() auto-creates a PurchaseReceipt, creates AP GL, no direct stock.
  5. Invoice cancellation cascades to fulfillment doc cancellation.
  6. Standalone fulfillment documents work independently of invoices.
  7. Global GL balance holds across full lifecycle.
"""

from decimal import Decimal
from datetime import date

from django.test import TestCase
from django.db.models import Sum

from accounting.models import GLEntry
from inventory.models import Batch, StockBin, StockMovement
from inventory.services import get_default_warehouse
from master_data.models import Category, Customer, Manufacturer, Product, Supplier
from transactions.models import (
    SalesInvoice, SalesItem,
    PurchaseInvoice, PurchaseItem,
    DeliveryNote, DeliveryNoteItem,
    PurchaseReceipt, PurchaseReceiptItem,
)


def _seed(batch):
    """Ensure a StockBin exists for the default warehouse."""
    wh = get_default_warehouse()
    StockBin.objects.get_or_create(
        warehouse=wh, batch=batch,
        defaults={'actual_qty': batch.current_quantity},
    )


class Sprint13DeliveryNoteTests(TestCase):
    """Test standalone DeliveryNote stock and GL behavior."""

    def setUp(self):
        self.cat = Category.objects.create(name='S13DN Cat', cgst_rate=9, sgst_rate=9)
        self.mfr = Manufacturer.objects.create(name='S13DN Mfr')
        self.product = Product.objects.create(
            name='S13DN Product', category=self.cat,
            unit_type='Kg', manufacturer=self.mfr,
        )
        self.customer = Customer.objects.create(name='S13DN Customer')
        self.batch = Batch.objects.create(
            product=self.product, batch_number='S13DN_B001',
            current_quantity=50, purchase_price=Decimal('100.00'),
            base_selling_price=Decimal('150.00'), mrp=Decimal('200.00'),
        )
        _seed(self.batch)

    def test_submit_deducts_stock(self):
        """Submitting a DeliveryNote deducts physical stock."""
        dn = DeliveryNote.objects.create(customer=self.customer, date=date.today())
        DeliveryNoteItem.objects.create(delivery_note=dn, batch=self.batch, quantity=10)
        dn.submit()

        self.batch.refresh_from_db()
        self.assertEqual(self.batch.current_quantity, 40)
        self.assertEqual(dn.status, 'SUBMITTED')

    def test_submit_creates_cogs_gl(self):
        """DN submit creates Dr COGS / Cr Stock In Hand GL entries."""
        dn = DeliveryNote.objects.create(customer=self.customer, date=date.today())
        DeliveryNoteItem.objects.create(delivery_note=dn, batch=self.batch, quantity=5)
        dn.submit()

        gl_entries = GLEntry.objects.filter(
            reference_type='DeliveryNote', reference_id=dn.id
        )
        self.assertEqual(gl_entries.count(), 2)

        debit = gl_entries.get(debit__gt=0)
        credit = gl_entries.get(credit__gt=0)
        self.assertEqual(debit.account.name, 'Cost of Goods Sold')
        self.assertEqual(credit.account.name, 'Stock In Hand')

    def test_cancel_restores_stock(self):
        """Cancelling a DN restores stock."""
        dn = DeliveryNote.objects.create(customer=self.customer, date=date.today())
        DeliveryNoteItem.objects.create(delivery_note=dn, batch=self.batch, quantity=10)
        dn.submit()
        dn.cancel()

        self.batch.refresh_from_db()
        self.assertEqual(self.batch.current_quantity, 50)
        self.assertEqual(dn.status, 'CANCELLED')

    def test_stock_movement_references_delivery_note(self):
        """StockMovement records reference DeliveryNote, not SalesInvoice."""
        dn = DeliveryNote.objects.create(customer=self.customer, date=date.today())
        DeliveryNoteItem.objects.create(delivery_note=dn, batch=self.batch, quantity=3)
        dn.submit()

        movement = StockMovement.objects.filter(
            reference_document_type='DeliveryNote',
            reference_document_id=dn.id
        )
        self.assertEqual(movement.count(), 1)
        self.assertEqual(movement.first().quantity, -3)


class Sprint13PurchaseReceiptTests(TestCase):
    """Test standalone PurchaseReceipt stock and GL behavior."""

    def setUp(self):
        self.cat = Category.objects.create(name='S13PR Cat', cgst_rate=9, sgst_rate=9)
        self.mfr = Manufacturer.objects.create(name='S13PR Mfr')
        self.product = Product.objects.create(
            name='S13PR Product', category=self.cat,
            unit_type='Kg', manufacturer=self.mfr,
        )
        self.supplier = Supplier.objects.create(name='S13PR Supplier')
        self.batch = Batch.objects.create(
            product=self.product, batch_number='S13PR_B001',
            current_quantity=0, purchase_price=Decimal('80.00'),
            base_selling_price=Decimal('120.00'), mrp=Decimal('150.00'),
        )
        _seed(self.batch)

    def test_submit_adds_stock(self):
        """Submitting a PurchaseReceipt adds physical stock."""
        pr = PurchaseReceipt.objects.create(supplier=self.supplier, date=date.today())
        PurchaseReceiptItem.objects.create(receipt=pr, batch=self.batch, quantity=20)
        pr.submit()

        self.batch.refresh_from_db()
        self.assertEqual(self.batch.current_quantity, 20)
        self.assertEqual(pr.status, 'SUBMITTED')

    def test_submit_creates_inventory_gl(self):
        """PR submit creates Dr Stock In Hand / Cr SRNB GL entries."""
        pr = PurchaseReceipt.objects.create(supplier=self.supplier, date=date.today())
        PurchaseReceiptItem.objects.create(receipt=pr, batch=self.batch, quantity=10)
        pr.submit()

        gl_entries = GLEntry.objects.filter(
            reference_type='PurchaseReceipt', reference_id=pr.id
        )
        self.assertEqual(gl_entries.count(), 2)

        debit = gl_entries.get(debit__gt=0)
        credit = gl_entries.get(credit__gt=0)
        self.assertEqual(debit.account.name, 'Stock In Hand')
        self.assertEqual(credit.account.name, 'Stock Received But Not Billed')

    def test_cancel_reverses_stock(self):
        """Cancelling a PR reverses stock."""
        pr = PurchaseReceipt.objects.create(supplier=self.supplier, date=date.today())
        PurchaseReceiptItem.objects.create(receipt=pr, batch=self.batch, quantity=15)
        pr.submit()
        pr.cancel()

        self.batch.refresh_from_db()
        self.assertEqual(self.batch.current_quantity, 0)


class Sprint13SalesInvoiceDecouplingTests(TestCase):
    """Test that SalesInvoice.submit() creates no direct stock movement."""

    def setUp(self):
        self.cat = Category.objects.create(name='S13SI Cat', cgst_rate=9, sgst_rate=9)
        self.mfr = Manufacturer.objects.create(name='S13SI Mfr')
        self.product = Product.objects.create(
            name='S13SI Product', category=self.cat,
            unit_type='Kg', manufacturer=self.mfr,
        )
        self.customer = Customer.objects.create(name='S13SI Customer')
        self.batch = Batch.objects.create(
            product=self.product, batch_number='S13SI_B001',
            current_quantity=100, purchase_price=Decimal('80.00'),
            base_selling_price=Decimal('118.00'), mrp=Decimal('150.00'),
        )
        _seed(self.batch)

    def test_submit_auto_creates_delivery_note(self):
        """SalesInvoice.submit() auto-creates a linked DeliveryNote."""
        invoice = SalesInvoice.objects.create(
            customer=self.customer,
            total_taxable=Decimal('100.00'),
            total_cgst=Decimal('9.00'),
            total_sgst=Decimal('9.00'),
            grand_total=Decimal('118.00'),
        )
        SalesItem.objects.create(
            invoice=invoice, batch=self.batch, quantity=5,
            unit_price=Decimal('23.60'), tax_rate=Decimal('18.00'),
            tax_amount=Decimal('18.00'), total_amount=Decimal('118.00'),
        )
        invoice.submit()

        # DN should be auto-created and linked
        invoice.refresh_from_db()
        self.assertIsNotNone(invoice.delivery_note)
        self.assertEqual(invoice.delivery_note.status, 'SUBMITTED')

    def test_no_direct_stock_movement_from_invoice(self):
        """No StockMovement should reference SalesInvoice — only DeliveryNote."""
        invoice = SalesInvoice.objects.create(
            customer=self.customer,
            total_taxable=Decimal('100.00'),
            total_cgst=Decimal('9.00'),
            total_sgst=Decimal('9.00'),
            grand_total=Decimal('118.00'),
        )
        SalesItem.objects.create(
            invoice=invoice, batch=self.batch, quantity=5,
            unit_price=Decimal('23.60'), tax_rate=Decimal('18.00'),
            tax_amount=Decimal('18.00'), total_amount=Decimal('118.00'),
        )
        invoice.submit()

        # Zero stock movements reference SalesInvoice
        si_movements = StockMovement.objects.filter(
            reference_document_type='SalesInvoice'
        )
        self.assertEqual(si_movements.count(), 0)

        # Stock movement references DeliveryNote
        dn_movements = StockMovement.objects.filter(
            reference_document_type='DeliveryNote'
        )
        self.assertTrue(dn_movements.exists())

    def test_stock_deducted_via_delivery_note(self):
        """Stock is deducted (via auto-DN), AR GL is created."""
        invoice = SalesInvoice.objects.create(
            customer=self.customer,
            total_taxable=Decimal('100.00'),
            total_cgst=Decimal('9.00'),
            total_sgst=Decimal('9.00'),
            grand_total=Decimal('118.00'),
        )
        SalesItem.objects.create(
            invoice=invoice, batch=self.batch, quantity=5,
            unit_price=Decimal('23.60'), tax_rate=Decimal('18.00'),
            tax_amount=Decimal('18.00'), total_amount=Decimal('118.00'),
        )
        invoice.submit()

        self.batch.refresh_from_db()
        self.assertEqual(self.batch.current_quantity, 95)  # 100 - 5

        # AR GL exists on the invoice
        ar_gl = GLEntry.objects.filter(
            reference_type='SalesInvoice', reference_id=invoice.id,
            account__name='Accounts Receivable'
        )
        self.assertEqual(ar_gl.count(), 1)

    def test_cancel_cascades_to_delivery_note(self):
        """Cancelling invoice also cancels linked DN, restoring stock."""
        invoice = SalesInvoice.objects.create(
            customer=self.customer,
            total_taxable=Decimal('100.00'),
            total_cgst=Decimal('9.00'),
            total_sgst=Decimal('9.00'),
            grand_total=Decimal('118.00'),
        )
        SalesItem.objects.create(
            invoice=invoice, batch=self.batch, quantity=5,
            unit_price=Decimal('23.60'), tax_rate=Decimal('18.00'),
            tax_amount=Decimal('18.00'), total_amount=Decimal('118.00'),
        )
        invoice.submit()
        invoice.cancel()

        self.batch.refresh_from_db()
        self.assertEqual(self.batch.current_quantity, 100)  # Fully restored

        invoice.refresh_from_db()
        self.assertEqual(invoice.delivery_note.status, 'CANCELLED')

    def test_no_double_stock_deduction(self):
        """Even with auto-DN, stock is deducted exactly once."""
        invoice = SalesInvoice.objects.create(
            customer=self.customer,
            total_taxable=Decimal('100.00'),
            total_cgst=Decimal('9.00'),
            total_sgst=Decimal('9.00'),
            grand_total=Decimal('118.00'),
        )
        SalesItem.objects.create(
            invoice=invoice, batch=self.batch, quantity=10,
            unit_price=Decimal('11.80'), tax_rate=Decimal('18.00'),
            tax_amount=Decimal('18.00'), total_amount=Decimal('118.00'),
        )
        invoice.submit()

        total_movements = StockMovement.objects.filter(batch=self.batch)
        self.assertEqual(total_movements.count(), 1)
        self.assertEqual(total_movements.first().quantity, -10)


class Sprint13PurchaseInvoiceDecouplingTests(TestCase):
    """Test that PurchaseInvoice.submit() creates no direct stock movement."""

    def setUp(self):
        self.cat = Category.objects.create(name='S13PI Cat', cgst_rate=9, sgst_rate=9)
        self.mfr = Manufacturer.objects.create(name='S13PI Mfr')
        self.product = Product.objects.create(
            name='S13PI Product', category=self.cat,
            unit_type='Kg', manufacturer=self.mfr,
        )
        self.supplier = Supplier.objects.create(name='S13PI Supplier')
        self.batch = Batch.objects.create(
            product=self.product, batch_number='S13PI_B001',
            current_quantity=0, purchase_price=Decimal('100.00'),
            base_selling_price=Decimal('150.00'), mrp=Decimal('200.00'),
        )
        _seed(self.batch)

    def test_submit_auto_creates_purchase_receipt(self):
        """PurchaseInvoice.submit() auto-creates a linked PurchaseReceipt."""
        invoice = PurchaseInvoice.objects.create(
            supplier=self.supplier, invoice_number='INV-S13-001',
            date=date.today(), total_amount=Decimal('1180.00'),
        )
        PurchaseItem.objects.create(
            invoice=invoice, batch=self.batch, quantity=10,
            basic_rate=Decimal('100.00'), tax_amount=Decimal('180.00'),
            total_amount=Decimal('1180.00'),
        )
        invoice.submit()

        invoice.refresh_from_db()
        self.assertIsNotNone(invoice.purchase_receipt)
        self.assertEqual(invoice.purchase_receipt.status, 'SUBMITTED')

    def test_no_direct_stock_movement_from_invoice(self):
        """No StockMovement should reference PurchaseInvoice — only PurchaseReceipt."""
        invoice = PurchaseInvoice.objects.create(
            supplier=self.supplier, invoice_number='INV-S13-002',
            date=date.today(), total_amount=Decimal('1000.00'),
        )
        PurchaseItem.objects.create(
            invoice=invoice, batch=self.batch, quantity=10,
            basic_rate=Decimal('100.00'), tax_amount=Decimal('0.00'),
            total_amount=Decimal('1000.00'),
        )
        invoice.submit()

        pi_movements = StockMovement.objects.filter(
            reference_document_type='PurchaseInvoice'
        )
        self.assertEqual(pi_movements.count(), 0)

        pr_movements = StockMovement.objects.filter(
            reference_document_type='PurchaseReceipt'
        )
        self.assertTrue(pr_movements.exists())

    def test_stock_added_via_purchase_receipt(self):
        """Stock is added (via auto-PR), AP GL is created."""
        invoice = PurchaseInvoice.objects.create(
            supplier=self.supplier, invoice_number='INV-S13-003',
            date=date.today(), total_amount=Decimal('1000.00'),
        )
        PurchaseItem.objects.create(
            invoice=invoice, batch=self.batch, quantity=10,
            basic_rate=Decimal('100.00'), tax_amount=Decimal('0.00'),
            total_amount=Decimal('1000.00'),
        )
        invoice.submit()

        self.batch.refresh_from_db()
        self.assertEqual(self.batch.current_quantity, 10)

        ap_gl = GLEntry.objects.filter(
            reference_type='PurchaseInvoice', reference_id=invoice.id,
            account__name='Accounts Payable'
        )
        self.assertEqual(ap_gl.count(), 1)

    def test_cancel_cascades_to_purchase_receipt(self):
        """Cancelling invoice also cancels linked PR, reversing stock."""
        invoice = PurchaseInvoice.objects.create(
            supplier=self.supplier, invoice_number='INV-S13-004',
            date=date.today(), total_amount=Decimal('1000.00'),
        )
        PurchaseItem.objects.create(
            invoice=invoice, batch=self.batch, quantity=10,
            basic_rate=Decimal('100.00'), tax_amount=Decimal('0.00'),
            total_amount=Decimal('1000.00'),
        )
        invoice.submit()
        invoice.cancel()

        self.batch.refresh_from_db()
        self.assertEqual(self.batch.current_quantity, 0)

        invoice.refresh_from_db()
        self.assertEqual(invoice.purchase_receipt.status, 'CANCELLED')


class Sprint13GlobalGLBalanceTest(TestCase):
    """Verify GL remains perfectly balanced across fulfillment + invoicing."""

    def setUp(self):
        self.cat = Category.objects.create(name='S13Bal Cat', cgst_rate=9, sgst_rate=9)
        self.mfr = Manufacturer.objects.create(name='S13Bal Mfr')
        self.product = Product.objects.create(
            name='S13Bal Product', category=self.cat,
            unit_type='Kg', manufacturer=self.mfr,
        )
        self.customer = Customer.objects.create(name='S13Bal Customer')
        self.supplier = Supplier.objects.create(name='S13Bal Supplier')
        self.batch = Batch.objects.create(
            product=self.product, batch_number='S13BAL_B001',
            current_quantity=100, purchase_price=Decimal('100.00'),
            base_selling_price=Decimal('150.00'), mrp=Decimal('200.00'),
        )
        _seed(self.batch)

    def test_full_lifecycle_gl_balance(self):
        """Purchase Receipt + Invoice + Sale DN + Invoice: debits == credits."""
        # 1. Purchase: Receipt + Invoice
        pi = PurchaseInvoice.objects.create(
            supplier=self.supplier, invoice_number='BAL-PI-001',
            date=date.today(), total_amount=Decimal('1180.00'),
        )
        PurchaseItem.objects.create(
            invoice=pi, batch=self.batch, quantity=10,
            basic_rate=Decimal('100.00'), tax_amount=Decimal('180.00'),
            total_amount=Decimal('1180.00'),
        )
        pi.submit()

        # 2. Sale: DeliveryNote + Invoice
        si = SalesInvoice.objects.create(
            customer=self.customer,
            total_taxable=Decimal('200.00'),
            total_cgst=Decimal('18.00'),
            total_sgst=Decimal('18.00'),
            grand_total=Decimal('236.00'),
        )
        SalesItem.objects.create(
            invoice=si, batch=self.batch, quantity=2,
            unit_price=Decimal('118.00'), tax_rate=Decimal('18.00'),
            tax_amount=Decimal('36.00'), total_amount=Decimal('236.00'),
        )
        si.submit()

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

    def test_cancel_preserves_gl_balance(self):
        """After submit + cancel, GL remains balanced."""
        si = SalesInvoice.objects.create(
            customer=self.customer,
            total_taxable=Decimal('100.00'),
            total_cgst=Decimal('9.00'),
            total_sgst=Decimal('9.00'),
            grand_total=Decimal('118.00'),
        )
        SalesItem.objects.create(
            invoice=si, batch=self.batch, quantity=5,
            unit_price=Decimal('23.60'), tax_rate=Decimal('18.00'),
            tax_amount=Decimal('18.00'), total_amount=Decimal('118.00'),
        )
        si.submit()
        si.cancel()

        totals = GLEntry.objects.aggregate(
            total_debit=Sum('debit'),
            total_credit=Sum('credit'),
        )
        self.assertEqual(totals['total_debit'], totals['total_credit'])
