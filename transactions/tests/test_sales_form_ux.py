"""
transactions/tests/test_sales_form_ux.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Sprint 17 UX — Definition of Done tests for the refactored Sales Form.

Tests confirmed by running the test suite (no browser required):
  1. The search_products endpoint exposes moving_average_price.
  2. The sales form page renders (200 OK).
  3. The rendered HTML contains "Save as Draft" — not "Complete Sale".
  4. The rendered HTML does NOT contain a red bulk-error summary box.
  5. The rendered Alpine.js contains hasNegativeMargin, marginPct, marginLabel.
  6. The rendered HTML contains the blur guard (@mousedown.prevent) on dropdowns.
"""

from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
import json

from master_data.models import Category, Customer, Manufacturer, Product
from inventory.models import Batch, Warehouse, StockBin


class SearchProductsMapTest(TestCase):
    """search_products endpoint must expose moving_average_price."""

    def setUp(self):
        cat = Category.objects.create(name='Seeds', cgst_rate=0, sgst_rate=0)
        mfr = Manufacturer.objects.create(name='MfrA')
        self.product = Product.objects.create(
            name='Wheat Seed 5kg', hsn_code='1001', unit_type='Bag',
            category=cat, manufacturer=mfr,
            moving_average_price=42.50,
        )

    def test_map_field_present_in_response(self):
        url = reverse('search_products') + '?q=Wheat&format=json'
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        self.assertEqual(len(data), 1)
        self.assertIn('moving_average_price', data[0])
        self.assertAlmostEqual(data[0]['moving_average_price'], 42.50, places=2)

    def test_map_is_zero_when_not_set(self):
        cat = Category.objects.create(name='Tools', cgst_rate=0, sgst_rate=0)
        mfr = Manufacturer.objects.create(name='MfrB')
        Product.objects.create(
            name='Spade', hsn_code='8201', unit_type='Kg',
            category=cat, manufacturer=mfr,
            moving_average_price=0,
        )
        url = reverse('search_products') + '?q=Spade&format=json'
        resp = self.client.get(url)
        data = json.loads(resp.content)
        self.assertEqual(data[0]['moving_average_price'], 0)


class SalesFormRenderTest(TestCase):
    """Sales form HTML must meet all Ive-standard DoD checks."""

    def setUp(self):
        # Auth user needed if login is required
        self.user = User.objects.create_user('staff', password='pass')
        self.client.force_login(self.user)

    def _get_form_html(self):
        resp = self.client.get(reverse('create_sale'))
        self.assertEqual(resp.status_code, 200)
        return resp.content.decode()

    def test_save_as_draft_label_present(self):
        """Submit button must say 'Save as Draft'."""
        html = self._get_form_html()
        self.assertIn('Save as Draft', html)

    def test_complete_sale_label_absent(self):
        """Old 'Complete Sale' label must be gone."""
        html = self._get_form_html()
        self.assertNotIn('Complete Sale', html)

    def test_no_bulk_red_error_box_by_default(self):
        """The old 'bg-red-50 border border-red-200' bulk error block must not appear by default (no error context)."""
        html = self._get_form_html()
        # Old class string from the removed bulk error div
        self.assertNotIn('bg-red-50 border border-red-200 text-red-700 px-6 py-4 rounded-2xl', html)

    def test_verified_state_binding_present(self):
        """Customer input must use the verified-state :class binding."""
        html = self._get_form_html()
        self.assertIn('border-blue-300 bg-blue-50/40', html)

    def test_blur_guard_on_customer_dropdown(self):
        """Customer dropdown must have @mousedown.prevent (blur guard)."""
        html = self._get_form_html()
        self.assertIn('@mousedown.prevent', html)

    def test_margin_badge_alpine_helpers_present(self):
        """Alpine.js must define marginPct, marginLabel, hasNegativeMargin."""
        html = self._get_form_html()
        self.assertIn('marginPct', html)
        self.assertIn('marginLabel', html)
        self.assertIn('hasNegativeMargin', html)

    def test_stock_badge_present(self):
        """Stock pulse badge text prefix must be in the template."""
        html = self._get_form_html()
        self.assertIn("'Avail: '", html)

    def test_negative_margin_gate_in_html(self):
        """Negative margin confirmation gate elements must be present."""
        html = self._get_form_html()
        self.assertIn('negativeMarginConfirmed', html)
        self.assertIn('below-cost sale', html)

    def test_focus_flow_nextTick_present(self):
        """selectProduct must trigger $nextTick focus flow to qty field."""
        html = self._get_form_html()
        self.assertIn('$nextTick', html)
        self.assertIn("'qty-input-'", html)

    def test_map_stored_on_row(self):
        """Row state must carry a 'map' field from selectProduct."""
        html = self._get_form_html()
        self.assertIn('row.map', html)
        self.assertIn('moving_average_price', html)
