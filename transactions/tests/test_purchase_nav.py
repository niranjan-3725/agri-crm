from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User

class PurchaseNavTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='testuser', password='password')
        self.client.login(username='testuser', password='password')
        self.url = reverse('create_purchase')

    def test_back_button_exists(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        
        # Check for link to purchase_list
        list_url = reverse('purchase_list')
        self.assertIn(f'href="{list_url}"', content)
        
        # Check for text or distinctive class
        self.assertIn('Back to Ledger', content)

    def test_detail_back_button_exists(self):
        # Create a dummy purchase to detail
        from transactions.models import PurchaseInvoice, Supplier
        from datetime import date
        supplier = Supplier.objects.create(name='Test Supplier', phone='123', address='Adr')
        invoice = PurchaseInvoice.objects.create(supplier=supplier, invoice_number='INV-001', date=date.today(), total_amount=100)
        
        detail_url = reverse('purchase_detail', args=[invoice.pk])
        response = self.client.get(detail_url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        
        list_url = reverse('purchase_list')
        self.assertIn(f'href="{list_url}"', content)
        self.assertIn('Back to Ledger', content)
