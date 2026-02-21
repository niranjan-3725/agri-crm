from django.test import TestCase, Client
from django.urls import reverse
from master_data.models import Supplier, Product, Category, Manufacturer, Customer
from transactions.models import PurchaseInvoice, PurchaseItem, SalesInvoice, SalesItem, SalesReturn, PurchaseReturn
from inventory.models import Batch, StockMovement, StockBin
from inventory.services import get_default_warehouse
from datetime import date
from decimal import Decimal
import json


def _seed_stockbin(batch):
    """Ensure the given batch has a StockBin in the default warehouse,
    matching its current_quantity. Call after Batch.objects.create()."""
    wh = get_default_warehouse()
    StockBin.objects.get_or_create(
        warehouse=wh, batch=batch,
        defaults={'actual_qty': batch.current_quantity},
    )


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
        self.assertEqual(invoice.loading_charges, Decimal('10.00'))
        self.assertEqual(invoice.additional_discount, Decimal('5.00'))
        
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
        _seed_stockbin(self.batch)

        self.item = PurchaseItem.objects.create(
            invoice=self.invoice,
            batch=self.batch,
            quantity=5,
            basic_rate=Decimal('100.00'),
            tax_amount=Decimal('90.00'),
            selling_price=Decimal('150.00'),
            profit_margin=Decimal('25.00'), # 25% margin
            total_amount=Decimal('590.00')
        )
        # Sprint 11: Submit the invoice so it moves from DRAFT → SUBMITTED
        self.invoice.submit()
        
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
        self.assertEqual(new_invoice.status, 'SUBMITTED')
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
        _seed_stockbin(self.batch)

    def test_sale_deduction_bug_1_fix(self):
        """Test Sale Deduction (Bug #1 Fix): Creating a sale produces DRAFT; submitting deducts stock."""
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

        # Sprint 11: Creation produces DRAFT — stock unchanged
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.current_quantity, 10)

        # Now submit and verify stock deducted
        invoice = SalesInvoice.objects.first()
        invoice.submit()
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.current_quantity, 5)

        movements = StockMovement.objects.filter(batch=self.batch)
        self.assertEqual(movements.count(), 1)
        self.assertEqual(movements.first().quantity, -5)
        self.assertEqual(movements.first().reference_document_type, 'DeliveryNote')

    def test_sale_return_addition(self):
        """Test Sale Return Addition: Return creates DRAFT; submitting adds stock."""
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

        # Sprint 11: DRAFT — stock unchanged
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.current_quantity, 10)

        # Submit the return
        sr = SalesReturn.objects.first()
        sr.submit()
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.current_quantity, 12)  # 10 + 2
        
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
        """Test Invoice Deletion Restoration: Submitting+deleting restores stock via cancel."""
        data = {
            'customer': self.customer.id,
            'date': date.today().strftime('%Y-%m-%d'),
            'batch_id[]': [self.batch.id],
            'qty[]': ['5'],
            'price[]': ['150.00'],
            'payment_status': 'UNPAID',
        }
        self.client.post(reverse('create_sale'), data)

        invoice = SalesInvoice.objects.first()
        invoice.submit()  # Sprint 11: Must submit first
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.current_quantity, 5)

        response = self.client.post(reverse('delete_invoice', args=[invoice.id]))
        self.assertEqual(response.status_code, 302)

        self.batch.refresh_from_db()
        self.assertEqual(self.batch.current_quantity, 10)

        movements = StockMovement.objects.filter(batch=self.batch).order_by('created_at')
        self.assertEqual(movements.count(), 2)
        self.assertEqual(movements[0].reference_document_type, 'DeliveryNote')
        self.assertEqual(movements[0].quantity, -5)
        self.assertEqual(movements[1].reference_document_type, 'DeliveryNoteCancel')
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
        """Gap 4 fix: create_purchase saves DRAFT; submitting creates ledger entry."""
        data = self._purchase_data()
        response = self.client.post(reverse('create_purchase'), data)
        self.assertEqual(response.status_code, 302)

        invoice = PurchaseInvoice.objects.first()
        self.assertIsNotNone(invoice)

        # Sprint 11: DRAFT — stock unchanged
        batch = Batch.objects.get(batch_number='BINWARD')
        self.assertEqual(batch.current_quantity, 0)

        # Submit and verify
        invoice.submit()
        batch.refresh_from_db()
        self.assertEqual(batch.current_quantity, 10)

        movements = StockMovement.objects.filter(batch=batch)
        self.assertEqual(movements.count(), 1)
        self.assertEqual(movements.first().quantity, 10)
        self.assertEqual(movements.first().reference_document_type, 'PurchaseReceipt')
        # Sprint 13: reference_document_id is on the PurchaseReceipt, not the invoice
        self.assertEqual(movements.first().reference_document_id, invoice.purchase_receipt.id)

    def test_purchase_delete_creates_negative_ledger_and_reverses_stock(self):
        """Gap 3 fix: purchase cancel creates a - StockMovement and deducts stock."""
        data = self._purchase_data(inv_num='INV-DEL-001')
        self.client.post(reverse('create_purchase'), data)

        batch = Batch.objects.get(batch_number='BINWARD')
        invoice = PurchaseInvoice.objects.first()
        invoice.submit()  # Sprint 11: Must submit first
        batch.refresh_from_db()
        self.assertEqual(batch.current_quantity, 10)

        response = self.client.post(reverse('purchase_delete', args=[invoice.id]))
        self.assertEqual(response.status_code, 302)

        batch.refresh_from_db()
        self.assertEqual(batch.current_quantity, 0)

        movements = StockMovement.objects.filter(batch=batch).order_by('created_at')
        self.assertEqual(movements.count(), 2)
        self.assertEqual(movements[0].quantity, 10)
        self.assertEqual(movements[0].reference_document_type, 'PurchaseReceipt')
        self.assertEqual(movements[1].quantity, -10)
        self.assertEqual(movements[1].reference_document_type, 'PurchaseReceiptCancel')

        invoice.refresh_from_db()
        self.assertEqual(invoice.status, 'CANCELLED')
        self.assertEqual(PurchaseInvoice.objects.count(), 1)


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
        _seed_stockbin(self.batch)

    def test_two_items_same_batch_deducts_correctly(self):
        """Sprint 11: DRAFT creation has no stock impact; submit deducts correctly."""
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

        invoice = SalesInvoice.objects.first()
        invoice.submit()

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
        _seed_stockbin(self.batch)

    def _create_sales_invoice(self):
        """Helper: create and submit a valid SalesInvoice with one item."""
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
        invoice.submit()  # Sprint 11: DRAFT → SUBMITTED
        return invoice

    def _create_purchase_invoice(self):
        """Helper: create and submit a valid PurchaseInvoice with one item."""
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
        invoice.submit()  # Sprint 11: DRAFT → SUBMITTED
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

        # Sprint 13: Cancel goes through DeliveryNote, not SalesInvoice
        cancel_movements = StockMovement.objects.filter(
            batch=self.batch,
            reference_document_type='DeliveryNoteCancel',
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

        # Sprint 13: Cancel goes through PurchaseReceipt, not PurchaseInvoice
        cancel_movements = StockMovement.objects.filter(
            batch=self.batch,
            reference_document_type='PurchaseReceiptCancel',
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
        # Before cancel: should appear (SUBMITTED)
        response = self.client.get(reverse('sales_list'))
        found_ids = [i.pk for i in response.context['invoices'].object_list]
        self.assertIn(invoice.pk, found_ids)

        invoice.cancel()

        # After cancel: should NOT appear
        response = self.client.get(reverse('sales_list'))
        found_ids = [i.pk for i in response.context['invoices'].object_list]
        self.assertNotIn(invoice.pk, found_ids)


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
        _seed_stockbin(self.batch)

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
        """Editing a SUBMITTED sale must cancel the old and create a new SUBMITTED invoice."""
        # First create a sale via the view (produces DRAFT)
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
        self.assertEqual(original.status, 'DRAFT')

        # Sprint 11: Submit so that edit triggers cancel+amend
        original.submit()
        self.assertEqual(original.status, 'SUBMITTED')

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

        # New invoice must be SUBMITTED and linked
        new_inv = SalesInvoice.objects.filter(amended_from=original).first()
        self.assertIsNotNone(new_inv)
        self.assertEqual(new_inv.status, 'SUBMITTED')
        self.assertEqual(new_inv.items.count(), 1)
        self.assertEqual(new_inv.items.first().quantity, 3)

        # Stock: original sold 5, cancel restored 5, new sold 3 → net = 50 - 3 = 47
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.current_quantity, 47)

        # Ledger: 3 entries total
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
        """Editing a SUBMITTED purchase must cancel the old and create a new SUBMITTED invoice."""
        # Create a purchase via the view (produces DRAFT)
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

        # Sprint 11: Submit so that edit triggers cancel+amend
        original.submit()

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

        # New invoice must be SUBMITTED and linked
        new_inv = PurchaseInvoice.objects.filter(amended_from=original).first()
        self.assertIsNotNone(new_inv)
        self.assertEqual(new_inv.status, 'SUBMITTED')
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
        _seed_stockbin(self.batch)

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
        
        # Sprint 11: Submit the DRAFT return
        sales_return = SalesReturn.objects.first()
        sales_return.submit()
        
        # VERIFY: Stock increased
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.current_quantity, 110)
        
        # VERIFY: Ledger Entry exists
        movement = StockMovement.objects.filter(batch=self.batch, reference_document_type='SalesReturn').first()
        self.assertIsNotNone(movement)
        self.assertEqual(movement.quantity, 10)  # Inward
        
        # ACT: Delete Sales Return (cancel)
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

        # Sprint 11: Submit the DRAFT return
        purchase_return = PurchaseReturn.objects.first()
        purchase_return.submit()
            
        # VERIFY: Stock decreased
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.current_quantity, 80)
        
        # VERIFY: Ledger Entry exists
        movement = StockMovement.objects.filter(batch=self.batch, reference_document_type='PurchaseReturn').first()
        self.assertIsNotNone(movement)
        self.assertEqual(movement.quantity, -20)  # Outward
        
        # ACT: Delete Purchase Return (cancel)
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
        _seed_stockbin(self.batch)

    def test_sales_return_immutability(self):
        """Verify SalesReturn cannot be deleted when SUBMITTED, but can be cancelled."""
        create_data = {
            'customer': self.customer.id,
            'date': '2026-02-21',
            'batch_id[]': [str(self.batch.id)],
            'qty[]': ['10'],
            'price[]': ['150.00'],
        }
        self.client.post(reverse('create_sales_return'), create_data)
        sales_return = SalesReturn.objects.first()
        
        # Sprint 11: Submit the return first
        sales_return.submit()
        
        # ACT: Try to hard-delete
        from django.core.exceptions import ValidationError
        with self.assertRaisesMessage(ValidationError, "Submitted returns cannot be deleted"):
            sales_return.delete()
            
        self.assertEqual(sales_return.status, 'SUBMITTED')
            
        # ACT: Delete via view (which now uses .cancel())
        response = self.client.post(reverse('delete_sales_return', args=[sales_return.pk]))
        self.assertEqual(response.status_code, 302)
        
        # Verify still exists in DB, but CANCELLED
        sales_return.refresh_from_db()
        self.assertEqual(sales_return.status, 'CANCELLED')
        
        # Try cancelling again -> should raise ValidationError
        with self.assertRaisesMessage(ValidationError, "Only submitted documents can be cancelled"):
            sales_return.cancel()

    def test_purchase_return_immutability(self):
        """Verify PurchaseReturn cannot be deleted when SUBMITTED, but can be cancelled."""
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
        
        # Sprint 11: Submit the return first
        purchase_return.submit()
        
        # ACT: Try to hard-delete
        from django.core.exceptions import ValidationError
        with self.assertRaisesMessage(ValidationError, "Submitted returns cannot be deleted"):
            purchase_return.delete()
            
        self.assertEqual(purchase_return.status, 'SUBMITTED')
            
        # ACT: Delete via view (which now uses .cancel())
        response = self.client.post(reverse('delete_purchase_return', args=[purchase_return.pk]))
        self.assertEqual(response.status_code, 302)
        
        # Verify still exists in DB, but CANCELLED
        purchase_return.refresh_from_db()
        self.assertEqual(purchase_return.status, 'CANCELLED')
        
        # Try cancelling again
        with self.assertRaisesMessage(ValidationError, "Only submitted documents can be cancelled"):
            purchase_return.cancel()


class Sprint7StockReconciliationTests(TestCase):
    """Sprint 7: Validate StockReconciliation model and reconcile_stock() service."""

    def setUp(self):
        from master_data.models import Manufacturer
        self.category = Category.objects.create(name="Recon Seeds", cgst_rate=9, sgst_rate=9)
        self.manufacturer = Manufacturer.objects.create(name="Recon Manufacturer")
        self.product = Product.objects.create(
            name="Recon Product",
            category=self.category,
            unit_type="Kg",
            manufacturer=self.manufacturer,
        )
        self.batch = Batch.objects.create(
            product=self.product,
            batch_number="RECON_BATCH_001",
            current_quantity=10,
            base_selling_price=Decimal("150.00"),
            mrp=Decimal("200.00"),
            purchase_price=Decimal("100.00"),
        )
        _seed_stockbin(self.batch)

    def test_reconcile_stock_up(self):
        """Reconciling 10 → 12 creates a +2 ledger entry."""
        from inventory.services import reconcile_stock
        from inventory.models import StockReconciliation

        recon = reconcile_stock(batch_id=self.batch.id, new_quantity=12, reason='Count Error')

        # Reconciliation record
        self.assertEqual(recon.previous_quantity, 10)
        self.assertEqual(recon.new_quantity, 12)
        self.assertEqual(recon.delta, 2)

        # Batch cache updated
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.current_quantity, 12)

        # Ledger entry created with correct sign
        movement = StockMovement.objects.filter(
            batch=self.batch,
            reference_document_type='StockReconciliation',
        ).first()
        self.assertIsNotNone(movement)
        self.assertEqual(movement.quantity, 2)

    def test_reconcile_stock_down(self):
        """Reconciling 10 → 8 creates a -2 ledger entry."""
        from inventory.services import reconcile_stock

        recon = reconcile_stock(batch_id=self.batch.id, new_quantity=8, reason='Damage')

        self.assertEqual(recon.delta, -2)

        self.batch.refresh_from_db()
        self.assertEqual(self.batch.current_quantity, 8)

        movement = StockMovement.objects.filter(
            batch=self.batch,
            reference_document_type='StockReconciliation',
        ).first()
        self.assertIsNotNone(movement)
        self.assertEqual(movement.quantity, -2)

    def test_reconcile_stock_no_change(self):
        """Reconciling 10 → 10 saves the audit record but creates NO ledger entry."""
        from inventory.services import reconcile_stock

        recon = reconcile_stock(batch_id=self.batch.id, new_quantity=10, reason='Count Error')

        self.assertEqual(recon.delta, 0)

        # Batch unchanged
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.current_quantity, 10)

        # No ledger entry for zero delta
        movement_count = StockMovement.objects.filter(
            batch=self.batch,
            reference_document_type='StockReconciliation',
        ).count()
        self.assertEqual(movement_count, 0)

        # But the reconciliation audit record WAS created
        from inventory.models import StockReconciliation
        self.assertEqual(StockReconciliation.objects.count(), 1)

    def test_reconcile_negative_quantity_raises(self):
        """Passing a negative new_quantity raises ValueError immediately."""
        from inventory.services import reconcile_stock

        with self.assertRaises(ValueError):
            reconcile_stock(batch_id=self.batch.id, new_quantity=-5, reason='Other')

        # Batch untouched
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.current_quantity, 10)


class Sprint8MultiWarehouseTests(TestCase):
    """Sprint 8: Validate multi-warehouse architecture (Warehouse, StockBin, updated ledger)."""

    def setUp(self):
        from master_data.models import Manufacturer
        from inventory.models import Warehouse, StockBin
        from inventory.services import get_default_warehouse

        self.category = Category.objects.create(name="WH Seeds", cgst_rate=9, sgst_rate=9)
        self.manufacturer = Manufacturer.objects.create(name="WH Manufacturer")
        self.product = Product.objects.create(
            name="WH Product",
            category=self.category,
            unit_type="Kg",
            manufacturer=self.manufacturer,
        )
        self.batch = Batch.objects.create(
            product=self.product,
            batch_number="WH_BATCH_001",
            current_quantity=0,
            base_selling_price=Decimal("150.00"),
            mrp=Decimal("200.00"),
            purchase_price=Decimal("100.00"),
        )
        # Create two warehouses
        self.wh_main = get_default_warehouse()
        self.wh_secondary = Warehouse.objects.create(
            name="Secondary Warehouse", location="Back store", is_active=True
        )

    def test_inward_creates_stockbin_and_updates_it(self):
        """Stock inward to a specific warehouse creates/updates the correct StockBin."""
        from inventory.services import process_stock_movement
        from inventory.models import StockBin

        movement = process_stock_movement(
            batch_id=self.batch.id,
            quantity=25,
            doc_type='PurchaseInvoice',
            doc_id=1,
            warehouse_id=self.wh_main.id,
        )

        # StockBin should exist with correct qty
        stock_bin = StockBin.objects.get(warehouse=self.wh_main, batch=self.batch)
        self.assertEqual(stock_bin.actual_qty, 25)

        # Batch global cache also updated
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.current_quantity, 25)

    def test_outward_deducts_from_correct_stockbin(self):
        """Stock outward from a warehouse deducts from the correct StockBin."""
        from inventory.services import process_stock_movement
        from inventory.models import StockBin

        # Seed stock
        process_stock_movement(self.batch.id, 50, 'PurchaseInvoice', 1, self.wh_main.id)

        # Sell 15
        process_stock_movement(self.batch.id, -15, 'SalesInvoice', 2, self.wh_main.id)

        stock_bin = StockBin.objects.get(warehouse=self.wh_main, batch=self.batch)
        self.assertEqual(stock_bin.actual_qty, 35)

        self.batch.refresh_from_db()
        self.assertEqual(self.batch.current_quantity, 35)

    def test_stockmovement_records_warehouse(self):
        """StockMovement ledger entry records the warehouse FK."""
        from inventory.services import process_stock_movement

        movement = process_stock_movement(
            self.batch.id, 10, 'PurchaseInvoice', 1, self.wh_secondary.id
        )

        self.assertEqual(movement.warehouse_id, self.wh_secondary.id)

    def test_two_warehouses_independent_quantities(self):
        """The same batch in two warehouses maintains independent stock levels."""
        from inventory.services import process_stock_movement
        from inventory.models import StockBin

        process_stock_movement(self.batch.id, 30, 'PurchaseInvoice', 1, self.wh_main.id)
        process_stock_movement(self.batch.id, 20, 'PurchaseInvoice', 2, self.wh_secondary.id)

        bin_main = StockBin.objects.get(warehouse=self.wh_main, batch=self.batch)
        bin_sec = StockBin.objects.get(warehouse=self.wh_secondary, batch=self.batch)

        self.assertEqual(bin_main.actual_qty, 30)
        self.assertEqual(bin_sec.actual_qty, 20)

        # Global cache is sum of both
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.current_quantity, 50)

    def test_overdraft_specific_warehouse_raises(self):
        """Over-drafting a specific warehouse StockBin triggers InsufficientStockError."""
        from inventory.services import process_stock_movement, InsufficientStockError

        # Put 5 in main, 20 in secondary
        process_stock_movement(self.batch.id, 5, 'PurchaseInvoice', 1, self.wh_main.id)
        process_stock_movement(self.batch.id, 20, 'PurchaseInvoice', 2, self.wh_secondary.id)

        # Try to take 10 from main (only has 5) — should fail
        with self.assertRaises(InsufficientStockError):
            process_stock_movement(self.batch.id, -10, 'SalesInvoice', 3, self.wh_main.id)

        # Main bin untouched
        from inventory.models import StockBin
        bin_main = StockBin.objects.get(warehouse=self.wh_main, batch=self.batch)
        self.assertEqual(bin_main.actual_qty, 5)

    def test_default_warehouse_fallback(self):
        """Calling process_stock_movement without warehouse_id uses the default warehouse."""
        from inventory.services import process_stock_movement
        from inventory.models import StockBin

        movement = process_stock_movement(
            batch_id=self.batch.id,
            quantity=15,
            doc_type='PurchaseInvoice',
            doc_id=99,
            # warehouse_id NOT passed — should default to Main Warehouse
        )

        self.assertEqual(movement.warehouse_id, self.wh_main.id)
        stock_bin = StockBin.objects.get(warehouse=self.wh_main, batch=self.batch)
        self.assertEqual(stock_bin.actual_qty, 15)


class Sprint10MovingAverageTests(TestCase):
    """Sprint 10: Validate Moving Average valuation engine."""

    def setUp(self):
        from master_data.models import Manufacturer
        from inventory.models import Warehouse, StockBin
        from inventory.services import get_default_warehouse

        self.category = Category.objects.create(name="MA Seeds", cgst_rate=9, sgst_rate=9)
        self.manufacturer = Manufacturer.objects.create(name="MA Manufacturer")
        self.product = Product.objects.create(
            name="MA Product",
            category=self.category,
            unit_type="Kg",
            manufacturer=self.manufacturer,
        )
        # Batch 1 — purchase price ₹100
        self.batch1 = Batch.objects.create(
            product=self.product,
            batch_number="MA_BATCH_001",
            current_quantity=0,
            base_selling_price=Decimal("150.00"),
            mrp=Decimal("200.00"),
            purchase_price=Decimal("100.00"),
        )
        # Batch 2 — purchase price ₹150
        self.batch2 = Batch.objects.create(
            product=self.product,
            batch_number="MA_BATCH_002",
            current_quantity=0,
            base_selling_price=Decimal("180.00"),
            mrp=Decimal("220.00"),
            purchase_price=Decimal("150.00"),
        )
        self.wh = get_default_warehouse()
        StockBin.objects.get_or_create(
            warehouse=self.wh, batch=self.batch1, defaults={'actual_qty': 0}
        )
        StockBin.objects.get_or_create(
            warehouse=self.wh, batch=self.batch2, defaults={'actual_qty': 0}
        )

    def test_first_purchase_sets_average_to_purchase_price(self):
        """Buy 10 @ ₹100 → moving average should be ₹100."""
        from inventory.services import process_stock_movement

        process_stock_movement(self.batch1.id, 10, 'PurchaseInvoice', 1, self.wh.id)

        self.product.refresh_from_db()
        self.assertEqual(self.product.moving_average_price, Decimal('100.0000'))

    def test_second_purchase_recalculates_weighted_average(self):
        """Buy 10 @ ₹100, then buy 10 @ ₹150 → average should be ₹125."""
        from inventory.services import process_stock_movement

        process_stock_movement(self.batch1.id, 10, 'PurchaseInvoice', 1, self.wh.id)
        process_stock_movement(self.batch2.id, 10, 'PurchaseInvoice', 2, self.wh.id)

        self.product.refresh_from_db()
        self.assertEqual(self.product.moving_average_price, Decimal('125.0000'))

    def test_sale_does_not_change_moving_average(self):
        """Selling 5 units should consume at MA price but NOT change the average."""
        from inventory.services import process_stock_movement

        process_stock_movement(self.batch1.id, 10, 'PurchaseInvoice', 1, self.wh.id)
        process_stock_movement(self.batch2.id, 10, 'PurchaseInvoice', 2, self.wh.id)
        # MA is now 125

        process_stock_movement(self.batch1.id, -5, 'SalesInvoice', 3, self.wh.id)

        self.product.refresh_from_db()
        self.assertEqual(self.product.moving_average_price, Decimal('125.0000'))

    def test_sale_valuation_rate_is_moving_average(self):
        """The outward StockMovement should snapshot valuation_rate = current MA."""
        from inventory.services import process_stock_movement
        from inventory.models import StockMovement

        process_stock_movement(self.batch1.id, 10, 'PurchaseInvoice', 1, self.wh.id)
        process_stock_movement(self.batch2.id, 10, 'PurchaseInvoice', 2, self.wh.id)
        # MA = 125

        process_stock_movement(self.batch1.id, -5, 'SalesInvoice', 3, self.wh.id)

        sale_movement = StockMovement.objects.get(
            reference_document_type='SalesInvoice', reference_document_id=3
        )
        self.assertEqual(sale_movement.valuation_rate, Decimal('125.0000'))

    def test_purchase_valuation_rate_is_batch_price(self):
        """The inward StockMovement should snapshot valuation_rate = batch purchase price."""
        from inventory.services import process_stock_movement
        from inventory.models import StockMovement

        process_stock_movement(self.batch1.id, 10, 'PurchaseInvoice', 1, self.wh.id)

        purchase_movement = StockMovement.objects.get(
            reference_document_type='PurchaseInvoice', reference_document_id=1
        )
        self.assertEqual(purchase_movement.valuation_rate, Decimal('100.0000'))

    def test_sale_gl_uses_moving_average_for_cogs(self):
        """COGS GL entry should use the moving average, not the batch price."""
        from inventory.services import process_stock_movement
        from accounting.models import GLEntry

        process_stock_movement(self.batch1.id, 10, 'PurchaseInvoice', 1, self.wh.id)
        process_stock_movement(self.batch2.id, 10, 'PurchaseInvoice', 2, self.wh.id)
        # MA = 125

        process_stock_movement(self.batch1.id, -5, 'SalesInvoice', 3, self.wh.id)

        cogs_entry = GLEntry.objects.get(
            reference_type='SalesInvoice', reference_id=3, debit__gt=0
        )
        self.assertEqual(cogs_entry.account.name, 'Cost of Goods Sold')
        # COGS = 5 units × ₹125 MA = ₹625
        self.assertEqual(cogs_entry.debit, Decimal('625.00'))

    def test_asymmetric_purchase_average(self):
        """Buy 5 @ ₹200, then buy 15 @ ₹100 → average should be ₹125."""
        from inventory.services import process_stock_movement

        self.batch1.purchase_price = Decimal('200.00')
        self.batch1.save()
        self.batch2.purchase_price = Decimal('100.00')
        self.batch2.save()

        process_stock_movement(self.batch1.id, 5, 'PurchaseInvoice', 1, self.wh.id)
        process_stock_movement(self.batch2.id, 15, 'PurchaseInvoice', 2, self.wh.id)

        self.product.refresh_from_db()
        # (5*200 + 15*100) / 20 = (1000 + 1500) / 20 = 125
        self.assertEqual(self.product.moving_average_price, Decimal('125.0000'))


class Sprint11DocumentStateMachineTests(TestCase):
    """Sprint 11: Validate Draft → Submit → Cancel state machine."""

    def setUp(self):
        from master_data.models import Manufacturer
        from inventory.models import Warehouse, StockBin
        from inventory.services import get_default_warehouse

        self.category = Category.objects.create(name="S11 Cat", cgst_rate=9, sgst_rate=9)
        self.manufacturer = Manufacturer.objects.create(name="S11 Mfr")
        self.product = Product.objects.create(
            name="S11 Product", category=self.category,
            unit_type="Kg", manufacturer=self.manufacturer,
        )
        self.supplier = Supplier.objects.create(
            name="S11 Supplier", phone="1234", gstin="22AAAA", address="Test",
        )
        self.customer = Customer.objects.create(
            name="S11 Customer", mobile_no="9999", address="Test",
        )
        # Create a batch with initial stock for outward tests
        self.batch = Batch.objects.create(
            product=self.product, batch_number="S11_B001",
            current_quantity=100, base_selling_price=Decimal("200.00"),
            mrp=Decimal("250.00"), purchase_price=Decimal("100.00"),
        )
        self.wh = get_default_warehouse()
        StockBin.objects.get_or_create(
            warehouse=self.wh, batch=self.batch, defaults={'actual_qty': 100}
        )

    # ─── Purchase Invoice Tests ───

    def test_purchase_draft_creates_zero_ledger_entries(self):
        """Creating a PurchaseInvoice in DRAFT should produce 0 StockMovements."""
        invoice = PurchaseInvoice.objects.create(
            supplier=self.supplier, invoice_number="PI-S11-001",
            date="2026-02-21", total_amount=Decimal("1000.00"),
        )
        PurchaseItem.objects.create(
            invoice=invoice, batch=self.batch, quantity=10,
            basic_rate=Decimal("100.00"), tax_amount=Decimal("0.00"),
            total_amount=Decimal("1000.00"),
        )
        self.assertEqual(invoice.status, 'DRAFT')
        self.assertEqual(
            StockMovement.objects.filter(
                reference_document_type='PurchaseInvoice',
                reference_document_id=invoice.id
            ).count(), 0
        )

    def test_purchase_submit_creates_stock_and_gl_entries(self):
        """Submitting a DRAFT PurchaseInvoice should create ledger entries."""
        from accounting.models import GLEntry

        invoice = PurchaseInvoice.objects.create(
            supplier=self.supplier, invoice_number="PI-S11-002",
            date="2026-02-21", total_amount=Decimal("1000.00"),
        )
        PurchaseItem.objects.create(
            invoice=invoice, batch=self.batch, quantity=10,
            basic_rate=Decimal("100.00"), tax_amount=Decimal("0.00"),
            total_amount=Decimal("1000.00"),
        )
        invoice.submit()

        self.assertEqual(invoice.status, 'SUBMITTED')
        # Sprint 13: Stock movement via auto-created PurchaseReceipt
        invoice.refresh_from_db()
        self.assertIsNotNone(invoice.purchase_receipt)
        self.assertEqual(
            StockMovement.objects.filter(
                reference_document_type='PurchaseReceipt',
                reference_document_id=invoice.purchase_receipt.id
            ).count(), 1
        )
        # GL: 2 stock GL on PurchaseReceipt + 2 AP GL on PurchaseInvoice
        self.assertGreaterEqual(
            GLEntry.objects.filter(
                reference_type='PurchaseInvoice',
                reference_id=invoice.id
            ).count(), 2
        )

    def test_submit_already_submitted_raises_error(self):
        """Attempting to submit a SUBMITTED doc should raise ValidationError."""
        from django.core.exceptions import ValidationError

        invoice = PurchaseInvoice.objects.create(
            supplier=self.supplier, invoice_number="PI-S11-003",
            date="2026-02-21", total_amount=Decimal("1000.00"),
        )
        PurchaseItem.objects.create(
            invoice=invoice, batch=self.batch, quantity=5,
            basic_rate=Decimal("100.00"), tax_amount=Decimal("0.00"),
            total_amount=Decimal("500.00"),
        )
        invoice.submit()

        with self.assertRaises(ValidationError):
            invoice.submit()

    # ─── Sales Invoice Tests ───

    def test_sales_draft_creates_zero_ledger_entries(self):
        """Creating a SalesInvoice in DRAFT should produce 0 StockMovements."""
        invoice = SalesInvoice.objects.create(
            customer=self.customer, date="2026-02-21",
            total_taxable=Decimal("900.00"), total_cgst=Decimal("50.00"),
            total_sgst=Decimal("50.00"), grand_total=Decimal("1000.00"),
        )
        SalesItem.objects.create(
            invoice=invoice, batch=self.batch, quantity=5,
            unit_price=Decimal("200.00"), tax_rate=Decimal("18.00"),
            tax_amount=Decimal("0.00"), total_amount=Decimal("1000.00"),
        )
        self.assertEqual(invoice.status, 'DRAFT')
        self.assertEqual(
            StockMovement.objects.filter(
                reference_document_type='SalesInvoice',
                reference_document_id=invoice.id
            ).count(), 0
        )

    def test_sales_submit_deducts_stock(self):
        """Submitting a SalesInvoice should deduct stock via StockMovement."""
        invoice = SalesInvoice.objects.create(
            customer=self.customer, date="2026-02-21",
            total_taxable=Decimal("900.00"), total_cgst=Decimal("50.00"),
            total_sgst=Decimal("50.00"), grand_total=Decimal("1000.00"),
        )
        SalesItem.objects.create(
            invoice=invoice, batch=self.batch, quantity=5,
            unit_price=Decimal("200.00"), tax_rate=Decimal("18.00"),
            tax_amount=Decimal("0.00"), total_amount=Decimal("1000.00"),
        )
        invoice.submit()

        self.assertEqual(invoice.status, 'SUBMITTED')
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.current_quantity, 95)  # 100 - 5

    def test_editing_draft_creates_zero_entries(self):
        """Modifying items on a DRAFT invoice should never hit ledgers."""
        invoice = SalesInvoice.objects.create(
            customer=self.customer, date="2026-02-21",
            total_taxable=0, total_cgst=0, total_sgst=0, grand_total=0,
        )
        item = SalesItem.objects.create(
            invoice=invoice, batch=self.batch, quantity=3,
            unit_price=Decimal("200.00"), tax_rate=Decimal("18.00"),
            tax_amount=Decimal("0.00"), total_amount=Decimal("600.00"),
        )
        # Edit: delete old item, create new with different qty
        item.delete()
        SalesItem.objects.create(
            invoice=invoice, batch=self.batch, quantity=7,
            unit_price=Decimal("200.00"), tax_rate=Decimal("18.00"),
            tax_amount=Decimal("0.00"), total_amount=Decimal("1400.00"),
        )
        self.assertEqual(
            StockMovement.objects.filter(
                reference_document_type='SalesInvoice',
                reference_document_id=invoice.id
            ).count(), 0
        )

    # ─── Cancel Tests ───

    def test_cancel_submitted_reverses_stock(self):
        """Cancelling a SUBMITTED sales invoice should restore stock."""
        invoice = SalesInvoice.objects.create(
            customer=self.customer, date="2026-02-21",
            total_taxable=0, total_cgst=0, total_sgst=0, grand_total=0,
        )
        SalesItem.objects.create(
            invoice=invoice, batch=self.batch, quantity=10,
            unit_price=Decimal("200.00"), tax_rate=Decimal("18.00"),
            tax_amount=Decimal("0.00"), total_amount=Decimal("2000.00"),
        )
        invoice.submit()
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.current_quantity, 90)  # 100 - 10

        invoice.cancel()
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.current_quantity, 100)  # restored
        self.assertEqual(invoice.status, 'CANCELLED')

    def test_cancel_draft_raises_error(self):
        """Cannot cancel a DRAFT — must submit first."""
        from django.core.exceptions import ValidationError

        invoice = SalesInvoice.objects.create(
            customer=self.customer, date="2026-02-21",
            total_taxable=0, total_cgst=0, total_sgst=0, grand_total=0,
        )
        with self.assertRaises(ValidationError):
            invoice.cancel()

    # ─── Draft Deletion Tests ───

    def test_draft_can_be_deleted(self):
        """DRAFT documents CAN be hard-deleted."""
        invoice = PurchaseInvoice.objects.create(
            supplier=self.supplier, invoice_number="PI-S11-DEL",
            date="2026-02-21", total_amount=Decimal("500.00"),
        )
        pk = invoice.pk
        invoice.delete()  # Should NOT raise
        self.assertFalse(PurchaseInvoice.objects.filter(pk=pk).exists())

    def test_submitted_cannot_be_deleted(self):
        """SUBMITTED documents cannot be hard-deleted."""
        from django.core.exceptions import ValidationError

        invoice = PurchaseInvoice.objects.create(
            supplier=self.supplier, invoice_number="PI-S11-NDEL",
            date="2026-02-21", total_amount=Decimal("500.00"),
        )
        PurchaseItem.objects.create(
            invoice=invoice, batch=self.batch, quantity=5,
            basic_rate=Decimal("100.00"), tax_amount=Decimal("0.00"),
            total_amount=Decimal("500.00"),
        )
        invoice.submit()

        with self.assertRaises(ValidationError):
            invoice.delete()

