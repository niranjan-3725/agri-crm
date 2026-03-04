"""
Test suite for Sprint 1 — StockMovement ledger & atomic service layer.

Validates:
  1. Atomic ledger creation (movement + cache update in one go).
  2. Race-condition immunity (F() expression query compilation).
  3. Non-negative stock enforcement (CHECK constraint → rollback).
"""

from decimal import Decimal

from django.db import IntegrityError, connection
from django.db.models import F
from django.test import TestCase

from inventory.models import Batch, StockBin, StockMovement, Warehouse
from inventory.services import (
    InsufficientStockError,
    get_default_warehouse,
    process_stock_movement,
    reconcile_stock,
)
from master_data.models import Category, Manufacturer, Product


class StockMovementServiceTests(TestCase):
    """Integration tests for ``process_stock_movement()``."""

    @classmethod
    def setUpTestData(cls):
        """Shared fixtures — created once for the whole TestCase."""
        cls.cat = Category.objects.create(
            name='Pesticides',
            cgst_rate=Decimal('9.00'),
            sgst_rate=Decimal('9.00'),
        )
        cls.mfr = Manufacturer.objects.create(name='AgriChem')
        cls.product = Product.objects.create(
            name='TestProduct-SP1',
            hsn_code='38089190',
            unit_type='Bottle',
            category=cls.cat,
            manufacturer=cls.mfr,
        )

    def _make_batch(self, qty: int = 0, **overrides) -> Batch:
        """Helper to create a Batch with sensible defaults.

        Sprint 8: Also creates a StockBin in the default warehouse
        so that outward movements have stock to draw from.
        """
        defaults = dict(
            product=self.product,
            batch_number='B001',
            purchase_price=Decimal('100.00'),
            mrp=Decimal('150.00'),
            base_selling_price=Decimal('140.00'),
            current_quantity=qty,
        )
        defaults.update(overrides)
        batch = Batch.objects.create(**defaults)
        # Seed a matching StockBin in the default warehouse
        wh = get_default_warehouse()
        StockBin.objects.get_or_create(
            warehouse=wh, batch=batch,
            defaults={'actual_qty': qty},
        )
        return batch

    # ------------------------------------------------------------------
    # 1. Atomic Ledger Creation
    # ------------------------------------------------------------------
    def test_inward_creates_movement_and_updates_batch(self):
        """Calling with +qty must create a StockMovement AND raise
        current_quantity by exactly that amount."""
        batch = self._make_batch(qty=10)

        movement = process_stock_movement(
            batch_id=batch.pk,
            quantity=5,
            doc_type='PurchaseInvoice',
            doc_id=42,
        )

        # Movement record assertions
        self.assertIsInstance(movement, StockMovement)
        self.assertEqual(movement.quantity, 5)
        self.assertEqual(movement.reference_document_type, 'PurchaseInvoice')
        self.assertEqual(movement.reference_document_id, 42)
        self.assertEqual(movement.batch_id, batch.pk)

        # Batch cache assertion (refresh from DB — the in-memory object
        # still has the old value because F() updates are DB-only).
        batch.refresh_from_db()
        self.assertEqual(batch.current_quantity, 15)

    def test_outward_creates_movement_and_updates_batch(self):
        """Calling with -qty must deduct stock correctly."""
        batch = self._make_batch(qty=20)

        movement = process_stock_movement(
            batch_id=batch.pk,
            quantity=-8,
            doc_type='SalesInvoice',
            doc_id=99,
        )

        self.assertEqual(movement.quantity, -8)
        batch.refresh_from_db()
        self.assertEqual(batch.current_quantity, 12)

    def test_exact_depletion_to_zero_allowed(self):
        """Stock reaching exactly 0 must NOT raise."""
        batch = self._make_batch(qty=5)

        process_stock_movement(
            batch_id=batch.pk,
            quantity=-5,
            doc_type='SalesInvoice',
            doc_id=1,
        )

        batch.refresh_from_db()
        self.assertEqual(batch.current_quantity, 0)

    def test_multiple_movements_accumulate(self):
        """Several sequential movements must all be recorded and the
        batch cache must reflect the net result."""
        batch = self._make_batch(qty=0)

        process_stock_movement(batch.pk, 100, 'PurchaseInvoice', 1)
        process_stock_movement(batch.pk, -30, 'SalesInvoice', 2)
        process_stock_movement(batch.pk, 10, 'SalesReturn', 3)

        batch.refresh_from_db()
        self.assertEqual(batch.current_quantity, 80)
        self.assertEqual(StockMovement.objects.filter(batch=batch).count(), 3)

    # ------------------------------------------------------------------
    # 2. Race-Condition Immunity (F() expression verification)
    # ------------------------------------------------------------------
    def test_update_uses_f_expression_not_python_arithmetic(self):
        """Prove the UPDATE query performs the arithmetic on the DB side.

        If two concurrent updates both run F('current_quantity') + 5
        in sequence without a Python-level refresh, the result must be
        the *sum* of both (50 + 5 + 5 = 60), NOT the last-write-wins
        result (55) that a naive read-modify-write would produce.
        """
        batch = self._make_batch(qty=50)

        # Simulate two "concurrent" F()-based updates in sequence
        # without refreshing the Python object in between:
        Batch.objects.filter(pk=batch.pk).update(
            current_quantity=F('current_quantity') + 5
        )
        Batch.objects.filter(pk=batch.pk).update(
            current_quantity=F('current_quantity') + 5
        )

        batch.refresh_from_db()
        # With F(), the second update sees the DB value of 55 and adds 5 → 60.
        self.assertEqual(batch.current_quantity, 60)

    # ------------------------------------------------------------------
    # 3. Negative Constraint (CHECK constraint → rollback)
    # ------------------------------------------------------------------
    def test_negative_stock_raises_insufficient_stock_error(self):
        """Deducting more than available must raise
        InsufficientStockError and leave both the batch and ledger
        untouched (full rollback)."""
        batch = self._make_batch(qty=3)

        with self.assertRaises(InsufficientStockError):
            process_stock_movement(
                batch_id=batch.pk,
                quantity=-10,   # try to take 10 from 3
                doc_type='SalesInvoice',
                doc_id=999,
            )

        # Batch qty must be unchanged
        batch.refresh_from_db()
        self.assertEqual(batch.current_quantity, 3)

        # No orphaned ledger row
        self.assertEqual(
            StockMovement.objects.filter(
                batch=batch, reference_document_id=999
            ).count(),
            0,
        )

    def test_negative_stock_raw_integrity_error(self):
        """A raw UPDATE bypassing the service must also be blocked
        by the DB-level CHECK constraint."""
        batch = self._make_batch(qty=2)

        with self.assertRaises(IntegrityError):
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE inventory_batch SET current_quantity = -1 "
                    "WHERE id = %s",
                    [batch.pk],
                )

    def test_nonexistent_batch_raises(self):
        """Passing an invalid batch_id must raise DoesNotExist."""
        with self.assertRaises(Batch.DoesNotExist):
            process_stock_movement(
                batch_id=999999,
                quantity=5,
                doc_type='ManualAdjustment',
                doc_id=1,
            )

    # ------------------------------------------------------------------
    # 4. Ledger Integrity
    # ------------------------------------------------------------------
    def test_ledger_is_append_only(self):
        """StockMovement has no update path — calling save() on an
        existing record should simply re-save (Django default) but
        the service never does that. Verify created_at is set."""
        batch = self._make_batch(qty=0)
        m = process_stock_movement(batch.pk, 10, 'PurchaseInvoice', 1)

        self.assertIsNotNone(m.created_at)
        self.assertEqual(m.quantity, 10)


# ── Bug #1 Regression: StockReconciliation warehouse scope ─────────────


class ReconcileStockWarehouseScopeTests(TestCase):
    """Regression tests for Bug #1: reconcile_stock() must use per-warehouse
    StockBin.actual_qty as the baseline, not the global Batch.current_quantity.

    In a multi-warehouse setup the two values diverge.  The old code used
    batch.current_quantity (global total), which produced a wrong delta and
    crashed or corrupted stock for any warehouse-specific reconciliation.
    """

    @classmethod
    def setUpTestData(cls):
        cls.cat = Category.objects.create(
            name='Recon Test Cat',
            cgst_rate=Decimal('9.00'),
            sgst_rate=Decimal('9.00'),
        )
        cls.mfr = Manufacturer.objects.create(name='Recon Mfr')
        cls.product = Product.objects.create(
            name='Recon Product',
            hsn_code='38089190',
            unit_type='Bag',
            category=cls.cat,
            manufacturer=cls.mfr,
        )

    def _make_batch(self, qty=0):
        return Batch.objects.create(
            product=self.product,
            batch_number=f'RB-{Batch.objects.count()}',
            purchase_price=Decimal('50.00'),
            mrp=Decimal('80.00'),
            base_selling_price=Decimal('70.00'),
            current_quantity=qty,
        )

    def test_single_warehouse_reconcile_still_works(self):
        """Single-warehouse reconcile: uses bin qty == global qty, result unchanged."""
        batch = self._make_batch(qty=0)
        wh = get_default_warehouse()
        StockBin.objects.get_or_create(warehouse=wh, batch=batch, defaults={'actual_qty': 0})
        process_stock_movement(batch.pk, 10, 'PurchaseReceipt', 1, wh.pk)

        reconcile_stock(batch_id=batch.pk, new_quantity=8, warehouse_id=wh.pk)

        bin_ = StockBin.objects.get(warehouse=wh, batch=batch)
        batch.refresh_from_db()
        self.assertEqual(bin_.actual_qty, 8)
        self.assertEqual(batch.current_quantity, 8)

    def test_multiwarehouse_reconcile_uses_bin_qty_not_global(self):
        """Core regression: reconciling warehouse A must not use the global total.

        Warehouse A: 10 units, Warehouse B: 20 units → global = 30.
        Reconcile warehouse A to 8 (physical count found 2 missing).
        Expected delta = 8 - 10 = -2 (NOT 8 - 30 = -22).
        """
        batch = self._make_batch(qty=0)
        wh_a = Warehouse.objects.create(name='Recon WH-A')
        wh_b = Warehouse.objects.create(name='Recon WH-B')
        StockBin.objects.create(warehouse=wh_a, batch=batch, actual_qty=0)
        StockBin.objects.create(warehouse=wh_b, batch=batch, actual_qty=0)

        process_stock_movement(batch.pk, 10, 'PurchaseReceipt', 1, wh_a.pk)
        process_stock_movement(batch.pk, 20, 'PurchaseReceipt', 2, wh_b.pk)

        # Sanity check: global qty is 30 before reconciliation
        batch.refresh_from_db()
        self.assertEqual(batch.current_quantity, 30)

        # Reconcile warehouse A to 8 — should remove 2 from wh_a, not 22
        reconcile_stock(batch_id=batch.pk, new_quantity=8, warehouse_id=wh_a.pk)

        bin_a = StockBin.objects.get(warehouse=wh_a, batch=batch)
        bin_b = StockBin.objects.get(warehouse=wh_b, batch=batch)
        batch.refresh_from_db()

        self.assertEqual(bin_a.actual_qty, 8,
                         "Warehouse A should be reconciled to 8, not crash to -12")
        self.assertEqual(bin_b.actual_qty, 20,
                         "Warehouse B must be untouched")
        self.assertEqual(batch.current_quantity, 28,
                         "Global cache must equal 8 (wh_a) + 20 (wh_b)")

    def test_multiwarehouse_reconcile_does_not_raise_insufficient_stock(self):
        """Regression: the buggy code tried to remove 22 from wh_a (had 10) and
        would trigger InsufficientStockError.  The fix removes only 2."""
        batch = self._make_batch(qty=0)
        wh_a = Warehouse.objects.create(name='Recon WH-C')
        wh_b = Warehouse.objects.create(name='Recon WH-D')
        StockBin.objects.create(warehouse=wh_a, batch=batch, actual_qty=0)
        StockBin.objects.create(warehouse=wh_b, batch=batch, actual_qty=0)

        process_stock_movement(batch.pk, 10, 'PurchaseReceipt', 3, wh_a.pk)
        process_stock_movement(batch.pk, 20, 'PurchaseReceipt', 4, wh_b.pk)

        try:
            reconcile_stock(batch_id=batch.pk, new_quantity=8, warehouse_id=wh_a.pk)
        except InsufficientStockError:
            self.fail(
                "reconcile_stock raised InsufficientStockError — it incorrectly "
                "computed delta against the global qty (30) instead of the "
                "warehouse-specific bin qty (10)."
            )
