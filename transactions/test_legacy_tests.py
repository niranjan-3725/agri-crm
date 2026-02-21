from django.test import TestCase, Client
from django.urls import reverse
from master_data.models import Supplier, Product, Category, Manufacturer, Customer
from transactions.models import PurchaseInvoice, PurchaseItem, SalesInvoice, SalesItem, SalesReturn, PurchaseReturn
from inventory.models import Batch, StockMovement
from datetime import date
from decimal import Decimal
import json

class PurchaseCreateViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.create_url = reverse('create_purchase')
        
        # Setup Master Data
        self.supplier = Supplier.objects.create(name="Test Supplier", phone="1234567890", gstin="22AAAAA0000A1Z5", address="Test Address")
        self.category = Category.objects.create(name="Seeds", cgst_rate=9, sgst_rate=9)
        self.manufacturer = Manufacturer.objects.create(name="AgriCorp")
        self.product = Product.objects.create(
            name="Super Seed",
            hsn_code="1234",
            unit_type="Kg",
            category=self.category,
            manufacturer=self.manufacturer
        )

        self.valid_data = {
            'supplier': self.supplier.id,
            'invoice_number': 'INV-TEST-001',
            'date': date.today().strftime('%Y-%m-%d'),
            # Row 1
            'product_id_0': self.product.id,
            'product_name[]': [self.product.name],
            'batch_number[]': ['B001'],
            'mfg_date[]': ['2023-01-01'],
            'expiry_date[]': ['2025-01-01'],
            'size[]': ['1.0'],
            'unit[]': ['Kg'],
            'qty[]': ['10'],
            'purchase_rate[]': ['100'], # Basic Rate
            'mrp[]': ['200'],
            'margin[]': ['20'],
            'selling_price[]': ['141.60'],
            # Extras
            'loading_charges': '10',
            'discount': '5'
        }

    def test_purchase_create_view_status_code(self):
        response = self.client.get(self.create_url)
        self.assertEqual(response.status_code, 200)

    def test_purchase_create_template(self):
        response = self.client.get(self.create_url)
        self.assertTemplateUsed(response, 'transactions/purchase_form.html')

    def test_context_data(self):
        response = self.client.get(self.create_url)
        self.assertIn('suppliers', response.context)
        self.assertIn('categories', response.context)
        self.assertIn('manufacturers', response.context)
        self.assertEqual(len(response.context['suppliers']), 1)

    def test_valid_submission(self):
        response = self.client.post(self.create_url, self.valid_data)
        self.assertEqual(response.status_code, 302) 
        
        # Verify Object Creation
        self.assertEqual(PurchaseInvoice.objects.count(), 1)
        invoice = PurchaseInvoice.objects.first()
        self.assertEqual(invoice.invoice_number, 'INV-TEST-001')
        self.assertEqual(invoice.loading_charges, 50.00)
        self.assertEqual(invoice.additional_discount, 10.00)
        
        self.assertEqual(PurchaseItem.objects.count(), 1)
        item = PurchaseItem.objects.first()
        self.assertEqual(item.invoice, invoice)
        self.assertEqual(item.batch.product, self.product)
        # Check basic_rate
        self.assertEqual(item.basic_rate, 100.00)

    def test_payment_status_logic(self):
        # 1. Test UNPAID
        data_unpaid = self.valid_data.copy()
        data_unpaid['invoice_number'] = 'INV-UNPAID'
        data_unpaid['payment_status'] = 'UNPAID'
        data_unpaid['amount_paid'] = '0'
        
        response = self.client.post(self.create_url, data_unpaid)
        if response.status_code != 302:
            print(f"Form Errors: {response.context.get('error')}")
            # Also print form errors if available
            if 'form' in response.context:
                print(f"Form Errors: {response.context['form'].errors}")
        self.assertEqual(response.status_code, 302)
        
        invoice_unpaid = PurchaseInvoice.objects.get(invoice_number='INV-UNPAID')
        self.assertEqual(invoice_unpaid.payment_status, 'UNPAID')
        self.assertEqual(invoice_unpaid.balance_due, invoice_unpaid.total_amount)
        self.assertEqual(invoice_unpaid.amount_paid, 0)
        
        # 2. Test PAID (Full)
        data_paid = self.valid_data.copy()
        data_paid['invoice_number'] = 'INV-PAID'
        data_paid['payment_status'] = 'PAID'
        # Even if we send 0, view logic should set it to total
        data_paid['amount_paid'] = '0' 
        
        self.client.post(self.create_url, data_paid)
        invoice_paid = PurchaseInvoice.objects.get(invoice_number='INV-PAID')
        self.assertEqual(invoice_paid.payment_status, 'PAID')
        self.assertEqual(invoice_paid.balance_due, 0)
        self.assertEqual(invoice_paid.amount_paid, invoice_paid.total_amount)
        
        # 3. Test PARTIAL
        data_partial = self.valid_data.copy()
        data_partial['invoice_number'] = 'INV-PARTIAL'
        data_partial['payment_status'] = 'PARTIAL'
        data_partial['amount_paid'] = '100' # Partial amount
        
        self.client.post(self.create_url, data_partial)
        invoice_partial = PurchaseInvoice.objects.get(invoice_number='INV-PARTIAL')
        self.assertEqual(invoice_partial.payment_status, 'PARTIAL')
        self.assertEqual(invoice_partial.amount_paid, 100)
        self.assertEqual(invoice_partial.balance_due, invoice_partial.total_amount - 100)


class PurchaseEditViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        
        # Master Data
        self.supplier = Supplier.objects.create(name="Edit Supplier")
        self.category = Category.objects.create(name="Edit Cat", cgst_rate=9, sgst_rate=9)
        self.manufacturer = Manufacturer.objects.create(name="Edit Manu")
        self.product = Product.objects.create(name="Edit Product", unit_type="Kg", category=self.category, manufacturer=self.manufacturer)

        # Create Existing Invoice
        self.invoice = PurchaseInvoice.objects.create(
            supplier=self.supplier,
            invoice_number='INV-EDIT-001',
            date=date.today(),
            loading_charges=10,
            additional_discount=5,
            total_amount=1000
        )
        
        self.batch = Batch.objects.create(
            product=self.product,
            batch_number='B-EDIT',
            purchase_price=118, # Net
            base_selling_price=150,
            mrp=200,
            current_quantity=5 
        )

        self.item = PurchaseItem.objects.create(
            invoice=self.invoice,
            batch=self.batch,
            quantity=5,
            basic_rate=100.00,
            tax_amount=90.00,
            selling_price=150.00,
            profit_margin=25.00, # 25% margin
            total_amount=590.00
        )
        
        self.url = reverse('purchase_edit', args=[self.invoice.pk])

    def test_edit_page_loads_data(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'transactions/purchase_form.html')
        
        # Check context for existing_items mapping
        self.assertIn('existing_items_json', response.context)
        existing_items = json.loads(response.context['existing_items_json'])
        self.assertTrue(len(existing_items) > 0)
        

    
    def test_edit_page_saves_changes(self):
        """Sprint 4: Editing creates a new amended invoice and cancels the original."""
        data = {
            'supplier': self.supplier.id,
            'invoice_number': 'INV-EDIT-UPDATED',
            'date': date.today().strftime('%Y-%m-%d'),
            # Items
            'product_name[]': ['Edit Product'],
            'batch_number[]': ['B-EDIT'],
            'mfg_date[]': ['2023-01-01'],
            'expiry_date[]': ['2025-01-01'],
            'size[]': ['1.0'],
            'unit[]': ['Kg'],
            'qty[]': ['5'],
            'purchase_rate[]': ['120.00'],
            'mrp[]': ['200'],
            'margin[]': ['30.00'],
            'selling_price[]': ['156.00'],
            # Extras
            'loading_charges': '15',
            'discount': '10'
        }
        
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 302)
        
        # Sprint 4: Original is now CANCELLED
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, 'CANCELLED')
        
        # New amended invoice created
        new_invoice = PurchaseInvoice.objects.filter(amended_from=self.invoice).first()
        self.assertIsNotNone(new_invoice)
        self.assertEqual(new_invoice.status, 'ACTIVE')
        self.assertEqual(new_invoice.invoice_number, 'INV-EDIT-UPDATED')
        
        # Verify new item on amended invoice
        new_item = new_invoice.items.first()
        self.assertIsNotNone(new_item)
        self.assertEqual(float(new_item.basic_rate), 120.00)
        self.assertEqual(float(new_item.profit_margin), 30.00)

from inventory.models import StockMovement
from .models import SalesInvoice, SalesItem, SalesReturn, SalesReturnItem

class OutwardFlowLedgerTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.supplier = Supplier.objects.create(name="Test Supplier")
        self.category = Category.objects.create(name="Seeds", cgst_rate=9, sgst_rate=9)
        self.manufacturer = Manufacturer.objects.create(name="AgriCorp")
        self.product = Product.objects.create(name="Super Seed", unit_type="Kg", category=self.category, manufacturer=self.manufacturer)
        self.customer = Customer.objects.create(name="Test Customer")

        self.batch = Batch.objects.create(
            product=self.product,
            batch_number='B002',
            purchase_price=Decimal('100.00'),
            mrp=Decimal('200.00'),
            base_selling_price=Decimal('150.00'),
            current_quantity=10
        )

    def test_sale_deduction_bug_1_fix(self):
        """Test Sale Deduction (Bug #1 Fix): Assert StockMovement is created & Batch decreases."""
        data = {
            'customer': self.customer.id,
            'date': date.today().strftime('%Y-%m-%d'),
            'batch_id[]': [self.batch.id],
            'qty[]': ['5'],
            'price[]': ['150.00'],
            'payment_status': 'UNPAID',
        }
        response = self.client.post(reverse('create_sale'), data)
        self.assertEqual(response.status_code, 302)
        
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.current_quantity, 5)

        movements = StockMovement.objects.filter(batch=self.batch)
        self.assertEqual(movements.count(), 1)
        self.assertEqual(movements.first().quantity, -5)
        self.assertEqual(movements.first().reference_document_type, 'SalesInvoice')

    def test_sale_return_addition(self):
        """Test Sale Return Addition: Return units, check StockMovement and batch quantity."""
        # Create an initial sale manually or mock it.
        invoice = SalesInvoice.objects.create(
            customer=self.customer, 
            grand_total=0,
            total_taxable=0,
            total_cgst=0,
            total_sgst=0
        )
        SalesItem.objects.create(invoice=invoice, batch=self.batch, quantity=2, unit_price=100, tax_rate=0, tax_amount=0, total_amount=200)
        
        data = {
            'customer': self.customer.id,
            'date': date.today().strftime('%Y-%m-%d'),
            'original_sale': invoice.id,
            'batch_id[]': [self.batch.id],
            'qty[]': ['2'],
            'price[]': ['100.00'],
        }
        response = self.client.post(reverse('create_sales_return'), data)
        self.assertEqual(response.status_code, 302)

        self.batch.refresh_from_db()
        self.assertEqual(self.batch.current_quantity, 12) # 10 + 2
        
        movements = StockMovement.objects.filter(batch=self.batch)
        self.assertEqual(movements.count(), 1)
        self.assertEqual(movements.first().quantity, 2)
        self.assertEqual(movements.first().reference_document_type, 'SalesReturn')

    def test_negative_stock_block_on_sale(self):
        """Test Negative Stock Block: Try to sell 50 units. Assert transaction rollback."""
        data = {
            'customer': self.customer.id,
            'date': date.today().strftime('%Y-%m-%d'),
            'batch_id[]': [self.batch.id],
            'qty[]': ['50'],
            'price[]': ['150.00'],
        }
        
        response = self.client.post(reverse('create_sale'), data)
        # Assuming forms with errors return 200 with the template
        self.assertEqual(response.status_code, 200)
        self.assertIn('error', response.context)

        self.batch.refresh_from_db()
        self.assertEqual(self.batch.current_quantity, 10)  # No deduction applied

        self.assertEqual(SalesInvoice.objects.count(), 0)
        self.assertEqual(StockMovement.objects.filter(batch=self.batch).count(), 0)

    def test_invoice_deletion_restoration(self):
        """Test Invoice Deletion Restoration: Deleting a valid invoice restores stock via ledger."""
        data = {
            'customer': self.customer.id,
            'date': date.today().strftime('%Y-%m-%d'),
            'batch_id[]': [self.batch.id],
            'qty[]': ['5'],
            'price[]': ['150.00'],
            'payment_status': 'UNPAID',
        }
        self.client.post(reverse('create_sale'), data)
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.current_quantity, 5)

        invoice = SalesInvoice.objects.first()
        response = self.client.post(reverse('delete_invoice', args=[invoice.id]))
        self.assertEqual(response.status_code, 302)

        self.batch.refresh_from_db()
        self.assertEqual(self.batch.current_quantity, 10)

        movements = StockMovement.objects.filter(batch=self.batch).order_by('created_at')
        self.assertEqual(movements.count(), 2)
        self.assertEqual(movements[0].reference_document_type, 'SalesInvoice')
        self.assertEqual(movements[0].quantity, -5)
        self.assertEqual(movements[1].reference_document_type, 'SalesInvoiceCancel')
        self.assertEqual(movements[1].quantity, 5)

        # Sprint 3: Invoice record is NOT deleted — it's marked CANCELLED
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, 'CANCELLED')
        self.assertEqual(SalesInvoice.objects.count(), 1)  # Still in DB


class InwardFlowLedgerTests(TestCase):
    """Sprint 2.5: Validate the Purchase (Inward) Flow uses the StockMovement ledger."""

    def setUp(self):
        self.client = Client()
        self.supplier = Supplier.objects.create(
            name="Test Supplier", phone="1234567890",
            gstin="22AAAAA0000A1Z5", address="Test Address"
        )
        self.category = Category.objects.create(name="Seeds", cgst_rate=9, sgst_rate=9)
        self.manufacturer = Manufacturer.objects.create(name="AgriCorp")
        self.product = Product.objects.create(
            name="Inward Test Product", hsn_code="1234",
            unit_type="Kg", category=self.category,
            manufacturer=self.manufacturer,
        )

    def _purchase_data(self, inv_num='INV-IN-001', qty='10', batch_no='BINWARD'):
        return {
            'supplier': self.supplier.id,
            'invoice_number': inv_num,
            'date': date.today().strftime('%Y-%m-%d'),
            'product_name[]': [self.product.name],
            'batch_number[]': [batch_no],
            'mfg_date[]': ['2023-01-01'],
            'expiry_date[]': ['2025-01-01'],
            'size[]': ['1.0'],
            'unit[]': ['Kg'],
            'qty[]': [qty],
            'purchase_rate[]': ['100'],
            'mrp[]': ['200'],
            'margin[]': ['20'],
            'selling_price[]': ['141.60'],
            'loading_charges': '0',
            'discount': '0',
        }

    def test_create_purchase_creates_ledger_entry_and_updates_batch(self):
        """Gap 4 fix: create_purchase must create a + StockMovement and update Batch qty."""
        data = self._purchase_data()
        response = self.client.post(reverse('create_purchase'), data)
        self.assertEqual(response.status_code, 302)

        invoice = PurchaseInvoice.objects.first()
        self.assertIsNotNone(invoice)

        batch = Batch.objects.get(batch_number='BINWARD')
        self.assertEqual(batch.current_quantity, 10)

        movements = StockMovement.objects.filter(batch=batch)
        self.assertEqual(movements.count(), 1)
        self.assertEqual(movements.first().quantity, 10)
        self.assertEqual(movements.first().reference_document_type, 'PurchaseInvoice')
        self.assertEqual(movements.first().reference_document_id, invoice.id)

    def test_purchase_delete_creates_negative_ledger_and_reverses_stock(self):
        """Gap 3 fix: purchase_delete must create a - StockMovement and deduct stock."""
        # Create purchase first
        data = self._purchase_data(inv_num='INV-DEL-001')
        self.client.post(reverse('create_purchase'), data)

        batch = Batch.objects.get(batch_number='BINWARD')
        self.assertEqual(batch.current_quantity, 10)

        invoice = PurchaseInvoice.objects.first()
        response = self.client.post(reverse('purchase_delete', args=[invoice.id]))
        self.assertEqual(response.status_code, 302)

        batch.refresh_from_db()
        self.assertEqual(batch.current_quantity, 0)

        movements = StockMovement.objects.filter(batch=batch).order_by('created_at')
        self.assertEqual(movements.count(), 2)
        self.assertEqual(movements[0].quantity, 10)
        self.assertEqual(movements[0].reference_document_type, 'PurchaseInvoice')
        self.assertEqual(movements[1].quantity, -10)
        self.assertEqual(movements[1].reference_document_type, 'PurchaseInvoiceCancel')

        # Sprint 3: Invoice record is NOT deleted — it's marked CANCELLED
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, 'CANCELLED')
        self.assertEqual(PurchaseInvoice.objects.count(), 1)  # Still in DB


class StaleStateSaleFixTests(TestCase):
    """Sprint 2.5: Validate that selling multiple items from the same batch
    in one request works correctly (proves refresh_from_db stale-state fix)."""

    def setUp(self):
        self.client = Client()
        self.category = Category.objects.create(name="Seeds", cgst_rate=9, sgst_rate=9)
        self.manufacturer = Manufacturer.objects.create(name="AgriCorp")
        self.product = Product.objects.create(
            name="Multi Batch Product", unit_type="Kg",
            category=self.category, manufacturer=self.manufacturer,
        )
        self.customer = Customer.objects.create(name="Test Customer")
        self.batch = Batch.objects.create(
            product=self.product,
            batch_number='BMULTI',
            purchase_price=Decimal('100.00'),
            mrp=Decimal('200.00'),
            base_selling_price=Decimal('150.00'),
            current_quantity=20,
        )

    def test_two_items_same_batch_deducts_correctly(self):
        """If two line items reference the same batch (qty=7 + qty=5), total deduction
        should be 12 and the batch should have 8 remaining. Without refresh_from_db,
        item.clean() on the 2nd item would see stale qty=20 instead of 13."""
        from .models import SalesInvoice as SI
        data = {
            'customer': self.customer.id,
            'date': date.today().strftime('%Y-%m-%d'),
            'batch_id[]': [str(self.batch.id), str(self.batch.id)],
            'qty[]': ['7', '5'],
            'price[]': ['150.00', '150.00'],
            'payment_status': 'UNPAID',
        }
        response = self.client.post(reverse('create_sale'), data)
        self.assertEqual(response.status_code, 302)

        self.batch.refresh_from_db()
        self.assertEqual(self.batch.current_quantity, 8)  # 20 - 7 - 5

        movements = StockMovement.objects.filter(batch=self.batch).order_by('created_at')
        self.assertEqual(movements.count(), 2)
        self.assertEqual(movements[0].quantity, -7)
        self.assertEqual(movements[1].quantity, -5)


class ImmutableDocumentTests(TestCase):
    """Sprint 3: Validate immutable document architecture —
    .delete() is blocked, .cancel() works, cancelled invoices are filtered."""

    def setUp(self):
        self.client = Client()
        self.supplier = Supplier.objects.create(
            name="Test Supplier", phone="1234567890",
            gstin="22AAAAA0000A1Z5", address="Test Address"
        )
        self.category = Category.objects.create(name="Seeds", cgst_rate=9, sgst_rate=9)
        self.manufacturer = Manufacturer.objects.create(name="AgriCorp")
        self.product = Product.objects.create(
            name="Immutable Test Product", hsn_code="1234",
            unit_type="Kg", category=self.category,
            manufacturer=self.manufacturer,
        )
        self.customer = Customer.objects.create(name="Test Customer")
        self.batch = Batch.objects.create(
            product=self.product,
            batch_number='BIMMUT',
            purchase_price=Decimal('100.00'),
            mrp=Decimal('200.00'),
            base_selling_price=Decimal('150.00'),
            current_quantity=50,
        )

    def _create_sales_invoice(self):
        """Helper: create a valid SalesInvoice with one item."""
        from django.core.exceptions import ValidationError as DjangoValidationError
        invoice = SalesInvoice.objects.create(
            customer=self.customer,
            grand_total=Decimal('150.00'),
            total_taxable=Decimal('142.86'),
            total_cgst=Decimal('3.57'),
            total_sgst=Decimal('3.57'),
        )
        from .models import SalesItem
        SalesItem.objects.create(
            invoice=invoice, batch=self.batch,
            quantity=5, unit_price=Decimal('150.00'),
            tax_rate=Decimal('5.00'), tax_amount=Decimal('7.14'),
            total_amount=Decimal('150.00'),
        )
        # Deduct stock via ledger (simulating what create_sale does)
        from inventory.services import process_stock_movement
        process_stock_movement(
            batch_id=self.batch.id, quantity=-5,
            doc_type='SalesInvoice', doc_id=invoice.id,
        )
        return invoice

    def _create_purchase_invoice(self):
        """Helper: create a valid PurchaseInvoice with one item."""
        invoice = PurchaseInvoice.objects.create(
            supplier=self.supplier,
            invoice_number=f'INV-IMMUT-{PurchaseInvoice.objects.count()}',
            date=date.today(),
            total_amount=Decimal('1000.00'),
        )
        PurchaseItem.objects.create(
            invoice=invoice, batch=self.batch,
            quantity=10, basic_rate=Decimal('100.00'),
            tax_amount=Decimal('18.00'), selling_price=Decimal('150.00'),
            profit_margin=Decimal('20.00'), total_amount=Decimal('1000.00'),
        )
        from inventory.services import process_stock_movement
        process_stock_movement(
            batch_id=self.batch.id, quantity=10,
            doc_type='PurchaseInvoice', doc_id=invoice.id,
        )
        return invoice

    # --- .delete() is blocked ---

    def test_sales_invoice_delete_raises(self):
        """Calling .delete() on SalesInvoice must raise ValidationError."""
        invoice = self._create_sales_invoice()
        from django.core.exceptions import ValidationError as DjangoValidationError
        with self.assertRaises(DjangoValidationError):
            invoice.delete()
        # Record must still exist
        self.assertTrue(SalesInvoice.objects.filter(pk=invoice.pk).exists())

    def test_purchase_invoice_delete_raises(self):
        """Calling .delete() on PurchaseInvoice must raise ValidationError."""
        invoice = self._create_purchase_invoice()
        from django.core.exceptions import ValidationError as DjangoValidationError
        with self.assertRaises(DjangoValidationError):
            invoice.delete()
        self.assertTrue(PurchaseInvoice.objects.filter(pk=invoice.pk).exists())

    # --- .cancel() works correctly ---

    def test_sales_invoice_cancel_creates_ledger_and_marks_cancelled(self):
        """cancel() must reverse stock, create StockMovement, and set status=CANCELLED."""
        invoice = self._create_sales_invoice()
        self.batch.refresh_from_db()
        qty_before = self.batch.current_quantity  # 50 - 5 = 45

        invoice.cancel()

        # Status check
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, 'CANCELLED')

        # Stock restored
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.current_quantity, qty_before + 5)

        # Ledger entry created
        cancel_movements = StockMovement.objects.filter(
            batch=self.batch,
            reference_document_type='SalesInvoiceCancel',
            reference_document_id=invoice.id,
        )
        self.assertEqual(cancel_movements.count(), 1)
        self.assertEqual(cancel_movements.first().quantity, 5)

    def test_purchase_invoice_cancel_creates_ledger_and_marks_cancelled(self):
        """cancel() must reverse stock, create StockMovement, and set status=CANCELLED."""
        invoice = self._create_purchase_invoice()
        self.batch.refresh_from_db()
        qty_before = self.batch.current_quantity  # 50 + 10 = 60

        invoice.cancel()

        invoice.refresh_from_db()
        self.assertEqual(invoice.status, 'CANCELLED')

        self.batch.refresh_from_db()
        self.assertEqual(self.batch.current_quantity, qty_before - 10)

        cancel_movements = StockMovement.objects.filter(
            batch=self.batch,
            reference_document_type='PurchaseInvoiceCancel',
            reference_document_id=invoice.id,
        )
        self.assertEqual(cancel_movements.count(), 1)
        self.assertEqual(cancel_movements.first().quantity, -10)

    # --- Double-cancel is blocked ---

    def test_double_cancel_raises(self):
        """Calling cancel() twice must raise ValidationError."""
        invoice = self._create_sales_invoice()
        invoice.cancel()
        from django.core.exceptions import ValidationError as DjangoValidationError
        with self.assertRaises(DjangoValidationError):
            invoice.cancel()

    # --- Cancelled invoices are excluded from lists ---

    def test_sales_list_excludes_cancelled(self):
        """The sales_list view must not show CANCELLED invoices."""
        invoice = self._create_sales_invoice()
        # Before cancel: should appear
        response = self.client.get(reverse('sales_list'))
        self.assertIn(invoice, response.context['invoices'].object_list)

        invoice.cancel()

        # After cancel: should NOT appear
        response = self.client.get(reverse('sales_list'))
        self.assertNotIn(invoice, response.context['invoices'].object_list)


class AmendLifecycleTests(TestCase):
    """Sprint 4: Validate the Amend lifecycle —
    editing cancels the old doc and creates a new linked version."""

    def setUp(self):
        self.client = Client()
        self.supplier = Supplier.objects.create(
            name="Test Supplier", phone="1234567890",
            gstin="22AAAAA0000A1Z5", address="Test Address"
        )
        self.category = Category.objects.create(name="Seeds", cgst_rate=9, sgst_rate=9)
        self.manufacturer = Manufacturer.objects.create(name="AgriCorp")
        self.product = Product.objects.create(
            name="Amend Product", hsn_code="1234",
            unit_type="Kg", category=self.category,
            manufacturer=self.manufacturer,
        )
        self.customer = Customer.objects.create(name="Test Customer")
        self.batch = Batch.objects.create(
            product=self.product,
            batch_number='BAMEND',
            purchase_price=Decimal('100.00'),
            mrp=Decimal('200.00'),
            base_selling_price=Decimal('150.00'),
            current_quantity=50,
        )

    # --- Sales Amend ---

    def test_edit_cancelled_sale_is_blocked(self):
        """Editing a CANCELLED sales invoice must redirect with error."""
        invoice = SalesInvoice.objects.create(
            customer=self.customer,
            grand_total=Decimal('100.00'),
            total_taxable=Decimal('90.00'),
            total_cgst=Decimal('5.00'),
            total_sgst=Decimal('5.00'),
        )
        invoice.status = 'CANCELLED'
        invoice.save()
        response = self.client.get(reverse('edit_sale', args=[invoice.pk]))
        self.assertEqual(response.status_code, 302)

    def test_edit_sale_creates_two_invoices(self):
        """Editing an active sale must cancel the old and create a new ACTIVE invoice."""
        # First create a sale via the view
        create_data = {
            'customer': self.customer.id,
            'date': date.today().strftime('%Y-%m-%d'),
            'batch_id[]': [str(self.batch.id)],
            'qty[]': ['5'],
            'price[]': ['150.00'],
            'payment_status': 'UNPAID',
        }
        self.client.post(reverse('create_sale'), create_data)
        original = SalesInvoice.objects.first()
        self.assertIsNotNone(original)
        self.assertEqual(original.status, 'ACTIVE')

        self.batch.refresh_from_db()
        qty_after_sale = self.batch.current_quantity  # 50 - 5 = 45

        # Now edit it — change qty from 5 to 3
        edit_data = {
            'customer': self.customer.id,
            'date': date.today().strftime('%Y-%m-%d'),
            'batch_id[]': [str(self.batch.id)],
            'qty[]': ['3'],
            'price[]': ['150.00'],
            'payment_status': 'UNPAID',
        }
        response = self.client.post(reverse('edit_sale', args=[original.pk]), edit_data)
        self.assertEqual(response.status_code, 302)

        # Two invoices should exist
        self.assertEqual(SalesInvoice.objects.count(), 2)

        # Original must be CANCELLED
        original.refresh_from_db()
        self.assertEqual(original.status, 'CANCELLED')

        # New invoice must be ACTIVE and linked
        new_inv = SalesInvoice.objects.filter(amended_from=original).first()
        self.assertIsNotNone(new_inv)
        self.assertEqual(new_inv.status, 'ACTIVE')
        self.assertEqual(new_inv.items.count(), 1)
        self.assertEqual(new_inv.items.first().quantity, 3)

        # Stock: original sold 5, cancel restored 5, new sold 3 → net = 50 - 3 = 47
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.current_quantity, 47)

        # Ledger: 4 entries total
        movements = StockMovement.objects.filter(batch=self.batch).order_by('created_at')
        self.assertEqual(movements.count(), 3)
        self.assertEqual(movements[0].quantity, -5)   # Original sale
        self.assertEqual(movements[1].quantity, 5)    # Cancel (restore)
        self.assertEqual(movements[2].quantity, -3)   # Amended sale

    # --- Purchase Amend ---

    def test_edit_cancelled_purchase_is_blocked(self):
        """Editing a CANCELLED purchase invoice must redirect with error."""
        invoice = PurchaseInvoice.objects.create(
            supplier=self.supplier,
            invoice_number='INV-CANCEL-BLOCK',
            date=date.today(),
            total_amount=Decimal('1000.00'),
        )
        invoice.status = 'CANCELLED'
        invoice.save()
        response = self.client.get(reverse('purchase_edit', args=[invoice.pk]))
        self.assertEqual(response.status_code, 302)

    def test_edit_purchase_creates_two_invoices(self):
        """Editing an active purchase must cancel the old and create a new ACTIVE invoice."""
        # Create a purchase via the view
        create_data = {
            'supplier': self.supplier.id,
            'invoice_number': 'INV-AMEND-001',
            'date': date.today().strftime('%Y-%m-%d'),
            'product_name[]': ['Amend Product'],
            'batch_number[]': ['BAMEND'],
            'mfg_date[]': ['2023-01-01'],
            'expiry_date[]': ['2025-01-01'],
            'size[]': ['1.0'],
            'unit[]': ['Kg'],
            'qty[]': ['10'],
            'purchase_rate[]': ['100'],
            'mrp[]': ['200'],
            'margin[]': ['20'],
            'selling_price[]': ['141.60'],
            'loading_charges': '10',
            'discount': '5',
        }
        self.client.post(reverse('create_purchase'), create_data)
        original = PurchaseInvoice.objects.filter(invoice_number='INV-AMEND-001').first()
        self.assertIsNotNone(original)

        self.batch.refresh_from_db()
        qty_after_purchase = self.batch.current_quantity  # 50 + 10 = 60

        # Edit: change qty from 10 to 7
        edit_data = {
            'supplier': self.supplier.id,
            'invoice_number': 'INV-AMEND-001',
            'date': date.today().strftime('%Y-%m-%d'),
            'product_name[]': ['Amend Product'],
            'batch_number[]': ['BAMEND'],
            'mfg_date[]': ['2023-01-01'],
            'expiry_date[]': ['2025-01-01'],
            'size[]': ['1.0'],
            'unit[]': ['Kg'],
            'qty[]': ['7'],
            'purchase_rate[]': ['100'],
            'mrp[]': ['200'],
            'margin[]': ['20'],
            'selling_price[]': ['141.60'],
            'loading_charges': '10',
            'discount': '5',
        }
        response = self.client.post(reverse('purchase_edit', args=[original.pk]), edit_data)
        self.assertEqual(response.status_code, 302)

        # Original must be CANCELLED with renamed number
        original.refresh_from_db()
        self.assertEqual(original.status, 'CANCELLED')
        self.assertEqual(original.invoice_number, 'INV-AMEND-001-C')

        # New invoice must be ACTIVE and linked
        new_inv = PurchaseInvoice.objects.filter(amended_from=original).first()
        self.assertIsNotNone(new_inv)
        self.assertEqual(new_inv.status, 'ACTIVE')
        self.assertEqual(new_inv.invoice_number, 'INV-AMEND-001')
        self.assertEqual(new_inv.items.count(), 1)
        self.assertEqual(new_inv.items.first().quantity, 7)

        # Stock: original +10, cancel -10, amended +7 → net = 50 + 7 = 57
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.current_quantity, 57)

class Sprint5ReturnsLedgerTests(TestCase):
    """Sprint 5: Validate Returns use the process_stock_movement Ledger."""

    def setUp(self):
        self.client = Client()
        from master_data.models import Manufacturer
        self.supplier = Supplier.objects.create(name="Test Return Supplier")
        self.customer = Customer.objects.create(name="Test Return Customer")
        self.category = Category.objects.create(name="Seeds", cgst_rate=9, sgst_rate=9)
        self.manufacturer = Manufacturer.objects.create(name="Test Manufacturer")
        self.product = Product.objects.create(name="Test Return Product", category=self.category, unit_type="Kg", manufacturer=self.manufacturer)
        
        from django.db.models import F
        self.batch = Batch.objects.create(
            product=self.product,
            batch_number="RETURN_BATCH",
            current_quantity=100,
            base_selling_price=Decimal("150.00"),
            mrp=Decimal("200.00"),
            purchase_price=Decimal("100.00")
        )

    def test_sales_return_ledger_flow(self):
        """create_sales_return adds stock (+ve) via ledger, delete_sales_return deducts stock (-ve)."""
        create_data = {
            'customer': self.customer.id,
            'date': '2026-02-21',
            'batch_id[]': [str(self.batch.id)],
            'qty[]': ['10'],
            'price[]': ['150.00'],
        }
        
        # ACT: Create Sales Return (Customer brings 10 back)
        response = self.client.post(reverse('create_sales_return'), create_data)
        self.assertEqual(response.status_code, 302)
        
        # VERIFY: Stock increased
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.current_quantity, 110)
        
        # VERIFY: Ledger Entry exists
        movement = StockMovement.objects.filter(batch=self.batch, reference_document_type='SalesReturn').first()
        self.assertIsNotNone(movement)
        self.assertEqual(movement.quantity, 10)  # Inward
        
        # Find the return ID
        sales_return = SalesReturn.objects.first()
        
        # ACT: Delete Sales Return
        del_response = self.client.post(reverse('delete_sales_return', args=[sales_return.pk]))
        self.assertEqual(del_response.status_code, 302)
        
        # VERIFY: Stock reversed back to 100
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.current_quantity, 100)
        
        # VERIFY: Cancel Ledger Entry exists
        cancel_movement = StockMovement.objects.filter(batch=self.batch, reference_document_type='SalesReturnCancel').first()
        self.assertIsNotNone(cancel_movement)
        self.assertEqual(cancel_movement.quantity, -10)  # Reversed inward

    def test_purchase_return_ledger_flow(self):
        """create_purchase_return deducts stock (-ve) via ledger, delete_purchase_return restores stock (+ve)."""
        create_data = {
            'supplier': self.supplier.id,
            'date': '2026-02-21',
            'reason': 'Defective',
            'batch_id[]': [str(self.batch.id)],
            'qty[]': ['20'],
            'price[]': ['100.00'],
        }
        
        # ACT: Create Purchase Return (We send 20 back to supplier)
        response = self.client.post(reverse('create_purchase_return'), create_data)
        self.assertEqual(response.status_code, 302)
            
        # VERIFY: Stock decreased
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.current_quantity, 80)
        
        # VERIFY: Ledger Entry exists
        movement = StockMovement.objects.filter(batch=self.batch, reference_document_type='PurchaseReturn').first()
        self.assertIsNotNone(movement)
        self.assertEqual(movement.quantity, -20)  # Outward
        
        # Find the return ID
        purchase_return = PurchaseReturn.objects.first()
        
        # ACT: Delete Purchase Return
        del_response = self.client.post(reverse('delete_purchase_return', args=[purchase_return.pk]))
        self.assertEqual(del_response.status_code, 302)
        
        # VERIFY: Stock reversed back to 100
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.current_quantity, 100)
        
        # VERIFY: Cancel Ledger Entry exists
        cancel_movement = StockMovement.objects.filter(batch=self.batch, reference_document_type='PurchaseReturnCancel').first()
        self.assertIsNotNone(cancel_movement)
        self.assertEqual(cancel_movement.quantity, 20)  # Reversed outward

class Sprint6ImmutableReturnsTests(TestCase):
    """Sprint 6: Validate Returns cannot be hard-deleted and can be safely cancelled."""

    def setUp(self):
        self.client = Client()
        from master_data.models import Manufacturer
        self.supplier = Supplier.objects.create(name="Test Sprint 6 Supplier")
        self.customer = Customer.objects.create(name="Test Sprint 6 Customer")
        self.category = Category.objects.create(name="Seeds Sprint 6", cgst_rate=9, sgst_rate=9)
        self.manufacturer = Manufacturer.objects.create(name="Test Sprint 6 Manufacturer")
        self.product = Product.objects.create(name="Test Sprint 6 Product", category=self.category, unit_type="Kg", manufacturer=self.manufacturer)
        
        self.batch = Batch.objects.create(
            product=self.product,
            batch_number="RETURN_BATCH_S6",
            current_quantity=100,
            base_selling_price=Decimal("150.00"),
            mrp=Decimal("200.00"),
            purchase_price=Decimal("100.00")
        )

    def test_sales_return_immutability(self):
        """Verify SalesReturn cannot be deleted, but can be cancelled."""
        create_data = {
            'customer': self.customer.id,
            'date': '2026-02-21',
            'batch_id[]': [str(self.batch.id)],
            'qty[]': ['10'],
            'price[]': ['150.00'],
        }
        self.client.post(reverse('create_sales_return'), create_data)
        sales_return = SalesReturn.objects.first()
        
        # ACT: Try to hard-delete
        from django.core.exceptions import ValidationError
        with self.assertRaisesMessage(ValidationError, "Submitted returns cannot be hard-deleted"):
            sales_return.delete()
            
        # Verify status is active
        self.assertEqual(sales_return.status, 'ACTIVE')
            
        # ACT: Delete via view (which now uses .cancel())
        response = self.client.post(reverse('delete_sales_return', args=[sales_return.pk]))
        self.assertEqual(response.status_code, 302)
        
        # Verify still exists in DB, but CANCELLED
        sales_return.refresh_from_db()
        self.assertEqual(sales_return.status, 'CANCELLED')
        
        # Try cancelling again -> should raise ValidationError
        with self.assertRaisesMessage(ValidationError, "This return is already cancelled"):
            sales_return.cancel()

    def test_purchase_return_immutability(self):
        """Verify PurchaseReturn cannot be deleted, but can be cancelled."""
        create_data = {
            'supplier': self.supplier.id,
            'date': '2026-02-21',
            'reason': 'Defective',
            'batch_id[]': [str(self.batch.id)],
            'qty[]': ['20'],
            'price[]': ['100.00'],
        }
        self.client.post(reverse('create_purchase_return'), create_data)
        purchase_return = PurchaseReturn.objects.first()
        
        # ACT: Try to hard-delete
        from django.core.exceptions import ValidationError
        with self.assertRaisesMessage(ValidationError, "Submitted returns cannot be hard-deleted"):
            purchase_return.delete()
            
        # Verify status is active
        self.assertEqual(purchase_return.status, 'ACTIVE')
            
        # ACT: Delete via view (which now uses .cancel())
        response = self.client.post(reverse('delete_purchase_return', args=[purchase_return.pk]))
        self.assertEqual(response.status_code, 302)
        
        # Verify still exists in DB, but CANCELLED
        purchase_return.refresh_from_db()
        self.assertEqual(purchase_return.status, 'CANCELLED')
        
        # Try cancelling again
        with self.assertRaisesMessage(ValidationError, "This return is already cancelled"):
            purchase_return.cancel()
