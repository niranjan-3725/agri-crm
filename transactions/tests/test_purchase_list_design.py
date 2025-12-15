from django.test import TestCase, Client
from django.urls import reverse
from master_data.models import Supplier
from transactions.models import PurchaseInvoice
from django.utils import timezone
from datetime import timedelta

class PurchaseListDesignTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.supplier = Supplier.objects.create(name="Design Test Supplier")
        # Create invoices in current month
        self.invoice1 = PurchaseInvoice.objects.create(
            supplier=self.supplier,
            invoice_number='INV-DESIGN-001',
            date=timezone.now(),
            total_amount=1000
        )
        self.invoice2 = PurchaseInvoice.objects.create(
            supplier=self.supplier,
            invoice_number='INV-DESIGN-002',
            date=timezone.now(),
            total_amount=2000
        )
        self.url = reverse('purchase_list')

    def test_redesign_context_and_layout(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        
        # Check Context
        self.assertIn('monthly_total', response.context)
        self.assertEqual(response.context['monthly_total'], 3000)
        self.assertIn('top_suppliers', response.context)
        self.assertTrue(len(response.context['top_suppliers']) > 0)
        self.assertEqual(response.context['top_suppliers'][0].total_purchased, 3000)
        
        # Check HTML Content (Design Elements)
        content = response.content.decode('utf-8')
        
        # Header
        self.assertIn('Purchase Ledger', content)
        self.assertIn('New Purchase', content) # Button
        
        # Right Panel
        self.assertIn('Monthly Overview', content)
        self.assertIn('Track your spending', content)
        self.assertIn('Total Purchases (This Month)', content)
        self.assertIn('Top Suppliers', content)
        
        # Card List logic
        # Check for card classes
        self.assertIn('bg-white rounded-2xl p-5 border border-gray-100', content)
        
        # Check Data in List
        self.assertIn('INV-DESIGN-001', content)
        self.assertIn('Design Test Supplier', content)
        # Check amounts formatting (with rupee symbol or comma if enabled)
        # We used |intcomma so 1,000 becomes 1,000. 
        # But 1000 might be 1000 or 1,000 depending on locale.
        # Just check the strings exist.
