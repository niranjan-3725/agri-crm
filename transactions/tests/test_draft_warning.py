"""
Tests for Draft Warning UX: verifies the 'This is a DRAFT' inventory impact
banner appears when status == DRAFT and is absent after submission.
"""
from django.test import TestCase, Client
from django.urls import reverse
from master_data.models import Supplier
from transactions.models import PurchaseInvoice
from datetime import date


class DraftWarningBannerTest(TestCase):
    """
    Verifies that the amber 'This is a DRAFT' warning banner appears on the
    purchase detail page for DRAFT invoices, and disappears after submission.
    """

    def setUp(self):
        self.client = Client()
        self.supplier = Supplier.objects.create(name="Draft Test Supplier")
        self.invoice = PurchaseInvoice.objects.create(
            supplier=self.supplier,
            invoice_number="INV-DRAFT-WARN-001",
            date=date.today(),
            total_amount=500,
            status="DRAFT",
        )
        self.detail_url = reverse("purchase_detail", args=[self.invoice.pk])
        self.submit_url = reverse("submit_purchase_invoice", args=[self.invoice.pk])

    def test_draft_warning_visible_on_draft_invoice(self):
        """The amber warning banner must be present for a DRAFT invoice."""
        response = self.client.get(self.detail_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This is a DRAFT")
        self.assertContains(response, "draft-warning-banner")
        self.assertContains(response, "Inventory levels and ledger balances will")

    def test_draft_warning_absent_on_submitted_invoice(self):
        """The amber warning banner must NOT be present once submitted."""
        # Force status to SUBMITTED (bypass submit() side-effects for isolation)
        PurchaseInvoice.objects.filter(pk=self.invoice.pk).update(status="SUBMITTED")
        self.invoice.refresh_from_db()

        response = self.client.get(self.detail_url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "draft-warning-banner")
        self.assertNotContains(response, "This is a DRAFT")

    def test_draft_warning_absent_on_cancelled_invoice(self):
        """The amber warning banner must NOT be present on a CANCELLED invoice."""
        PurchaseInvoice.objects.filter(pk=self.invoice.pk).update(status="CANCELLED")
        self.invoice.refresh_from_db()

        response = self.client.get(self.detail_url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "draft-warning-banner")

    def test_pending_submission_badge_visible_on_draft(self):
        """'Pending Submission' badge should be visible on DRAFT invoices."""
        response = self.client.get(self.detail_url)
        self.assertContains(response, "Pending Submission")

    def test_submit_url_in_context_for_draft(self):
        """Context must expose the correct submit URL for DRAFT invoices."""
        response = self.client.get(self.detail_url)
        self.assertEqual(response.status_code, 200)
        # Context carries the correct submit URL
        self.assertEqual(response.context['submit_url'], self.submit_url)
        # Invoice is DRAFT — actions panel would render Submit
        self.assertEqual(response.context['invoice'].status, 'DRAFT')
        # Edit URL is also available for DRAFT amendments
        expected_edit = f'/purchases/{self.invoice.pk}/edit/'
        self.assertEqual(response.context['edit_url'], expected_edit)
