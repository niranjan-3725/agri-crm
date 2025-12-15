from django.test import TestCase, Client
from django.urls import reverse
from master_data.models import Supplier, Product, Category, Manufacturer
from transactions.models import PurchaseInvoice, PurchaseItem
from inventory.models import Batch
from datetime import date
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
            'purchase_rate[]': ['120.00'], # Changed Rate
            'mrp[]': ['200'],
            'margin[]': ['30.00'], # Changed Margin
            'selling_price[]': ['156.00'],
            # Extras
            'loading_charges': '15',
            'discount': '10'
        }
        
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 302)
        
        # Verify Update
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.invoice_number, 'INV-EDIT-UPDATED')
        
        # self.item.refresh_from_db() # Removed as item is deleted and recreated
        # The view (line 299) says: item.delete(). So self.item instance is detached.
        # We must query items again.
        
        new_item = self.invoice.items.first()
        self.assertEqual(float(new_item.basic_rate), 120.00)
        self.assertEqual(float(new_item.profit_margin), 30.00)
