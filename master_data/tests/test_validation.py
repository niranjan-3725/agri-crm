from django.test import TestCase
from master_data.models import Customer
from master_data.forms import CustomerForm

class CustomerMobileValidationTest(TestCase):
    def setUp(self):
        # Create a baseline customer
        self.customer = Customer.objects.create(
            name='Existing Customer',
            mobile_no='9999999999',
            city='Test City',
            address='Test Address'
        )

    def test_valid_mobile_number(self):
        """Test that a valid 10-digit number passes validation."""
        form_data = {
            'name': 'New Customer',
            'mobile_no': '9876543210',
            'city': 'City',
            'address': 'Address'
        }
        form = CustomerForm(data=form_data)
        self.assertTrue(form.is_valid())

    def test_mobile_number_too_short(self):
        """Test validation failure for number with less than 10 digits."""
        form_data = {
            'name': 'Short Number',
            'mobile_no': '123456789', # 9 digits
            'city': 'City',
            'address': 'Address'
        }
        form = CustomerForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('mobile_no', form.errors)
        self.assertEqual(form.errors['mobile_no'][0], "Mobile number must be exactly 10 digits.")

    def test_mobile_number_too_long(self):
        """Test validation failure for number with more than 10 digits."""
        form_data = {
            'name': 'Long Number',
            'mobile_no': '12345678901', # 11 digits
            'city': 'City',
            'address': 'Address'
        }
        form = CustomerForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('mobile_no', form.errors)
        self.assertEqual(form.errors['mobile_no'][0], "Mobile number must be exactly 10 digits.")

    def test_non_numeric_mobile_number(self):
        """Test validation failure for non-numeric characters."""
        form_data = {
            'name': 'Alpha Number',
            'mobile_no': '123456789a', 
            'city': 'City',
            'address': 'Address'
        }
        form = CustomerForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('mobile_no', form.errors)
        self.assertEqual(form.errors['mobile_no'][0], "Mobile number must contain only digits.")

    def test_duplicate_mobile_number(self):
        """Test validation failure for duplicate mobile number."""
        form_data = {
            'name': 'Duplicate Customer',
            'mobile_no': '9999999999',  # Same as existing customer
            'city': 'City',
            'address': 'Address'
        }
        form = CustomerForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('mobile_no', form.errors)
        self.assertEqual(form.errors['mobile_no'][0], "Customer with this mobile number already exists.")

    def test_edit_same_customer_allowed(self):
        """Test that validation allows saving the same number when editing the user."""
        form_data = {
            'name': 'Existing Customer Updated',
            'mobile_no': '9999999999',  # Own number
            'city': 'Updated City',
            'address': 'Updated Address'
        }
        # bind form with instance
        form = CustomerForm(data=form_data, instance=self.customer)
        self.assertTrue(form.is_valid())
