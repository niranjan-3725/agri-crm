from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from transactions.models import PurchaseInvoice, Supplier, SupplierPayment
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal

class PayableDashboardTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='testuser', password='password')
        self.client.login(username='testuser', password='password')
        self.supplier = Supplier.objects.create(name='Test Supplier', phone='1234567890', address='Test Address', gstin='GSTIN123', default_credit_period=30)
        self.url = reverse('accounts_payable')

    def test_kpi_calculations(self):
        today = timezone.now().date()
        
        # 1. Overdue Invoice (Due yesterday)
        inv_overdue = PurchaseInvoice.objects.create(
            supplier=self.supplier, invoice_number='INV-OLD', date=today - timedelta(days=31), 
            total_amount=1000, balance_due=1000, payment_status='UNPAID',
            due_date=today - timedelta(days=1)
        )

        # 2. Outstanding Invoice (Due tomorrow)
        inv_outstanding = PurchaseInvoice.objects.create(
            supplier=self.supplier, invoice_number='INV-NEW', date=today, 
            total_amount=500, balance_due=500, payment_status='UNPAID',
            due_date=today + timedelta(days=1)
        )

        # 3. Paid Invoice (Should be ignored for outstanding)
        inv_paid = PurchaseInvoice.objects.create(
            supplier=self.supplier, invoice_number='INV-PAID', date=today, 
            total_amount=200, amount_paid=200, balance_due=0, payment_status='PAID',
            due_date=today
        )

        # 4. Payment made today
        # This will trigger signal: amount_paid=100, balance_due=400.
        SupplierPayment.objects.create(invoice=inv_outstanding, amount=100, payment_date=today)
        # Refresh to ensure DB update (though signal does it)
        inv_outstanding.refresh_from_db()

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        
        # Check KPIs
        # Total Outstanding = 1000 (Overdue) + 400 (Outstanding) = 1400
        # (Paid invoice ignored because status is PAID)
        self.assertEqual(response.context['total_outstanding'], 1400)
        
        # Overdue = 1000
        self.assertEqual(response.context['overdue_amount'], 1000)
        
        # Paid This Month = 100
        self.assertEqual(response.context['paid_this_month'], 100)
        
    def test_record_payment(self):
        inv = PurchaseInvoice.objects.create(
            supplier=self.supplier, invoice_number='INV-PAY', date=timezone.now().date(), 
            total_amount=1000, balance_due=1000, payment_status='UNPAID'
        )
        
        record_url = reverse('record_payment')
        response = self.client.post(record_url, {
            'invoice_id': inv.id,
            'amount': 200,
            'payment_mode': 'CASH'
        })
        
        self.assertEqual(response.status_code, 200)
        
        # Check Invoice Updated
        inv.refresh_from_db()
        self.assertEqual(inv.amount_paid, 200)
        self.assertEqual(inv.balance_due, 800)
        
        # Check Payment Created
        self.assertTrue(SupplierPayment.objects.filter(invoice=inv, amount=200).exists())
