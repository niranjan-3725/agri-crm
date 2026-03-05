"""
Tests: Purchase Price Integrity Validation
==========================================
Enforces the business rule:  Basic Rate ≤ Sell Price ≤ MRP

Covers:
  1.  POST to /purchases/new/ with Basic Rate > MRP  → rejected (no redirect)
  2.  POST to /purchases/new/ with Sell Price > MRP  → rejected
  3.  POST to /purchases/new/ with Sell Price < Basic Rate → rejected
  4.  POST with valid prices (Rate < Sell ≤ MRP)     → accepted (redirects to detail)
  5.  Model-level clean(): PurchaseItem rejects selling_price < basic_rate
"""

from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from decimal import Decimal

from master_data.models import Supplier, Product, Category, Manufacturer
from inventory.models import Batch
from transactions.models import PurchaseInvoice, PurchaseItem


# ── Shared test setup ────────────────────────────────────────────────────────
class _PurchaseFormBase(TestCase):
    """Creates the master-data objects every purchase test needs."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_superuser('admin', 'admin@test.com', 'pass')
        cls.category = Category.objects.create(name='Fertilisers', cgst_rate=0, sgst_rate=0, igst_rate=0)
        cls.manufacturer = Manufacturer.objects.create(name='AgroTech Ltd')
        cls.supplier = Supplier.objects.create(
            name='Test Supplier', gstin='', phone='9999999999', address='Test City'
        )
        cls.product = Product.objects.create(
            name='UniqueTestProduct_XYZ', hsn_code='3105',
            unit_type='Kg', category=cls.category, manufacturer=cls.manufacturer
        )

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.user)

    def _post_purchase(self, rate, mrp, sell_price, invoice_suffix='001'):
        """Helper: POST a single-item purchase and return the response."""
        return self.client.post('/purchases/new/', {
            'supplier': self.supplier.id,
            'date': '2026-03-05',
            'invoice_number': f'TEST-PRICE-{invoice_suffix}',
            'product_name[]': ['UniqueTestProduct_XYZ'],
            'batch_number[]': ['BATCH-T01'],
            'mfg_date[]': ['2025-01-01'],
            'expiry_date[]': ['2027-12-31'],
            'size[]': ['1.0'],
            'unit[]': ['kg'],
            'qty[]': ['10'],
            'mrp[]': [str(mrp)],
            'purchase_rate[]': [str(rate)],
            'selling_price[]': [str(sell_price)],
            'margin[]': ['0'],
            'net_cost[]': [str(rate)],
            'loading_charges': '0',
            'discount': '0',
            'payment_status': 'UNPAID',
            'amount_paid': '0',
        })


# ── View-level POST validation tests ────────────────────────────────────────
class TestPurchasePriceValidationView(_PurchaseFormBase):

    def test_basic_rate_exceeds_mrp_is_rejected(self):
        """
        Core business rule: Basic Rate cannot exceed MRP.
        A purchase where rate=200, mrp=100 must be REJECTED — no 302 redirect.
        """
        response = self._post_purchase(rate=200, mrp=100, sell_price=150, invoice_suffix='A01')
        self.assertNotEqual(
            response.status_code, 302,
            "Purchase with Basic Rate (200) > MRP (100) must be rejected."
        )
        # Server should return the form with an error message
        self.assertContains(response, 'Basic Rate', status_code=200)

    def test_sell_price_exceeds_mrp_is_rejected(self):
        """Sell Price cannot exceed MRP."""
        response = self._post_purchase(rate=80, mrp=100, sell_price=150, invoice_suffix='A02')
        self.assertNotEqual(
            response.status_code, 302,
            "Purchase with Sell Price (150) > MRP (100) must be rejected."
        )
        self.assertContains(response, 'Sell Price', status_code=200)

    def test_sell_price_below_basic_rate_is_rejected(self):
        """Sell Price cannot be lower than Basic Rate."""
        response = self._post_purchase(rate=100, mrp=200, sell_price=60, invoice_suffix='A03')
        self.assertNotEqual(
            response.status_code, 302,
            "Purchase with Sell Price (60) < Basic Rate (100) must be rejected."
        )
        self.assertContains(response, 'Sell Price', status_code=200)

    def test_valid_price_hierarchy_is_accepted(self):
        """
        Happy path: Basic Rate (80) ≤ Sell Price (100) ≤ MRP (120).
        Should redirect to purchase_detail (302).
        """
        response = self._post_purchase(rate=80, mrp=120, sell_price=100, invoice_suffix='A04')
        self.assertEqual(
            response.status_code, 302,
            "Valid purchase (Rate 80 ≤ Sell 100 ≤ MRP 120) should be accepted and redirect."
        )

    def test_rate_equals_mrp_is_accepted(self):
        """Edge case: Basic Rate == MRP is valid (zero-margin purchase)."""
        response = self._post_purchase(rate=100, mrp=100, sell_price=100, invoice_suffix='A05')
        self.assertEqual(
            response.status_code, 302,
            "Purchase where Rate == Sell == MRP should be accepted."
        )


# ── Model-level clean() tests ────────────────────────────────────────────────
class TestPurchaseItemModelClean(_PurchaseFormBase):

    def _make_invoice(self):
        return PurchaseInvoice.objects.create(
            supplier=self.supplier, invoice_number='TEST-MODEL-CLEAN-001',
            date='2026-03-05', total_amount=0
        )

    def _make_batch(self, mrp):
        return Batch.objects.create(
            product=self.product, batch_number='BCLEAN01',
            mrp=Decimal(str(mrp)), manufacturing_date='2025-01-01',
            expiry_date='2027-12-31', size=Decimal('1.0'), unit='kg',
            purchase_price=Decimal('0'), base_selling_price=Decimal('0'),
            current_quantity=0
        )

    def test_clean_rejects_selling_price_below_basic_rate(self):
        """
        PurchaseItem.clean() must raise ValidationError
        when selling_price < basic_rate.
        """
        invoice = self._make_invoice()
        batch = self._make_batch(mrp=200)
        item = PurchaseItem(
            invoice=invoice, batch=batch,
            quantity=5,
            basic_rate=Decimal('100'),
            selling_price=Decimal('60'),  # INVALID: below basic_rate
            tax_amount=Decimal('0'),
            total_amount=Decimal('500'),
        )
        with self.assertRaises(ValidationError) as ctx:
            item.clean()
        self.assertIn('selling_price', ctx.exception.message_dict)

    def test_clean_rejects_basic_rate_above_mrp(self):
        """
        PurchaseItem.clean() must raise ValidationError
        when basic_rate > batch.mrp.
        """
        invoice = self._make_invoice()
        batch = self._make_batch(mrp=100)
        item = PurchaseItem(
            invoice=invoice, batch=batch,
            quantity=5,
            basic_rate=Decimal('150'),  # INVALID: exceeds mrp=100
            selling_price=Decimal('130'),
            tax_amount=Decimal('0'),
            total_amount=Decimal('750'),
        )
        with self.assertRaises(ValidationError) as ctx:
            item.clean()
        self.assertIn('basic_rate', ctx.exception.message_dict)

    def test_clean_accepts_valid_price_hierarchy(self):
        """
        PurchaseItem.clean() must NOT raise when
        basic_rate ≤ selling_price ≤ batch.mrp.
        """
        invoice = self._make_invoice()
        batch = self._make_batch(mrp=200)
        item = PurchaseItem(
            invoice=invoice, batch=batch,
            quantity=5,
            basic_rate=Decimal('80'),
            selling_price=Decimal('120'),  # VALID: 80 ≤ 120 ≤ 200
            tax_amount=Decimal('0'),
            total_amount=Decimal('400'),
        )
        # Should not raise
        item.clean()
