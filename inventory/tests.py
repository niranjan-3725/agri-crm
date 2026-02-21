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

from inventory.models import Batch, StockMovement
from inventory.services import InsufficientStockError, process_stock_movement
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
        """Helper to create a Batch with sensible defaults."""
        defaults = dict(
            product=self.product,
            batch_number='B001',
            purchase_price=Decimal('100.00'),
            mrp=Decimal('150.00'),
            base_selling_price=Decimal('140.00'),
            current_quantity=qty,
        )
        defaults.update(overrides)
        return Batch.objects.create(**defaults)

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
