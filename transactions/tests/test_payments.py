from django.test import TestCase
from transactions.models import PurchaseInvoice, SupplierPayment
from master_data.models import Supplier
from decimal import Decimal
from django.utils import timezone
from datetime import timedelta

class SupplierPaymentTests(TestCase):
    def setUp(self):
        self.supplier = Supplier.objects.create(name="Bayer", default_credit_period=45)
        self.invoice = PurchaseInvoice.objects.create(
            supplier=self.supplier,
            invoice_number="INV-001",
            date=timezone.now().date(),
            total_amount=Decimal("1000.00") # Changed from grand_total to total_amount
        )

    def test_due_date_auto_calculation(self):
        """Test if due date is auto-set to date + 45 days"""
        expected_due = self.invoice.date + timedelta(days=45)
        # Refresh to get updated due_date from save()
        self.invoice.refresh_from_db() 
        self.assertEqual(self.invoice.due_date, expected_due)

    def test_payment_updates_status(self):
        """Test that paying 500 makes status PARTIAL and balance 500"""
        SupplierPayment.objects.create(invoice=self.invoice, amount=Decimal("500.00"))
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.payment_status, 'PARTIAL')
        self.assertEqual(self.invoice.balance_due, Decimal("500.00"))

    def test_full_settlement(self):
        """Test that full payment marks as PAID"""
        SupplierPayment.objects.create(invoice=self.invoice, amount=Decimal("1000.00"))
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.payment_status, 'PAID')
        self.assertEqual(self.invoice.balance_due, Decimal("0.00"))
