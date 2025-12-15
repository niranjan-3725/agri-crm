from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from transactions.models import PurchaseInvoice, Supplier, SupplierPayment
from django.utils import timezone
from decimal import Decimal

class PaymentLedgerTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='testuser', password='password')
        self.client.login(username='testuser', password='password')
        self.supplier = Supplier.objects.create(name='Test Supplier', phone='1234567890')
        self.invoice = PurchaseInvoice.objects.create(
            supplier=self.supplier, 
            invoice_number='INV-LEDGER', 
            date=timezone.now().date(), 
            total_amount=1000, 
            balance_due=1000, 
            payment_status='UNPAID'
        )

    def test_record_payment_with_notes(self):
        url = reverse('record_payment')
        response = self.client.post(url, {
            'invoice_id': self.invoice.id,
            'amount': 500,
            'payment_mode': 'UPI',
            'notes': 'Test Transaction ID 123'
        })
        self.assertEqual(response.status_code, 200)
        
        # Verify Payment Created
        payment = SupplierPayment.objects.first()
        self.assertEqual(payment.amount, 500)
        self.assertEqual(payment.notes, 'Test Transaction ID 123')
        
        # Verify Invoice Updated
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.amount_paid, 500)
        self.assertEqual(self.invoice.balance_due, 500)

    def test_delete_payment(self):
        # Create initial payment
        payment = SupplierPayment.objects.create(
            invoice=self.invoice,
            amount=500,
            payment_date=timezone.now().date()
        )
        
        # Verify Initial State (Signal should have run)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.amount_paid, 500)
        
        # Delete Payment
        delete_url = reverse('delete_supplier_payment', args=[payment.pk])
        response = self.client.post(delete_url)
        
        # Verify Redirect
        self.assertRedirects(response, reverse('purchase_detail', args=[self.invoice.pk]))
        
        # Verify Invoice Rolled Back
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.amount_paid, 0)
        self.assertEqual(self.invoice.balance_due, 1000)
        self.assertEqual(self.invoice.payment_status, 'UNPAID')

    def test_dashboard_link_and_status(self):
        # Case 1: Unpaid
        url = reverse('accounts_payable')
        response = self.client.get(url)
        self.assertContains(response, 'href="/purchases/{}/"'.format(self.invoice.pk))
        self.assertContains(response, 'Pay') # Should show Pay button
        
        # Case 2: Paid
        SupplierPayment.objects.create(invoice=self.invoice, amount=1000)
        response = self.client.get(url)
        self.assertContains(response, 'Settled') # Should show Settled badge
        self.assertNotContains(response, 'showPayModal = true') # Check logic exclusion
