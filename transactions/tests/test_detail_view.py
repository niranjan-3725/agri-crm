from django.test import TestCase, Client
from django.urls import reverse
from master_data.models import Supplier
from transactions.models import PurchaseInvoice
from datetime import date

class PurchaseDetailViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.supplier = Supplier.objects.create(name="Detail Supplier")
        self.invoice = PurchaseInvoice.objects.create(
            supplier=self.supplier,
            invoice_number='INV-DETAIL-001',
            date=date.today(),
            total_amount=1000
        )
        self.url = reverse('purchase_detail', args=[self.invoice.pk])
        self.edit_url = reverse('purchase_edit', args=[self.invoice.pk])

    def test_detail_view_contains_edit_link(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'transactions/purchase_detail.html')
        # Check if the edit URL is present in the response
        self.assertContains(response, self.edit_url)
