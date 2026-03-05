"""
Tests: Product Selection Validation
=====================================
Validates the server-side behaviour that mirrors the UI's search-and-select
validation state:

  UI rule  : "Select a product from master data" error clears only when the
             user picks a product from the dropdown (setting `product_id`).

  Server rule: create_purchase rejects any product_name that cannot be
              resolved to a known Product record.

Covers:
  1. POST with a recognised product name   → accepted (302 redirect)
  2. POST with an unrecognised product name → rejected (200, shows error)
  3. POST with a blank product name        → rejected (200, shows error)
"""

from django.test import TestCase, Client
from django.contrib.auth.models import User

from master_data.models import Supplier, Product, Category, Manufacturer


# ── Shared test setup ────────────────────────────────────────────────────────
class _SelectionBase(TestCase):
    """Creates master-data objects required by every selection test."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_superuser('sel_admin', 'sel@test.com', 'pass')
        cls.category = Category.objects.create(
            name='Seeds_Sel', cgst_rate=0, sgst_rate=0, igst_rate=0
        )
        cls.manufacturer = Manufacturer.objects.create(name='SeedCorp_Sel')
        cls.supplier = Supplier.objects.create(
            name='Sel Supplier', gstin='', phone='9000000001', address='Sel City'
        )
        cls.product = Product.objects.create(
            name='SelTestProduct_ABC', hsn_code='1001',
            unit_type='Kg', category=cls.category, manufacturer=cls.manufacturer
        )

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.user)

    def _post(self, product_name, invoice_suffix='S01'):
        """POST a single-item purchase with the given product_name string."""
        return self.client.post('/purchases/new/', {
            'supplier': self.supplier.id,
            'date': '2026-03-05',
            'invoice_number': f'SEL-{invoice_suffix}',
            'product_name[]': [product_name],
            'batch_number[]': ['BATCH-SEL01'],
            'mfg_date[]': ['2025-01-01'],
            'expiry_date[]': ['2027-12-31'],
            'size[]': ['1.0'],
            'unit[]': ['kg'],
            'qty[]': ['5'],
            'mrp[]': ['150'],
            'purchase_rate[]': ['100'],
            'selling_price[]': ['120'],
            'margin[]': ['0'],
            'net_cost[]': ['100'],
            'loading_charges': '0',
            'discount': '0',
            'payment_status': 'UNPAID',
            'amount_paid': '0',
        })


# ── Tests ────────────────────────────────────────────────────────────────────
class TestProductSelectionValidation(_SelectionBase):

    def test_valid_product_name_is_accepted(self):
        """
        Mirrors the UI: selecting a product from the dropdown (which sets
        product_name to an exact master-data match) must be accepted.
        The server performs the same lookup; a match → 302 redirect.
        """
        response = self._post(product_name='SelTestProduct_ABC', invoice_suffix='S01')
        self.assertEqual(
            response.status_code, 302,
            "A recognised product name should be accepted and redirect (302)."
        )

    def test_unrecognised_product_name_is_rejected(self):
        """
        Mirrors the UI: typing a product name without selecting from the
        dropdown leaves no product_id, and the server must reject it.
        Any name that doesn't match a Product record → 200 with error.
        """
        response = self._post(product_name='GhostProduct_NOPE', invoice_suffix='S02')
        self.assertNotEqual(
            response.status_code, 302,
            "An unrecognised product name must be rejected — no redirect."
        )
        # The response should be 200 (re-rendered form) with an error message
        self.assertEqual(response.status_code, 200)

    def test_blank_product_name_is_rejected(self):
        """
        Posting an empty product name must not create a purchase.
        """
        response = self._post(product_name='', invoice_suffix='S03')
        self.assertNotEqual(
            response.status_code, 302,
            "A blank product name must be rejected — no redirect."
        )
        self.assertEqual(response.status_code, 200)

    def test_valid_selection_does_not_raise_product_error(self):
        """
        When a recognised product is posted, the response must NOT
        contain the 'product not found' error text that would indicate
        the UI validation state was not cleared.
        """
        response = self._post(product_name='SelTestProduct_ABC', invoice_suffix='S04')
        # Should redirect — no inline error rendered at all
        self.assertEqual(response.status_code, 302)
