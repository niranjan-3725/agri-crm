"""
Sprint 14 — Order Pipeline & Fulfillment Tracking Tests.

Validates:
  1. Quotation, SalesOrder, PurchaseOrder follow the standard state machine.
  2. Orders create ZERO GL or StockMovement entries.
  3. DN submit updates SalesOrderItem.delivered_qty; cancel reverses it.
  4. SalesInvoice submit updates SalesOrderItem.billed_qty; cancel reverses it.
  5. PurchaseReceipt submit updates PurchaseOrderItem.received_qty; cancel reverses it.
  6. PurchaseInvoice submit updates PurchaseOrderItem.billed_qty; cancel reverses it.
  7. Percentage properties (per_delivered, per_billed, per_received) compute correctly.
  8. Full lifecycle: SO → DN → SI → cancel all → trackers return to zero.
"""

from decimal import Decimal
from datetime import date

from django.test import TestCase
from django.core.exceptions import ValidationError

from accounting.models import GLEntry
from inventory.models import Batch, StockBin, StockMovement
from inventory.services import get_default_warehouse
from master_data.models import Category, Customer, Manufacturer, Product, Supplier
from transactions.models import (
    Quotation, QuotationItem,
    SalesOrder, SalesOrderItem,
    PurchaseOrder, PurchaseOrderItem,
    DeliveryNote, DeliveryNoteItem,
    PurchaseReceipt, PurchaseReceiptItem,
    SalesInvoice, SalesItem,
    PurchaseInvoice, PurchaseItem,
)


def _seed(batch):
    wh = get_default_warehouse()
    StockBin.objects.get_or_create(
        warehouse=wh, batch=batch,
        defaults={'actual_qty': batch.current_quantity},
    )


# ═══════════════════════════════════════════════════════════════════════
# Test 1: Order State Machine & Zero Ledger Impact
# ═══════════════════════════════════════════════════════════════════════

class QuotationStateMachineTests(TestCase):

    def setUp(self):
        self.customer = Customer.objects.create(name='QTN Cust')

    def test_submit_and_cancel(self):
        q = Quotation.objects.create(customer=self.customer, grand_total=Decimal('500.00'))
        q.submit()
        self.assertEqual(q.status, 'SUBMITTED')
        q.cancel()
        self.assertEqual(q.status, 'CANCELLED')

    def test_delete_blocked_after_submit(self):
        q = Quotation.objects.create(customer=self.customer, grand_total=Decimal('500.00'))
        q.submit()
        with self.assertRaises(ValidationError):
            q.delete()

    def test_zero_gl_entries(self):
        q = Quotation.objects.create(customer=self.customer, grand_total=Decimal('1000.00'))
        q.submit()
        self.assertEqual(GLEntry.objects.count(), 0)

    def test_zero_stock_movements(self):
        q = Quotation.objects.create(customer=self.customer, grand_total=Decimal('1000.00'))
        q.submit()
        self.assertEqual(StockMovement.objects.count(), 0)


class SalesOrderStateMachineTests(TestCase):

    def setUp(self):
        self.customer = Customer.objects.create(name='SO Cust')

    def test_submit_and_cancel(self):
        so = SalesOrder.objects.create(customer=self.customer, grand_total=Decimal('1000.00'))
        so.submit()
        self.assertEqual(so.status, 'SUBMITTED')
        so.cancel()
        self.assertEqual(so.status, 'CANCELLED')

    def test_double_submit_raises(self):
        so = SalesOrder.objects.create(customer=self.customer, grand_total=Decimal('100.00'))
        so.submit()
        with self.assertRaises(ValidationError):
            so.submit()

    def test_zero_gl_entries_on_submit(self):
        """CRITICAL: Sales Order must create ZERO GL entries."""
        so = SalesOrder.objects.create(customer=self.customer, grand_total=Decimal('1000.00'))
        so.submit()
        self.assertEqual(GLEntry.objects.count(), 0)

    def test_zero_stock_movements_on_submit(self):
        """CRITICAL: Sales Order must create ZERO stock movements."""
        so = SalesOrder.objects.create(customer=self.customer, grand_total=Decimal('1000.00'))
        so.submit()
        self.assertEqual(StockMovement.objects.count(), 0)


class PurchaseOrderStateMachineTests(TestCase):

    def setUp(self):
        self.supplier = Supplier.objects.create(name='PO Supplier')

    def test_submit_and_cancel(self):
        po = PurchaseOrder.objects.create(supplier=self.supplier, grand_total=Decimal('2000.00'))
        po.submit()
        self.assertEqual(po.status, 'SUBMITTED')
        po.cancel()
        self.assertEqual(po.status, 'CANCELLED')

    def test_zero_gl_entries_on_submit(self):
        """CRITICAL: Purchase Order must create ZERO GL entries."""
        po = PurchaseOrder.objects.create(supplier=self.supplier, grand_total=Decimal('2000.00'))
        po.submit()
        self.assertEqual(GLEntry.objects.count(), 0)

    def test_zero_stock_movements_on_submit(self):
        """CRITICAL: Purchase Order must create ZERO stock movements."""
        po = PurchaseOrder.objects.create(supplier=self.supplier, grand_total=Decimal('2000.00'))
        po.submit()
        self.assertEqual(StockMovement.objects.count(), 0)


# ═══════════════════════════════════════════════════════════════════════
# Test 2: Sales Order → Delivery Note → delivered_qty Tracking
# ═══════════════════════════════════════════════════════════════════════

class SalesOrderDeliveryTrackingTests(TestCase):
    """Test that DN submit/cancel accurately updates SO delivered_qty."""

    def setUp(self):
        self.cat = Category.objects.create(name='S14 Cat', cgst_rate=9, sgst_rate=9)
        self.mfr = Manufacturer.objects.create(name='S14 Mfr')
        self.product = Product.objects.create(
            name='S14 Product', category=self.cat,
            unit_type='Kg', manufacturer=self.mfr,
        )
        self.customer = Customer.objects.create(name='S14 DN Cust')
        self.batch = Batch.objects.create(
            product=self.product, batch_number='S14DN_B001',
            current_quantity=100, purchase_price=Decimal('80.00'),
            base_selling_price=Decimal('120.00'), mrp=Decimal('150.00'),
        )
        _seed(self.batch)

        # Create and submit a Sales Order
        self.so = SalesOrder.objects.create(
            customer=self.customer, grand_total=Decimal('1200.00'),
        )
        self.soi = SalesOrderItem.objects.create(
            sales_order=self.so, batch=self.batch,
            quantity=20, unit_price=Decimal('60.00'),
            amount=Decimal('1200.00'),
        )
        self.so.submit()

    def test_dn_submit_updates_delivered_qty(self):
        """Submitting a DN linked to SO updates delivered_qty on the SOI."""
        dn = DeliveryNote.objects.create(
            customer=self.customer, date=date.today(), sales_order=self.so,
        )
        DeliveryNoteItem.objects.create(
            delivery_note=dn, batch=self.batch, quantity=10,
            sales_order_item=self.soi,
        )
        dn.submit()

        self.soi.refresh_from_db()
        self.assertEqual(self.soi.delivered_qty, 10)

    def test_dn_cancel_reverses_delivered_qty(self):
        """Cancelling a DN linked to SO reverses delivered_qty on the SOI."""
        dn = DeliveryNote.objects.create(
            customer=self.customer, date=date.today(), sales_order=self.so,
        )
        DeliveryNoteItem.objects.create(
            delivery_note=dn, batch=self.batch, quantity=10,
            sales_order_item=self.soi,
        )
        dn.submit()
        dn.cancel()

        self.soi.refresh_from_db()
        self.assertEqual(self.soi.delivered_qty, 0)

    def test_partial_delivery_percentage(self):
        """per_delivered property reflects partial delivery accurately."""
        dn = DeliveryNote.objects.create(
            customer=self.customer, date=date.today(), sales_order=self.so,
        )
        DeliveryNoteItem.objects.create(
            delivery_note=dn, batch=self.batch, quantity=5,
            sales_order_item=self.soi,
        )
        dn.submit()

        self.so.refresh_from_db()
        self.assertEqual(self.so.per_delivered, 25.0)  # 5/20 = 25%

    def test_full_delivery_percentage(self):
        """per_delivered is 100% when all qty delivered."""
        dn = DeliveryNote.objects.create(
            customer=self.customer, date=date.today(), sales_order=self.so,
        )
        DeliveryNoteItem.objects.create(
            delivery_note=dn, batch=self.batch, quantity=20,
            sales_order_item=self.soi,
        )
        dn.submit()

        self.so.refresh_from_db()
        self.assertEqual(self.so.per_delivered, 100.0)

    def test_dn_without_so_link_works_normally(self):
        """Submitting a standalone DN (no SO) still works with no errors."""
        dn = DeliveryNote.objects.create(
            customer=self.customer, date=date.today(),
        )
        DeliveryNoteItem.objects.create(
            delivery_note=dn, batch=self.batch, quantity=5,
        )
        dn.submit()

        self.batch.refresh_from_db()
        self.assertEqual(self.batch.current_quantity, 95)


# ═══════════════════════════════════════════════════════════════════════
# Test 3: Sales Order → Sales Invoice → billed_qty Tracking
# ═══════════════════════════════════════════════════════════════════════

class SalesOrderBillingTrackingTests(TestCase):
    """Test that SI submit/cancel accurately updates SO billed_qty."""

    def setUp(self):
        self.cat = Category.objects.create(name='S14B Cat', cgst_rate=9, sgst_rate=9)
        self.mfr = Manufacturer.objects.create(name='S14B Mfr')
        self.product = Product.objects.create(
            name='S14B Product', category=self.cat,
            unit_type='Kg', manufacturer=self.mfr,
        )
        self.customer = Customer.objects.create(name='S14 SI Cust')
        self.batch = Batch.objects.create(
            product=self.product, batch_number='S14SI_B001',
            current_quantity=100, purchase_price=Decimal('80.00'),
            base_selling_price=Decimal('120.00'), mrp=Decimal('150.00'),
        )
        _seed(self.batch)

        self.so = SalesOrder.objects.create(
            customer=self.customer, grand_total=Decimal('2360.00'),
        )
        self.soi = SalesOrderItem.objects.create(
            sales_order=self.so, batch=self.batch,
            quantity=20, unit_price=Decimal('118.00'),
            amount=Decimal('2360.00'),
        )
        self.so.submit()

    def test_si_submit_updates_billed_qty(self):
        """Submitting a SI linked to SO updates billed_qty on the SOI."""
        si = SalesInvoice.objects.create(
            customer=self.customer, sales_order=self.so,
            total_taxable=Decimal('1000.00'),
            total_cgst=Decimal('90.00'), total_sgst=Decimal('90.00'),
            grand_total=Decimal('1180.00'),
        )
        SalesItem.objects.create(
            invoice=si, batch=self.batch, quantity=10,
            unit_price=Decimal('118.00'), tax_rate=Decimal('18.00'),
            tax_amount=Decimal('180.00'), total_amount=Decimal('1180.00'),
            sales_order_item=self.soi,
        )
        si.submit()

        self.soi.refresh_from_db()
        self.assertEqual(self.soi.billed_qty, 10)

    def test_si_submit_also_updates_delivered_qty_via_auto_dn(self):
        """Auto-DN created by SI submit also updates SO delivered_qty."""
        si = SalesInvoice.objects.create(
            customer=self.customer, sales_order=self.so,
            total_taxable=Decimal('1000.00'),
            total_cgst=Decimal('90.00'), total_sgst=Decimal('90.00'),
            grand_total=Decimal('1180.00'),
        )
        SalesItem.objects.create(
            invoice=si, batch=self.batch, quantity=10,
            unit_price=Decimal('118.00'), tax_rate=Decimal('18.00'),
            tax_amount=Decimal('180.00'), total_amount=Decimal('1180.00'),
            sales_order_item=self.soi,
        )
        si.submit()

        self.soi.refresh_from_db()
        self.assertEqual(self.soi.delivered_qty, 10)
        self.assertEqual(self.soi.billed_qty, 10)

    def test_si_cancel_reverses_billed_and_delivered_qty(self):
        """Cancelling SI reverses both billed_qty and delivered_qty."""
        si = SalesInvoice.objects.create(
            customer=self.customer, sales_order=self.so,
            total_taxable=Decimal('1000.00'),
            total_cgst=Decimal('90.00'), total_sgst=Decimal('90.00'),
            grand_total=Decimal('1180.00'),
        )
        SalesItem.objects.create(
            invoice=si, batch=self.batch, quantity=10,
            unit_price=Decimal('118.00'), tax_rate=Decimal('18.00'),
            tax_amount=Decimal('180.00'), total_amount=Decimal('1180.00'),
            sales_order_item=self.soi,
        )
        si.submit()
        si.cancel()

        self.soi.refresh_from_db()
        self.assertEqual(self.soi.billed_qty, 0)
        self.assertEqual(self.soi.delivered_qty, 0)

    def test_per_billed_property(self):
        """per_billed reflects accurate billing percentage."""
        si = SalesInvoice.objects.create(
            customer=self.customer, sales_order=self.so,
            total_taxable=Decimal('500.00'),
            total_cgst=Decimal('45.00'), total_sgst=Decimal('45.00'),
            grand_total=Decimal('590.00'),
        )
        SalesItem.objects.create(
            invoice=si, batch=self.batch, quantity=5,
            unit_price=Decimal('118.00'), tax_rate=Decimal('18.00'),
            tax_amount=Decimal('90.00'), total_amount=Decimal('590.00'),
            sales_order_item=self.soi,
        )
        si.submit()

        self.so.refresh_from_db()
        self.assertEqual(self.so.per_billed, 25.0)  # 5/20 = 25%


# ═══════════════════════════════════════════════════════════════════════
# Test 4: Purchase Order → Purchase Receipt → received_qty Tracking
# ═══════════════════════════════════════════════════════════════════════

class PurchaseOrderReceiptTrackingTests(TestCase):
    """Test that PR submit/cancel accurately updates PO received_qty."""

    def setUp(self):
        self.cat = Category.objects.create(name='S14PR Cat', cgst_rate=9, sgst_rate=9)
        self.mfr = Manufacturer.objects.create(name='S14PR Mfr')
        self.product = Product.objects.create(
            name='S14PR Product', category=self.cat,
            unit_type='Kg', manufacturer=self.mfr,
        )
        self.supplier = Supplier.objects.create(name='S14PR Supplier')
        self.batch = Batch.objects.create(
            product=self.product, batch_number='S14PR_B001',
            current_quantity=0, purchase_price=Decimal('100.00'),
            base_selling_price=Decimal('150.00'), mrp=Decimal('200.00'),
        )
        _seed(self.batch)

        self.po = PurchaseOrder.objects.create(
            supplier=self.supplier, grand_total=Decimal('5000.00'),
        )
        self.poi = PurchaseOrderItem.objects.create(
            purchase_order=self.po, batch=self.batch,
            quantity=50, unit_price=Decimal('100.00'),
            amount=Decimal('5000.00'),
        )
        self.po.submit()

    def test_pr_submit_updates_received_qty(self):
        pr = PurchaseReceipt.objects.create(
            supplier=self.supplier, date=date.today(), purchase_order=self.po,
        )
        PurchaseReceiptItem.objects.create(
            receipt=pr, batch=self.batch, quantity=30,
            purchase_order_item=self.poi,
        )
        pr.submit()

        self.poi.refresh_from_db()
        self.assertEqual(self.poi.received_qty, 30)

    def test_pr_cancel_reverses_received_qty(self):
        pr = PurchaseReceipt.objects.create(
            supplier=self.supplier, date=date.today(), purchase_order=self.po,
        )
        PurchaseReceiptItem.objects.create(
            receipt=pr, batch=self.batch, quantity=30,
            purchase_order_item=self.poi,
        )
        pr.submit()
        pr.cancel()

        self.poi.refresh_from_db()
        self.assertEqual(self.poi.received_qty, 0)

    def test_per_received_property(self):
        pr = PurchaseReceipt.objects.create(
            supplier=self.supplier, date=date.today(), purchase_order=self.po,
        )
        PurchaseReceiptItem.objects.create(
            receipt=pr, batch=self.batch, quantity=25,
            purchase_order_item=self.poi,
        )
        pr.submit()

        self.po.refresh_from_db()
        self.assertEqual(self.po.per_received, 50.0)  # 25/50 = 50%


# ═══════════════════════════════════════════════════════════════════════
# Test 5: Purchase Order → Purchase Invoice → billed_qty Tracking
# ═══════════════════════════════════════════════════════════════════════

class PurchaseOrderBillingTrackingTests(TestCase):
    """Test that PI submit/cancel accurately updates PO billed_qty."""

    def setUp(self):
        self.cat = Category.objects.create(name='S14PIB Cat', cgst_rate=9, sgst_rate=9)
        self.mfr = Manufacturer.objects.create(name='S14PIB Mfr')
        self.product = Product.objects.create(
            name='S14PIB Product', category=self.cat,
            unit_type='Kg', manufacturer=self.mfr,
        )
        self.supplier = Supplier.objects.create(name='S14PIB Supplier')
        self.batch = Batch.objects.create(
            product=self.product, batch_number='S14PIB_B001',
            current_quantity=0, purchase_price=Decimal('100.00'),
            base_selling_price=Decimal('150.00'), mrp=Decimal('200.00'),
        )
        _seed(self.batch)

        self.po = PurchaseOrder.objects.create(
            supplier=self.supplier, grand_total=Decimal('5000.00'),
        )
        self.poi = PurchaseOrderItem.objects.create(
            purchase_order=self.po, batch=self.batch,
            quantity=50, unit_price=Decimal('100.00'),
            amount=Decimal('5000.00'),
        )
        self.po.submit()

    def test_pi_submit_updates_billed_qty(self):
        pi = PurchaseInvoice.objects.create(
            supplier=self.supplier, invoice_number='S14PIB-001',
            date=date.today(), total_amount=Decimal('2000.00'),
            purchase_order=self.po,
        )
        PurchaseItem.objects.create(
            invoice=pi, batch=self.batch, quantity=20,
            basic_rate=Decimal('100.00'), tax_amount=Decimal('0.00'),
            total_amount=Decimal('2000.00'),
            purchase_order_item=self.poi,
        )
        pi.submit()

        self.poi.refresh_from_db()
        self.assertEqual(self.poi.billed_qty, 20)

    def test_pi_submit_also_updates_received_qty_via_auto_pr(self):
        """Auto-PR created by PI submit also updates PO received_qty."""
        pi = PurchaseInvoice.objects.create(
            supplier=self.supplier, invoice_number='S14PIB-002',
            date=date.today(), total_amount=Decimal('2000.00'),
            purchase_order=self.po,
        )
        PurchaseItem.objects.create(
            invoice=pi, batch=self.batch, quantity=20,
            basic_rate=Decimal('100.00'), tax_amount=Decimal('0.00'),
            total_amount=Decimal('2000.00'),
            purchase_order_item=self.poi,
        )
        pi.submit()

        self.poi.refresh_from_db()
        self.assertEqual(self.poi.received_qty, 20)
        self.assertEqual(self.poi.billed_qty, 20)

    def test_pi_cancel_reverses_billed_and_received_qty(self):
        pi = PurchaseInvoice.objects.create(
            supplier=self.supplier, invoice_number='S14PIB-003',
            date=date.today(), total_amount=Decimal('2000.00'),
            purchase_order=self.po,
        )
        PurchaseItem.objects.create(
            invoice=pi, batch=self.batch, quantity=20,
            basic_rate=Decimal('100.00'), tax_amount=Decimal('0.00'),
            total_amount=Decimal('2000.00'),
            purchase_order_item=self.poi,
        )
        pi.submit()
        pi.cancel()

        self.poi.refresh_from_db()
        self.assertEqual(self.poi.billed_qty, 0)
        self.assertEqual(self.poi.received_qty, 0)

    def test_per_billed_property(self):
        pi = PurchaseInvoice.objects.create(
            supplier=self.supplier, invoice_number='S14PIB-004',
            date=date.today(), total_amount=Decimal('1000.00'),
            purchase_order=self.po,
        )
        PurchaseItem.objects.create(
            invoice=pi, batch=self.batch, quantity=10,
            basic_rate=Decimal('100.00'), tax_amount=Decimal('0.00'),
            total_amount=Decimal('1000.00'),
            purchase_order_item=self.poi,
        )
        pi.submit()

        self.po.refresh_from_db()
        self.assertEqual(self.po.per_billed, 20.0)  # 10/50 = 20%


# ═══════════════════════════════════════════════════════════════════════
# Test 6: Quotation → Sales Order Linkage
# ═══════════════════════════════════════════════════════════════════════

class QuotationToSalesOrderTests(TestCase):

    def setUp(self):
        self.cat = Category.objects.create(name='Q2SO Cat', cgst_rate=9, sgst_rate=9)
        self.mfr = Manufacturer.objects.create(name='Q2SO Mfr')
        self.product = Product.objects.create(
            name='Q2SO Product', category=self.cat,
            unit_type='Kg', manufacturer=self.mfr,
        )
        self.customer = Customer.objects.create(name='Q2SO Cust')
        self.batch = Batch.objects.create(
            product=self.product, batch_number='Q2SO_B001',
            current_quantity=50, purchase_price=Decimal('80.00'),
            base_selling_price=Decimal('120.00'), mrp=Decimal('150.00'),
        )

    def test_quotation_links_to_sales_order(self):
        q = Quotation.objects.create(customer=self.customer, grand_total=Decimal('600.00'))
        QuotationItem.objects.create(
            quotation=q, batch=self.batch, quantity=5,
            unit_price=Decimal('120.00'), amount=Decimal('600.00'),
        )
        q.submit()

        so = SalesOrder.objects.create(
            customer=self.customer, grand_total=Decimal('600.00'),
            quotation=q,
        )
        SalesOrderItem.objects.create(
            sales_order=so, batch=self.batch, quantity=5,
            unit_price=Decimal('120.00'), amount=Decimal('600.00'),
        )
        so.submit()

        self.assertEqual(so.quotation, q)
        self.assertEqual(q.sales_orders.first(), so)


# ═══════════════════════════════════════════════════════════════════════
# Test 7: Full Sales Lifecycle — SO → DN → SI → Cancel All
# ═══════════════════════════════════════════════════════════════════════

class FullSalesLifecycleTests(TestCase):
    """End-to-end test: SO → DN → SI → cancel → all trackers zero."""

    def setUp(self):
        self.cat = Category.objects.create(name='S14Full Cat', cgst_rate=9, sgst_rate=9)
        self.mfr = Manufacturer.objects.create(name='S14Full Mfr')
        self.product = Product.objects.create(
            name='S14Full Product', category=self.cat,
            unit_type='Kg', manufacturer=self.mfr,
        )
        self.customer = Customer.objects.create(name='S14Full Cust')
        self.batch = Batch.objects.create(
            product=self.product, batch_number='S14FULL_B001',
            current_quantity=100, purchase_price=Decimal('80.00'),
            base_selling_price=Decimal('120.00'), mrp=Decimal('150.00'),
        )
        _seed(self.batch)

    def test_full_lifecycle_trackers_and_gl(self):
        """SO → SI (auto-DN) → cancel SI: all trackers return to zero,
        stock is restored, and GL is balanced."""
        from django.db.models import Sum

        # 1. Create Sales Order
        so = SalesOrder.objects.create(
            customer=self.customer, grand_total=Decimal('2360.00'),
        )
        soi = SalesOrderItem.objects.create(
            sales_order=so, batch=self.batch, quantity=20,
            unit_price=Decimal('118.00'), amount=Decimal('2360.00'),
        )
        so.submit()

        # 2. Create and submit Sales Invoice (auto-creates DN)
        si = SalesInvoice.objects.create(
            customer=self.customer, sales_order=so,
            total_taxable=Decimal('2000.00'),
            total_cgst=Decimal('180.00'), total_sgst=Decimal('180.00'),
            grand_total=Decimal('2360.00'),
        )
        SalesItem.objects.create(
            invoice=si, batch=self.batch, quantity=20,
            unit_price=Decimal('118.00'), tax_rate=Decimal('18.00'),
            tax_amount=Decimal('360.00'), total_amount=Decimal('2360.00'),
            sales_order_item=soi,
        )
        si.submit()

        # Verify: 100% fulfilled
        soi.refresh_from_db()
        self.assertEqual(soi.delivered_qty, 20)
        self.assertEqual(soi.billed_qty, 20)
        self.assertEqual(so.per_delivered, 100.0)
        self.assertEqual(so.per_billed, 100.0)

        # Stock deducted
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.current_quantity, 80)

        # 3. Cancel the Invoice (cascades to DN cancel)
        si.cancel()

        # Verify: trackers back to zero
        soi.refresh_from_db()
        self.assertEqual(soi.delivered_qty, 0)
        self.assertEqual(soi.billed_qty, 0)

        # Stock restored
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.current_quantity, 100)

        # GL balanced (DN + DN cancel + SI + SI cancel)
        totals = GLEntry.objects.aggregate(
            total_debit=Sum('debit'), total_credit=Sum('credit'),
        )
        # Either both None (all deleted) or equal
        if totals['total_debit'] is not None:
            self.assertEqual(totals['total_debit'], totals['total_credit'])
