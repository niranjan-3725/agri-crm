from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from transactions.models import PurchaseInvoice, Supplier
from decimal import Decimal
from django.utils import timezone
from datetime import timedelta

class MonthlyOverviewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='testuser', password='password')
        self.client.login(username='testuser', password='password')
        self.supplier = Supplier.objects.create(name='Test Supplier', phone='1234567890', address='Test Address', gstin='27ABCDE1234F1Z2', default_credit_period=30)
        self.url = reverse('purchase_list')

    def test_increase(self):
        now = timezone.now()
        # Last Month: 100
        last_month = now.replace(day=1) - timedelta(days=1)
        PurchaseInvoice.objects.create(supplier=self.supplier, invoice_number='INV-LAST', date=last_month, total_amount=100)
        # This Month: 200
        PurchaseInvoice.objects.create(supplier=self.supplier, invoice_number='INV-THIS', date=now, total_amount=200)

        response = self.client.get(self.url)
        self.assertEqual(response.context['monthly_total'], 200)
        self.assertTrue(response.context['has_last_data'])
        self.assertEqual(response.context['trend'], 'up')
        self.assertEqual(response.context['percentage_diff'], 100.0) # (200-100)/100 * 100 = 100%

    def test_decrease(self):
        now = timezone.now()
        # Last Month: 200
        last_month = now.replace(day=1) - timedelta(days=1)
        PurchaseInvoice.objects.create(supplier=self.supplier, invoice_number='INV-LAST', date=last_month, total_amount=200)
        # This Month: 100
        PurchaseInvoice.objects.create(supplier=self.supplier, invoice_number='INV-THIS', date=now, total_amount=100)

        response = self.client.get(self.url)
        self.assertEqual(response.context['monthly_total'], 100)
        self.assertTrue(response.context['has_last_data'])
        self.assertEqual(response.context['trend'], 'down')
        self.assertEqual(response.context['percentage_diff'], 50.0) # (100-200)/200 * 100 = 50%

    def test_no_last_data(self):
        now = timezone.now()
        # This Month: 100
        PurchaseInvoice.objects.create(supplier=self.supplier, invoice_number='INV-THIS', date=now, total_amount=100)

        response = self.client.get(self.url)
        self.assertFalse(response.context['has_last_data']) 
        # Percentage/Trend don't matter if has_last_data is False, logic handles it.

    def test_year_boundary(self):
        # Specific tricky case: Dec last year vs Dec this year
        now = timezone.now()
        
        # Determine "Same Month Last Year"
        # Since we filter by YEAR, specific month logic is: date__year=current_year, date__month=current_month
        # So creating an invoice for same month but LAST YEAR should NOT count.
        
        last_year = now - timedelta(days=365) # Roughly last year
        # Ensure it's the same month index
        if last_year.month != now.month:
             # Adjust if needed, but simplistic check:
             # Just set date manually to Now Year-1
             pass
        
        last_year_date = now.replace(year=now.year - 1)
        
        PurchaseInvoice.objects.create(supplier=self.supplier, invoice_number='INV-OLD', date=last_year_date, total_amount=9999)
        PurchaseInvoice.objects.create(supplier=self.supplier, invoice_number='INV-NEW', date=now, total_amount=100)

        response = self.client.get(self.url)
        self.assertEqual(response.context['monthly_total'], 100) # Should NOT include 9999
