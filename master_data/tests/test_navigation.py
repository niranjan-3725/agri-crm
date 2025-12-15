"""
Test navigation links for master data sections.
Verifies that Category and Manufacturer links are present in the sidebar.
"""
from django.test import TestCase, Client
from django.urls import reverse
from master_data.models import Customer


class NavigationTest(TestCase):
    """Test that master data navigation links are present in the sidebar."""
    
    def setUp(self):
        self.client = Client()
    
    def test_category_link_in_navigation(self):
        """Test that the Category link is present in the navigation sidebar."""
        # Access the home page to get the sidebar
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        
        # Check that the category list URL is in the response
        category_url = reverse('category_list')
        self.assertContains(response, category_url)
        self.assertContains(response, 'Categories')
    
    def test_manufacturer_link_in_navigation(self):
        """Test that the Manufacturer link is present in the navigation sidebar."""
        # Access the home page to get the sidebar
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        
        # Check that the manufacturer list URL is in the response
        manufacturer_url = reverse('manufacturer_list')
        self.assertContains(response, manufacturer_url)
        self.assertContains(response, 'Manufacturers')
    
    def test_all_master_links_present(self):
        """Test that all master data links are present in the navigation."""
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        
        # Check all expected master links
        expected_links = [
            ('customer_list', 'Customers'),
            ('supplier_list', 'Suppliers'),
            ('product_list', 'Products'),
            ('category_list', 'Categories'),
            ('manufacturer_list', 'Manufacturers'),
        ]
        
        for url_name, link_text in expected_links:
            url = reverse(url_name)
            self.assertContains(
                response, 
                url, 
                msg_prefix=f"URL for {url_name} not found in navigation"
            )
            self.assertContains(
                response, 
                link_text, 
                msg_prefix=f"Link text '{link_text}' not found in navigation"
            )
    
    def test_category_page_accessible(self):
        """Test that the category list page is accessible."""
        response = self.client.get(reverse('category_list'))
        self.assertEqual(response.status_code, 200)
    
    def test_manufacturer_page_accessible(self):
        """Test that the manufacturer list page is accessible."""
        response = self.client.get(reverse('manufacturer_list'))
        self.assertEqual(response.status_code, 200)


class CustomerListPageTest(TestCase):
    """Test the redesigned customer list page."""
    
    def setUp(self):
        self.client = Client()
        # Create test customers
        self.customer1 = Customer.objects.create(
            name='Niranjan Kumar',
            mobile_no='9876543210',
            city='Siddipet',
            address='Main Road, Siddipet'
        )
        self.customer2 = Customer.objects.create(
            name='Rajesh Farming Co',
            mobile_no='9848012345',
            city='Karimnagar',
            address='Industrial Area'
        )
    
    def test_customer_list_page_loads(self):
        """Test that the customer list page loads successfully."""
        response = self.client.get(reverse('customer_list'))
        self.assertEqual(response.status_code, 200)
    
    def test_customer_list_has_card_layout(self):
        """Test that the customer list uses the new card-based layout."""
        response = self.client.get(reverse('customer_list'))
        # Check for card styling classes
        self.assertContains(response, 'rounded-3xl')
        self.assertContains(response, 'Customer Directory')
    
    def test_customer_list_shows_customers(self):
        """Test that customers are displayed on the page."""
        response = self.client.get(reverse('customer_list'))
        self.assertContains(response, 'Niranjan Kumar')
        self.assertContains(response, 'Rajesh Farming Co')
    
    def test_customer_list_has_right_panel_stats(self):
        """Test that the right panel shows statistics."""
        response = self.client.get(reverse('customer_list'))
        # Check for total customers count in context
        self.assertEqual(response.context['total_customers'], 2)
    
    def test_customer_list_shows_top_cities(self):
        """Test that top cities are included in the context."""
        response = self.client.get(reverse('customer_list'))
        top_cities = list(response.context['top_cities'])
        self.assertEqual(len(top_cities), 2)
        cities = [c['city'] for c in top_cities]
        self.assertIn('Siddipet', cities)
        self.assertIn('Karimnagar', cities)
    
    def test_customer_list_search(self):
        """Test that search functionality works."""
        response = self.client.get(reverse('customer_list'), {'q': 'Niranjan'})
        self.assertContains(response, 'Niranjan Kumar')
        self.assertNotContains(response, 'Rajesh Farming Co')
    
    def test_customer_list_mobile_search(self):
        """Test that search by mobile number works."""
        response = self.client.get(reverse('customer_list'), {'q': '9876543210'})
        self.assertContains(response, 'Niranjan Kumar')
        self.assertNotContains(response, 'Rajesh Farming Co')
