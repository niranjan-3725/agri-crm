from django.test import TestCase, Client
from django.urls import reverse
from transactions.models import PurchaseInvoice, Supplier, SupplierPayment
from django.utils import timezone
from decimal import Decimal

class DeletionStaleDataTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.supplier = Supplier.objects.create(name='Test Supplier', phone='1234567890')
        self.invoice = PurchaseInvoice.objects.create(
            supplier=self.supplier, 
            invoice_number='INV-STALE-CHECK', 
            date=timezone.now().date(), 
            total_amount=1000, 
            balance_due=1000
        )
        self.dashboard_url = reverse('accounts_payable')

    def test_recent_activity_updates_after_deletion(self):
        # 1. Create Payment
        payment = SupplierPayment.objects.create(
            invoice=self.invoice,
            amount=500,
            payment_date=timezone.now().date()
        )
        
        # 2. Verify in Dashboard
        response = self.client.get(self.dashboard_url)
        self.assertContains(response, 'INV-STALE-CHECK')
        self.assertContains(response, '500') # Should show amount
        
        # 3. Delete Payment
        payment.delete()
        
        # 4. Verify GONE from Dashboard Context
        response = self.client.get(self.dashboard_url)
        
        # Check specifically the recent_payments context
        # It should be empty because we deleted the only payment
        recent_payments = response.context['recent_payments']
        self.assertEqual(len(recent_payments), 0, "Recent Activity list should be empty after deletion")
