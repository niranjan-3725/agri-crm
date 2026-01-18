from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from transactions.models import SalesInvoice, CustomerPayment
from master_data.models import Customer, Product, Category, Manufacturer
from inventory.models import Batch
from decimal import Decimal

class EditSalesPaymentTest(TestCase):
    def setUp(self):
        self.client = Client()
        
        # Setup Data
        self.customer = Customer.objects.create(name="Test Customer Edit", mobile_no="9876543210")
        self.category = Category.objects.create(name="Test Cat", cgst_rate=2.5, sgst_rate=2.5) # 5% Tax Total
        self.manufacturer = Manufacturer.objects.create(name="Test Mfg")
        self.product = Product.objects.create(name="Test Product", category=self.category, manufacturer=self.manufacturer, hsn_code="1234", unit_type="Bag")
        self.batch = Batch.objects.create(
            product=self.product,
            batch_number="B1",
            current_quantity=100,
            purchase_price=80, 
            base_selling_price=100,
            mrp=120
        )

    def test_edit_sale_full_payment_of_balance(self):
        """
        Scenario: 
        1. Create sale (Total 105, Paid 40, Balance 65).
        2. Edit sale (Add item -> Total 210).
        3. User selects "PAID" (Pay remaining 170).
        4. Verify final status is PAID, Balance 0, Total Paid 210.
        """
        # 1. Create Initial Sale (Manually to save time)
        # 1 Qty @ 105 (Inclusive).
        invoice = SalesInvoice.objects.create(
            customer=self.customer,
            date=timezone.now().date(),
            grand_total=Decimal('105.00'),
            total_taxable=100, total_cgst=2.5, total_sgst=2.5,
            amount_received=Decimal('40.00'),
            payment_status='PARTIAL'
        )
        # Initial Payment 40 - Need to create this for Signal to work properly? 
        # Actually creating SalesInvoice manually avoids signal unless we save it.
        # But we need the CustomerPayment record for the view logic 'invoice.payments'
        CustomerPayment.objects.create(invoice=invoice, amount=Decimal('40.00'))
        
        # 2. Edit Sale via POST
        url = reverse('edit_sale', args=[invoice.pk])
        
        # New State: 2 Qty @ 105 = 210 Total.
        data = {
            'customer': self.customer.id,
            'date': timezone.now().date(),
            'batch_id[]': [self.batch.id, self.batch.id], # 2 items
            'qty[]': [1, 1],
            'price[]': [105, 105], 
            'payment_status': 'PAID',
            'amount_received': '170.00' 
        }
        
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        
        # 4. Verify
        invoice.refresh_from_db()
        self.assertEqual(invoice.grand_total, Decimal('210.00')) 
        
        self.assertEqual(invoice.amount_received, Decimal('210.00')) # 40 + 170(calc)
        # Logic: New GT 210. Old Paid 40. Remainder 170.
        # View creates payment of 170. Total 210.
        
        self.assertEqual(invoice.balance_due, Decimal('0.00'))
        self.assertEqual(invoice.payment_status, 'PAID')
        
        self.assertEqual(invoice.payments.count(), 2) 

    def test_edit_sale_partial_payment(self):
        """
        Scenario:
        1. Create sale (Total 105, Paid 0).
        2. Edit sale (No item change), but add Partial Payment of 50.
        """
        invoice = SalesInvoice.objects.create(
            customer=self.customer,
            date=timezone.now().date(),
            grand_total=Decimal('105.00'),
            total_taxable=100, total_cgst=2.5, total_sgst=2.5
        )
        
        url = reverse('edit_sale', args=[invoice.pk])
        
        data = {
            'customer': self.customer.id,
            'date': timezone.now().date(),
            'batch_id[]': [self.batch.id],
            'qty[]': [1],
            'price[]': [105], # Keep it 105
            'payment_status': 'PARTIAL',
            'amount_received': '50.00' # Paying 50 now
        }
        
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        
        invoice.refresh_from_db()
        self.assertEqual(invoice.grand_total, Decimal('105.00'))
        self.assertEqual(invoice.amount_received, Decimal('50.00'))
        self.assertEqual(invoice.balance_due, Decimal('55.00'))
        self.assertEqual(invoice.payment_status, 'PARTIAL')
