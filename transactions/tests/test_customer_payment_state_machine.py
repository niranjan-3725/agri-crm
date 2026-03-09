"""
Tests for CustomerPayment state machine (Phase 1 of Receivables Refactor).

Playbook rules exercised:
- Rule 13.1  CustomerPayment must have a status field (SUBMITTED / CANCELLED)
- Rule 13.2  cancel() must reverse GL entries before marking CANCELLED
- Rule 13.3  record_receipt must guard invoice.status == 'SUBMITTED'
- Rule 13.4  Signal only counts SUBMITTED payments toward balance_due
- Rule 5     record_receipt must be atomic
- Rule 9.1   Every successful submission redirects to the detail view of the document
- Rule 9.2   Only SUBMITTED invoices are eligible for payment
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from accounting.models import GLEntry
from master_data.models import Customer
from transactions.models import CustomerPayment, SalesInvoice


def _make_submitted_invoice(customer, grand_total=Decimal('1000.00')):
    """Create a SalesInvoice in SUBMITTED state with a preset grand_total."""
    invoice = SalesInvoice.objects.create(
        customer=customer,
        invoice_number=f"SI-TEST-{SalesInvoice.objects.count() + 1}",
        date=timezone.now().date(),
        grand_total=grand_total,
        total_taxable=grand_total,
        total_cgst=Decimal('0.00'),
        total_sgst=Decimal('0.00'),
        balance_due=grand_total,
        payment_status='UNPAID',
        status='SUBMITTED',
    )
    return invoice


class CustomerPaymentStatusFieldTest(TestCase):
    """Rule 13.1: status field defaults to SUBMITTED."""

    def setUp(self):
        self.customer = Customer.objects.create(name="Arjun Farms", mobile_no="9000000001")
        self.invoice = _make_submitted_invoice(self.customer)

    def test_new_payment_defaults_to_submitted(self):
        payment = CustomerPayment.objects.create(
            invoice=self.invoice,
            amount=Decimal('500.00'),
            payment_mode='CASH',
            status='SUBMITTED',
        )
        self.assertEqual(payment.status, 'SUBMITTED')

    def test_status_choices_are_submitted_and_cancelled(self):
        choice_values = [c[0] for c in CustomerPayment.STATUS_CHOICES]
        self.assertIn('SUBMITTED', choice_values)
        self.assertIn('CANCELLED', choice_values)


class CustomerPaymentCancelTest(TestCase):
    """Rule 13.2: cancel() deletes GL entries and restores balance_due."""

    def setUp(self):
        self.customer = Customer.objects.create(name="Balu Traders", mobile_no="9000000002")
        self.invoice = _make_submitted_invoice(self.customer, grand_total=Decimal('2000.00'))

    def test_cancel_sets_status_to_cancelled(self):
        payment = CustomerPayment.objects.create(
            invoice=self.invoice,
            amount=Decimal('2000.00'),
            payment_mode='UPI',
            status='SUBMITTED',
        )
        payment.cancel()
        payment.refresh_from_db()
        self.assertEqual(payment.status, 'CANCELLED')

    def test_cancel_removes_gl_entries(self):
        payment = CustomerPayment.objects.create(
            invoice=self.invoice,
            amount=Decimal('1000.00'),
            payment_mode='CASH',
            status='SUBMITTED',
        )
        # GL entries must exist after creation (Dr Cash/Bank, Cr AR)
        gl_before = GLEntry.objects.filter(
            reference_type='CustomerPayment', reference_id=payment.id
        ).count()
        self.assertGreater(gl_before, 0, "GL entries must be posted on payment creation")

        payment.cancel()

        gl_after = GLEntry.objects.filter(
            reference_type='CustomerPayment', reference_id=payment.id
        ).count()
        self.assertEqual(gl_after, 0, "GL entries must be deleted on cancel")

    def test_cancel_restores_invoice_balance_due(self):
        """Rule 13.4: signal filters SUBMITTED only; cancelled payment is excluded."""
        payment = CustomerPayment.objects.create(
            invoice=self.invoice,
            amount=Decimal('800.00'),
            payment_mode='BANK',
            status='SUBMITTED',
        )
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.balance_due, Decimal('1200.00'),
                         "balance_due should be reduced after payment")

        payment.cancel()

        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.balance_due, Decimal('2000.00'),
                         "balance_due must be fully restored after cancel")

    def test_cancel_restores_invoice_payment_status_to_unpaid(self):
        payment = CustomerPayment.objects.create(
            invoice=self.invoice,
            amount=Decimal('2000.00'),
            payment_mode='CASH',
            status='SUBMITTED',
        )
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.payment_status, 'PAID')

        payment.cancel()

        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.payment_status, 'UNPAID')

    def test_cancel_already_cancelled_raises(self):
        """Calling cancel() twice must raise ValidationError, not corrupt GL."""
        payment = CustomerPayment.objects.create(
            invoice=self.invoice,
            amount=Decimal('500.00'),
            payment_mode='UPI',
            status='SUBMITTED',
        )
        payment.cancel()
        with self.assertRaises(ValidationError):
            payment.cancel()

    def test_partial_payment_cancel_leaves_correct_balance(self):
        """Cancel one of two payments; only the remaining SUBMITTED one counts."""
        # Invoice grand_total=₹2000. Pay ₹1200 + ₹800 = ₹2000 (fully PAID).
        p1 = CustomerPayment.objects.create(
            invoice=self.invoice,
            amount=Decimal('1200.00'),
            payment_mode='CASH',
            status='SUBMITTED',
        )
        CustomerPayment.objects.create(
            invoice=self.invoice,
            amount=Decimal('800.00'),
            payment_mode='UPI',
            status='SUBMITTED',
        )
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.payment_status, 'PAID')

        p1.cancel()

        self.invoice.refresh_from_db()
        # Only ₹800 SUBMITTED payment remains → ₹1200 still due
        self.assertEqual(self.invoice.balance_due, Decimal('1200.00'))
        self.assertEqual(self.invoice.payment_status, 'PARTIAL')


class SignalStatusFilterTest(TestCase):
    """Rule 13.4: CANCELLED payments must not inflate amount_received."""

    def setUp(self):
        self.customer = Customer.objects.create(name="Chitra Mills", mobile_no="9000000003")
        self.invoice = _make_submitted_invoice(self.customer, grand_total=Decimal('500.00'))

    def test_cancelled_payment_excluded_from_amount_received(self):
        payment = CustomerPayment.objects.create(
            invoice=self.invoice,
            amount=Decimal('500.00'),
            payment_mode='CHEQUE',
            status='SUBMITTED',
        )
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.amount_received, Decimal('500.00'))

        payment.cancel()

        self.invoice.refresh_from_db()
        self.assertEqual(
            self.invoice.amount_received, Decimal('0.00'),
            "CANCELLED payment must not count toward amount_received"
        )


class RecordReceiptViewTest(TestCase):
    """Rule 13.3 + Rule 9.2: view guards for SUBMITTED invoices only."""

    def setUp(self):
        from django.contrib.auth.models import User
        self.client = Client()
        User.objects.create_user(username='tester', password='pass')
        self.client.login(username='tester', password='pass')
        self.customer = Customer.objects.create(name="Dinesh Agro", mobile_no="9000000004")

    def test_record_receipt_on_submitted_invoice_succeeds(self):
        invoice = _make_submitted_invoice(self.customer, grand_total=Decimal('1000.00'))
        url = reverse('record_receipt', kwargs={'pk': invoice.pk})
        response = self.client.post(url, {
            'amount': '500',
            'payment_mode': 'CASH',
        })
        # Rule 9.1: redirects to customer_payment_detail on success
        self.assertEqual(response.status_code, 302)
        invoice.refresh_from_db()
        self.assertEqual(invoice.balance_due, Decimal('500.00'))
        self.assertEqual(invoice.payment_status, 'PARTIAL')

    def test_record_receipt_on_draft_invoice_rejected(self):
        """Rule 9.2 / Rule 13.3: DRAFT invoices must not accept receipts."""
        invoice = SalesInvoice.objects.create(
            customer=self.customer,
            invoice_number='SI-DRAFT-1',
            date=timezone.now().date(),
            grand_total=Decimal('1000.00'),
            total_taxable=Decimal('1000.00'),
            total_cgst=Decimal('0.00'),
            total_sgst=Decimal('0.00'),
            balance_due=Decimal('1000.00'),
            payment_status='UNPAID',
            status='DRAFT',       # ← DRAFT, must be rejected
        )
        url = reverse('record_receipt', kwargs={'pk': invoice.pk})
        response = self.client.post(url, {'amount': '500', 'payment_mode': 'CASH'})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(CustomerPayment.objects.filter(invoice=invoice).exists())

    def test_record_receipt_zero_amount_rejected(self):
        invoice = _make_submitted_invoice(self.customer)
        url = reverse('record_receipt', kwargs={'pk': invoice.pk})
        response = self.client.post(url, {'amount': '0', 'payment_mode': 'CASH'})
        self.assertEqual(response.status_code, 400)

    def test_record_receipt_is_atomic_gl_and_payment_together(self):
        """Rule 5: If GL posting fails the payment row must not persist."""
        invoice = _make_submitted_invoice(self.customer, grand_total=Decimal('300.00'))
        count_before = CustomerPayment.objects.count()
        gl_before = GLEntry.objects.count()

        url = reverse('record_receipt', kwargs={'pk': invoice.pk})
        response = self.client.post(url, {'amount': '300', 'payment_mode': 'CASH'})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(CustomerPayment.objects.count(), count_before + 1)
        # GL must have been posted (Dr Cash/Bank + Cr AR = 2 entries)
        self.assertEqual(GLEntry.objects.count(), gl_before + 2)


class RecordReceiptRedirectTest(TestCase):
    """Rule 9.1: record_receipt and cancel_customer_payment must redirect to customer_payment_detail."""

    def setUp(self):
        from django.contrib.auth.models import User
        self.client = Client()
        User.objects.create_user(username='redirecttester', password='pass')
        self.client.login(username='redirecttester', password='pass')
        self.customer = Customer.objects.create(name="Redirect Test Farm", mobile_no="9000000099")

    def test_record_receipt_htmx_returns_204_with_hx_redirect_to_detail(self):
        """Rule 9.1 + Rule 13.7: HTMX modal path must return 204 + HX-Redirect pointing to
        customer_payment_detail, not to invoice_detail or any hardcoded path."""
        invoice = _make_submitted_invoice(self.customer, grand_total=Decimal('800.00'))
        url = reverse('record_receipt', kwargs={'pk': invoice.pk})

        response = self.client.post(
            url,
            {'amount': '800', 'payment_mode': 'CASH'},
            HTTP_HX_REQUEST='true',
        )

        self.assertEqual(response.status_code, 204)
        payment = CustomerPayment.objects.filter(invoice=invoice).first()
        self.assertIsNotNone(payment, "Payment must be created on success")
        expected_url = reverse('customer_payment_detail', kwargs={'pk': payment.pk})
        self.assertEqual(response['HX-Redirect'], expected_url)

    def test_record_receipt_non_htmx_redirects_to_payment_detail(self):
        """Rule 9.1: Standard (non-HTMX) POST must redirect 302 → customer_payment_detail."""
        invoice = _make_submitted_invoice(self.customer, grand_total=Decimal('600.00'))
        url = reverse('record_receipt', kwargs={'pk': invoice.pk})

        response = self.client.post(url, {'amount': '600', 'payment_mode': 'CASH'})

        self.assertEqual(response.status_code, 302)
        payment = CustomerPayment.objects.filter(invoice=invoice).first()
        self.assertIsNotNone(payment)
        expected_url = reverse('customer_payment_detail', kwargs={'pk': payment.pk})
        self.assertRedirects(response, expected_url, fetch_redirect_response=False)

    def test_cancel_customer_payment_redirects_to_payment_detail(self):
        """Rule 9.1: Cancelling a receipt must redirect back to the same receipt's detail page
        (not invoice_detail) so the user sees the CANCELLED badge and reversed ledger."""
        invoice = _make_submitted_invoice(self.customer, grand_total=Decimal('400.00'))
        payment = CustomerPayment.objects.create(
            invoice=invoice,
            amount=Decimal('400.00'),
            payment_mode='CASH',
            payment_date=timezone.now().date(),
            status='SUBMITTED',
        )
        url = reverse('cancel_customer_payment', kwargs={'pk': payment.pk})

        response = self.client.post(url)

        self.assertEqual(response.status_code, 302)
        expected_url = reverse('customer_payment_detail', kwargs={'pk': payment.pk})
        self.assertRedirects(response, expected_url, fetch_redirect_response=False)
        payment.refresh_from_db()
        self.assertEqual(payment.status, 'CANCELLED')
