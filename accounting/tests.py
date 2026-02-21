"""
Sprint 9 — General Ledger Integration Tests.

Validates:
  1. Purchase creates Debit to Stock In Hand, Credit to SRNB.
  2. Sale creates Debit to COGS, Credit to Stock In Hand.
  3. Reconciliation creates correct GL routing based on sign.
  4. Unbalanced entries raise UnbalancedEntryError.
  5. GL entries are always balanced (debits == credits) for every movement.
  6. Returns and cancellations produce correctly reversed GL entries.
"""

from decimal import Decimal
from django.test import TestCase

from accounting.models import Account, GLEntry
from accounting.services import make_gl_entries, UnbalancedEntryError, post_stock_gl
from inventory.models import Batch, StockBin
from inventory.services import process_stock_movement, get_default_warehouse
from master_data.models import Category, Manufacturer, Product


class GLPostingEngineTests(TestCase):
    """Test the make_gl_entries() balance validator."""

    def test_balanced_entries_succeed(self):
        """Perfectly balanced entries should save without error."""
        entries = [
            {'account_name': 'Stock In Hand', 'debit': Decimal('100.00'), 'credit': Decimal('0.00')},
            {'account_name': 'Stock Received But Not Billed', 'debit': Decimal('0.00'), 'credit': Decimal('100.00')},
        ]
        created = make_gl_entries('TestDoc', 1, entries, remarks='test')
        self.assertEqual(len(created), 2)
        self.assertEqual(created[0].debit, Decimal('100.00'))
        self.assertEqual(created[1].credit, Decimal('100.00'))

    def test_unbalanced_entries_raise_error(self):
        """Entries where debits != credits MUST raise UnbalancedEntryError."""
        entries = [
            {'account_name': 'Stock In Hand', 'debit': Decimal('100.00'), 'credit': Decimal('0.00')},
            {'account_name': 'Cost of Goods Sold', 'debit': Decimal('0.00'), 'credit': Decimal('50.00')},
        ]
        with self.assertRaises(UnbalancedEntryError):
            make_gl_entries('TestDoc', 1, entries)

    def test_zero_value_entries_skip(self):
        """Zero-value movements should produce no GL entries."""
        result = post_stock_gl('PurchaseInvoice', 1, 0, Decimal('100.00'))
        self.assertEqual(result, [])


class Sprint9PurchaseGLTests(TestCase):
    """Test GL integration for Purchase flows."""

    def setUp(self):
        self.cat = Category.objects.create(name='GL Seeds', cgst_rate=9, sgst_rate=9)
        self.mfr = Manufacturer.objects.create(name='GL Mfr')
        self.product = Product.objects.create(
            name='GL Product', category=self.cat,
            unit_type='Kg', manufacturer=self.mfr,
        )
        self.batch = Batch.objects.create(
            product=self.product, batch_number='GL_B001',
            current_quantity=0,
            purchase_price=Decimal('100.00'),
            base_selling_price=Decimal('150.00'),
            mrp=Decimal('200.00'),
        )
        self.wh = get_default_warehouse()
        StockBin.objects.get_or_create(
            warehouse=self.wh, batch=self.batch,
            defaults={'actual_qty': 0},
        )

    def test_purchase_creates_stock_debit_and_srnb_credit(self):
        """Purchase of 10 @ 100 → Debit Stock In Hand 1000, Credit SRNB 1000."""
        process_stock_movement(self.batch.id, 10, 'PurchaseInvoice', 1, self.wh.id)

        gl_entries = GLEntry.objects.filter(reference_type='PurchaseInvoice', reference_id=1)
        self.assertEqual(gl_entries.count(), 2)

        debit_entry = gl_entries.get(debit__gt=0)
        credit_entry = gl_entries.get(credit__gt=0)

        self.assertEqual(debit_entry.account.name, 'Stock In Hand')
        self.assertEqual(debit_entry.debit, Decimal('1000.00'))  # 10 * 100

        self.assertEqual(credit_entry.account.name, 'Stock Received But Not Billed')
        self.assertEqual(credit_entry.credit, Decimal('1000.00'))

    def test_purchase_cancel_reverses_gl(self):
        """Cancelling a purchase reverses the GL: Debit SRNB, Credit Stock In Hand."""
        process_stock_movement(self.batch.id, 10, 'PurchaseInvoice', 1, self.wh.id)
        process_stock_movement(self.batch.id, -10, 'PurchaseInvoiceCancel', 1, self.wh.id)

        cancel_entries = GLEntry.objects.filter(reference_type='PurchaseInvoiceCancel', reference_id=1)
        self.assertEqual(cancel_entries.count(), 2)

        debit_entry = cancel_entries.get(debit__gt=0)
        credit_entry = cancel_entries.get(credit__gt=0)

        self.assertEqual(debit_entry.account.name, 'Stock Received But Not Billed')
        self.assertEqual(credit_entry.account.name, 'Stock In Hand')


class Sprint9SaleGLTests(TestCase):
    """Test GL integration for Sales flows."""

    def setUp(self):
        self.cat = Category.objects.create(name='GL Sale Seeds', cgst_rate=9, sgst_rate=9)
        self.mfr = Manufacturer.objects.create(name='GL Sale Mfr')
        self.product = Product.objects.create(
            name='GL Sale Product', category=self.cat,
            unit_type='Kg', manufacturer=self.mfr,
        )
        self.batch = Batch.objects.create(
            product=self.product, batch_number='GL_SALE_B001',
            current_quantity=50,
            purchase_price=Decimal('80.00'),
            base_selling_price=Decimal('120.00'),
            mrp=Decimal('150.00'),
        )
        self.wh = get_default_warehouse()
        StockBin.objects.get_or_create(
            warehouse=self.wh, batch=self.batch,
            defaults={'actual_qty': 50},
        )

    def test_sale_creates_cogs_debit_and_stock_credit(self):
        """Sale of 5 @ 80 purchase price → Debit COGS 400, Credit Stock In Hand 400."""
        process_stock_movement(self.batch.id, -5, 'SalesInvoice', 2, self.wh.id)

        gl_entries = GLEntry.objects.filter(reference_type='SalesInvoice', reference_id=2)
        self.assertEqual(gl_entries.count(), 2)

        debit_entry = gl_entries.get(debit__gt=0)
        credit_entry = gl_entries.get(credit__gt=0)

        self.assertEqual(debit_entry.account.name, 'Cost of Goods Sold')
        self.assertEqual(debit_entry.debit, Decimal('400.00'))  # 5 * 80

        self.assertEqual(credit_entry.account.name, 'Stock In Hand')
        self.assertEqual(credit_entry.credit, Decimal('400.00'))

    def test_sales_return_reverses_cogs(self):
        """Sales return of 3 @ 80 → Debit Stock In Hand 240, Credit COGS 240."""
        process_stock_movement(self.batch.id, -5, 'SalesInvoice', 2, self.wh.id)
        process_stock_movement(self.batch.id, 3, 'SalesReturn', 3, self.wh.id)

        return_entries = GLEntry.objects.filter(reference_type='SalesReturn', reference_id=3)
        self.assertEqual(return_entries.count(), 2)

        debit_entry = return_entries.get(debit__gt=0)
        credit_entry = return_entries.get(credit__gt=0)

        self.assertEqual(debit_entry.account.name, 'Stock In Hand')
        self.assertEqual(credit_entry.account.name, 'Cost of Goods Sold')


class Sprint9ReconciliationGLTests(TestCase):
    """Test GL integration for stock reconciliation."""

    def setUp(self):
        self.cat = Category.objects.create(name='GL Recon Seeds', cgst_rate=9, sgst_rate=9)
        self.mfr = Manufacturer.objects.create(name='GL Recon Mfr')
        self.product = Product.objects.create(
            name='GL Recon Product', category=self.cat,
            unit_type='Kg', manufacturer=self.mfr,
        )
        self.batch = Batch.objects.create(
            product=self.product, batch_number='GL_RECON_B001',
            current_quantity=10,
            purchase_price=Decimal('50.00'),
            base_selling_price=Decimal('80.00'),
            mrp=Decimal('100.00'),
        )
        self.wh = get_default_warehouse()
        StockBin.objects.get_or_create(
            warehouse=self.wh, batch=self.batch,
            defaults={'actual_qty': 10},
        )

    def test_reconciliation_up_creates_stock_debit_adjustment_credit(self):
        """Recon 10→12 (+2) @ 50 → Debit Stock In Hand 100, Credit Inventory Adjustment 100."""
        from inventory.services import reconcile_stock
        reconcile_stock(self.batch.id, 12, 'Count Error')

        gl_entries = GLEntry.objects.filter(reference_type='StockReconciliation')
        self.assertEqual(gl_entries.count(), 2)

        debit_entry = gl_entries.get(debit__gt=0)
        credit_entry = gl_entries.get(credit__gt=0)

        self.assertEqual(debit_entry.account.name, 'Stock In Hand')
        self.assertEqual(debit_entry.debit, Decimal('100.00'))  # 2 * 50

        self.assertEqual(credit_entry.account.name, 'Inventory Adjustment')
        self.assertEqual(credit_entry.credit, Decimal('100.00'))

    def test_reconciliation_down_creates_adjustment_debit_stock_credit(self):
        """Recon 10→7 (-3) @ 50 → Debit Inventory Adjustment 150, Credit Stock In Hand 150."""
        from inventory.services import reconcile_stock
        reconcile_stock(self.batch.id, 7, 'Damage')

        gl_entries = GLEntry.objects.filter(reference_type='StockReconciliation')
        self.assertEqual(gl_entries.count(), 2)

        debit_entry = gl_entries.get(debit__gt=0)
        credit_entry = gl_entries.get(credit__gt=0)

        self.assertEqual(debit_entry.account.name, 'Inventory Adjustment')
        self.assertEqual(debit_entry.debit, Decimal('150.00'))  # 3 * 50

        self.assertEqual(credit_entry.account.name, 'Stock In Hand')
        self.assertEqual(credit_entry.credit, Decimal('150.00'))

    def test_reconciliation_no_change_creates_no_gl(self):
        """Recon 10→10 (delta=0) creates no GL entries."""
        from inventory.services import reconcile_stock
        reconcile_stock(self.batch.id, 10, 'Count Error')

        gl_entries = GLEntry.objects.filter(reference_type='StockReconciliation')
        self.assertEqual(gl_entries.count(), 0)


class Sprint9GlobalBalanceTest(TestCase):
    """Verify that GL is always balanced across all operations."""

    def setUp(self):
        self.cat = Category.objects.create(name='GL Balance Seeds', cgst_rate=9, sgst_rate=9)
        self.mfr = Manufacturer.objects.create(name='GL Balance Mfr')
        self.product = Product.objects.create(
            name='GL Balance Product', category=self.cat,
            unit_type='Kg', manufacturer=self.mfr,
        )
        self.batch = Batch.objects.create(
            product=self.product, batch_number='GL_BAL_B001',
            current_quantity=0,
            purchase_price=Decimal('100.00'),
            base_selling_price=Decimal('150.00'),
            mrp=Decimal('200.00'),
        )
        self.wh = get_default_warehouse()
        StockBin.objects.get_or_create(
            warehouse=self.wh, batch=self.batch,
            defaults={'actual_qty': 0},
        )

    def test_full_lifecycle_gl_balances(self):
        """Purchase → Sale → Return → Cancel: total debits must equal total credits."""
        from django.db.models import Sum

        # Purchase 20 @ 100
        process_stock_movement(self.batch.id, 20, 'PurchaseInvoice', 1, self.wh.id)
        # Sale 5 @ 100 cost
        process_stock_movement(self.batch.id, -5, 'SalesInvoice', 2, self.wh.id)
        # Sales Return 2 @ 100 cost
        process_stock_movement(self.batch.id, 2, 'SalesReturn', 3, self.wh.id)
        # Purchase Return 3 @ 100 cost
        process_stock_movement(self.batch.id, -3, 'PurchaseReturn', 4, self.wh.id)

        totals = GLEntry.objects.aggregate(
            total_debit=Sum('debit'),
            total_credit=Sum('credit'),
        )

        self.assertEqual(
            totals['total_debit'],
            totals['total_credit'],
            f"GL unbalanced! Debits={totals['total_debit']}, Credits={totals['total_credit']}",
        )
