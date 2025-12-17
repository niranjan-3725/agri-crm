from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from transactions.models import SalesInvoice, CustomerPayment, SalesItem
from master_data.models import Customer, Product, Category
from inventory.models import Batch
from decimal import Decimal

class SalesPaymentTest(TestCase):
    def setUp(self):
        self.client = Client()
        
        # Setup Data
        self.customer = Customer.objects.create(name="Test Customer", mobile_no="1234567890")
        self.category = Category.objects.create(name="Test Cat", cgst_rate=2.5, sgst_rate=2.5) # 5% Tax Total
        from master_data.models import Manufacturer
        self.manufacturer = Manufacturer.objects.create(name="Test Mfg")
        self.product = Product.objects.create(name="Test Product", category=self.category, manufacturer=self.manufacturer, hsn_code="1234", unit_type="Bag")
        self.batch = Batch.objects.create(
            product=self.product,
            batch_number="B1",
            current_quantity=100,
            purchase_price=80, # Added required field
            base_selling_price=100, # Base Price
            mrp=120
        )
        
    def test_create_sale_paid_triggers_payment_and_signal(self):
        """
        Test that submitting a sale with status 'PAID' creates a CustomerPayment
        and the signal updates the SalesInvoice to 'PAID'.
        """
        url = reverse('create_sale')
        
        # 1 Qty @ 100. Tax = 5%. Total = 105.
        data = {
            'customer': self.customer.id,
            'date': timezone.now().date(),
            'batch_id[]': [self.batch.id],
            'qty[]': [1],
            'price[]': [100], 
            'payment_status': 'PAID',
            'amount_received': '' # Should be ignored for PAID
        }
        
        response = self.client.post(url, data)
        
        # Check Redirect
        self.assertEqual(response.status_code, 302)
        
        # Check Invoice
        invoice = SalesInvoice.objects.last()
        self.assertIsNotNone(invoice)
        self.assertEqual(invoice.grand_total, Decimal('105.00'))
        
        # Check Payment
        payment = CustomerPayment.objects.filter(invoice=invoice).first()
        self.assertIsNotNone(payment, "CustomerPayment should be created")
        self.assertEqual(payment.amount, Decimal('105.00'))
        
        # Check Signal Effect
        invoice.refresh_from_db()
        self.assertEqual(invoice.amount_received, Decimal('105.00'))
        self.assertEqual(invoice.balance_due, Decimal('0.00'))
        self.assertEqual(invoice.payment_status, 'PAID')

    def test_create_sale_partial(self):
        """
        Test PARTIAL payment.
        """
        url = reverse('create_sale')
        
        # 1 Qty @ 100. Total 105. Pay 50.
        data = {
            'customer': self.customer.id,
            'date': timezone.now().date(),
            'batch_id[]': [self.batch.id],
            'qty[]': [1],
            'price[]': [100], 
            'payment_status': 'PARTIAL',
            'amount_received': '50.00'
        }
        
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        
        invoice = SalesInvoice.objects.last()
        
        # Check Payment
        payment = CustomerPayment.objects.filter(invoice=invoice).first()
        self.assertIsNotNone(payment)
        self.assertEqual(payment.amount, Decimal('50.00'))
        
        # Check Signal
        invoice.refresh_from_db()
        self.assertEqual(invoice.amount_received, Decimal('50.00'))
        self.assertEqual(invoice.balance_due, Decimal('55.00')) # 105 - 50 = 55
        self.assertEqual(invoice.payment_status, 'PARTIAL')

    def test_create_sale_unpaid(self):
        """
        Test UNPAID sale creates no payment.
        """
        url = reverse('create_sale')
        
        data = {
            'customer': self.customer.id,
            'date': timezone.now().date(),
            'batch_id[]': [self.batch.id],
            'qty[]': [1],
            'price[]': [100], 
            'payment_status': 'UNPAID'
        }
        
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        
        invoice = SalesInvoice.objects.last()
        
        # Check No Payment
        payment_exists = CustomerPayment.objects.filter(invoice=invoice).exists()
        self.assertFalse(payment_exists)
        
        # Check Status
        invoice.refresh_from_db()
        self.assertEqual(invoice.amount_received, Decimal('0.00'))
        self.assertEqual(invoice.payment_status, 'UNPAID')
