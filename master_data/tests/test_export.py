from django.test import TestCase, Client
from django.urls import reverse
from master_data.models import Customer

class CustomerExportTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.customer1 = Customer.objects.create(
            name='Test Customer 1',
            mobile_no='1234567890',
            city='Test City',
            address='Test Address',
            gstin='GST123'
        )
        self.customer2 = Customer.objects.create(
            name='Test Customer 2',
            mobile_no='0987654321',
            city='Another City',
            address='Another Address'
        )
        self.url = reverse('customer_export')

    def test_export_customer_csv(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv')
        self.assertEqual(response['Content-Disposition'], 'attachment; filename="customer_list.csv"')

        content = response.content.decode('utf-8')
        lines = content.strip().split('\r\n')
        
        # Check header
        self.assertEqual(lines[0], 'Customer Name,Mobile Number,City/Village,Address,GSTIN')
        
        # Check data (order by name)
        self.assertIn('Test Customer 1,1234567890,Test City,Test Address,GST123', content)
        self.assertIn('Test Customer 2,0987654321,Another City,Another Address,', content)

    def test_export_link_on_list_page(self):
        response = self.client.get(reverse('customer_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.url)
        self.assertContains(response, 'Export Customer List')
        # Ensure the old button text is gone
        self.assertNotContains(response, 'Download Report')
