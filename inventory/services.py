"""
inventory.services
~~~~~~~~~~~~~~~~~~~

Central service layer for all stock mutations.

EVERY change to stock MUST go through ``process_stock_movement()`` so that:

1. Both the ``StockBin.actual_qty`` (per-warehouse) and
   ``Batch.current_quantity`` (global cache) are updated in the
   **same** database transaction.
2. The cache updates use ``F()`` expressions, making them immune to
   race conditions (no Python-level read-modify-write).
3. DB-level ``CHECK`` constraints on both tables act as the ultimate
   backstop against negative stock.
4. An immutable ``StockMovement`` ledger row is always created.
5. Sprint 9: Balanced GL entries are posted for every movement.
6. Sprint 10: Moving-average valuation is recalculated on purchase
   inward and every StockMovement snapshots the valuation_rate.
"""

from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import F, Sum

from .models import Batch, StockBin, StockMovement, StockReconciliation, Warehouse


class InsufficientStockError(Exception):
    """Raised when a stock movement would push quantity below zero."""
    pass


def get_default_warehouse() -> Warehouse:
    """Return (or create) the default 'Main Warehouse'.

    Every operation that does not yet have an explicit warehouse
    selector should call this to obtain the fallback warehouse.
    """
    wh, _ = Warehouse.objects.get_or_create(
        name='Main Warehouse',
        defaults={'location': 'Default location', 'is_active': True},
    )
    return wh


# ── Sprint 10: Doc types whose inward recalculates the moving average ──
# Only true *purchase* inward changes the MA. Returns and reconciliation
# re-enter stock at the current average, leaving the MA untouched.
PURCHASE_INWARD_TYPES = frozenset({
    'PurchaseInvoice',
    'PurchaseReceipt',
    'PurchaseReturnCancel',
})


def _recalculate_moving_average(product, incoming_qty, incoming_price):
    """Recalculate the product's moving-average price (Sprint 10).

    Formula
    -------
    new_avg = ((old_total_qty × old_avg) + (incoming_qty × incoming_price))
              / (old_total_qty + incoming_qty)

    If old_total_qty == 0, the new average is simply *incoming_price*.

    The ``product`` **must** already be locked via ``select_for_update()``
    before calling this function.  The total qty is calculated from the
    DB **before** the current Batch.current_quantity F()-update has been
    applied, so the caller must query it beforehand.
    """
    # Get the product's total stock BEFORE this inward movement.
    old_total_qty = (
        Batch.objects.filter(product=product)
        .aggregate(total=Sum('current_quantity'))['total']
    ) or 0

    old_avg = product.moving_average_price or Decimal('0')

    if old_total_qty <= 0:
        new_avg = incoming_price
    else:
        old_total_value = Decimal(old_total_qty) * old_avg
        incoming_value = Decimal(incoming_qty) * incoming_price
        new_total_qty = old_total_qty + incoming_qty
        new_avg = (old_total_value + incoming_value) / Decimal(new_total_qty)

    product.moving_average_price = new_avg
    product.save(update_fields=['moving_average_price'])

    return new_avg


def process_stock_movement(
    batch_id: int,
    quantity: int,
    doc_type: str,
    doc_id: int,
    warehouse_id: int | None = None,
) -> StockMovement:
    """Atomically record a stock movement and update both StockBin and Batch.

    Parameters
    ----------
    batch_id : int
        PK of the ``Batch`` to mutate.
    quantity : int
        Change amount.  **Positive** for inward, **negative** for outward.
    doc_type : str
        Source document class name, e.g. ``'PurchaseInvoice'``.
    doc_id : int
        PK of the source document.
    warehouse_id : int | None
        PK of the ``Warehouse``.  If ``None``, the default warehouse is used.

    Returns
    -------
    StockMovement
        The newly created ledger entry.

    Raises
    ------
    InsufficientStockError
        If the update would push stock below zero (on either StockBin
        or Batch level).
    Batch.DoesNotExist
        If ``batch_id`` is invalid.
    """
    if warehouse_id is None:
        warehouse_id = get_default_warehouse().id

    try:
        with transaction.atomic():
            # 1. Verify batch exists and capture for valuation.
            batch = Batch.objects.get(pk=batch_id)
            product = batch.product

            # ── Sprint 10: Determine valuation_rate & recalculate MA ──
            from master_data.models import Product as ProductModel

            is_purchase_inward = (
                quantity > 0 and doc_type in PURCHASE_INWARD_TYPES
            )

            if is_purchase_inward:
                # Lock the product row — prevents concurrent MA corruption.
                product_locked = ProductModel.objects.select_for_update().get(
                    pk=product.pk
                )
                # Recalculate BEFORE the Batch qty updates so we have old totals.
                new_avg = _recalculate_moving_average(
                    product_locked, quantity, batch.purchase_price
                )
                valuation_rate = batch.purchase_price
            else:
                # Outward / non-purchase inward: use current moving average.
                product_locked = ProductModel.objects.select_for_update().get(
                    pk=product.pk
                )
                valuation_rate = product_locked.moving_average_price or batch.purchase_price

            # 2a. Ensure a StockBin row exists for (warehouse, batch).
            stock_bin, _created = StockBin.objects.get_or_create(
                warehouse_id=warehouse_id,
                batch_id=batch_id,
                defaults={'actual_qty': 0},
            )

            # 2b. Atomic F() update on StockBin.actual_qty.
            bin_rows = StockBin.objects.filter(
                warehouse_id=warehouse_id,
                batch_id=batch_id,
            ).update(actual_qty=F('actual_qty') + quantity)

            if bin_rows == 0:
                raise Batch.DoesNotExist(
                    f"StockBin for batch={batch_id}, warehouse={warehouse_id} not found."
                )

            # 3. Keep Batch.current_quantity (global aggregate cache) in sync.
            Batch.objects.filter(pk=batch_id).update(
                current_quantity=F('current_quantity') + quantity
            )

            # 4. Create the immutable ledger entry with valuation snapshot.
            movement = StockMovement.objects.create(
                batch_id=batch_id,
                warehouse_id=warehouse_id,
                quantity=quantity,
                reference_document_type=doc_type,
                reference_document_id=doc_id,
                valuation_rate=valuation_rate,
            )

            # 5. Sprint 9: Post balanced GL entries using the valuation_rate.
            from accounting.services import post_stock_gl
            post_stock_gl(
                doc_type=doc_type,
                doc_id=doc_id,
                quantity=quantity,
                purchase_price=valuation_rate,
            )

            return movement

    except IntegrityError as exc:
        exc_str = str(exc)
        if 'stockbin_non_negative_qty' in exc_str or 'batch_non_negative_stock' in exc_str:
            raise InsufficientStockError(
                f"Insufficient stock in Batch {batch_id} "
                f"(warehouse {warehouse_id}). "
                f"Attempted change: {quantity}."
            ) from exc
        raise


def reconcile_stock(
    batch_id: int,
    new_quantity: int,
    reason: str = 'Count Error',
    notes: str = '',
    warehouse_id: int | None = None,
) -> StockReconciliation:
    """Perform a physical stock reconciliation for a batch.

    Reads the current (true) quantity inside a locked atomic block,
    computes delta = new_quantity - previous_quantity, saves a
    StockReconciliation audit record, and — only when delta != 0 —
    posts a compensating StockMovement ledger entry.
    """
    if new_quantity < 0:
        raise ValueError("new_quantity cannot be negative.")

    if warehouse_id is None:
        warehouse_id = get_default_warehouse().id

    with transaction.atomic():
        # Lock the batch row for global cache consistency.
        batch = Batch.objects.select_for_update().get(pk=batch_id)

        # Read the *warehouse-specific* quantity, not the global Batch cache.
        # Batch.current_quantity is the sum across ALL warehouses; using it as
        # the baseline for a per-warehouse reconciliation produces a wrong delta
        # in any multi-warehouse setup (Bug #1).
        try:
            stock_bin = StockBin.objects.select_for_update().get(
                batch_id=batch_id, warehouse_id=warehouse_id,
            )
            previous_quantity = stock_bin.actual_qty
        except StockBin.DoesNotExist:
            # Warehouse has never held this batch — treat as zero.
            previous_quantity = 0

        delta = new_quantity - previous_quantity

        recon = StockReconciliation.objects.create(
            batch=batch,
            previous_quantity=previous_quantity,
            new_quantity=new_quantity,
            reason=reason,
            notes=notes,
        )

        if delta != 0:
            process_stock_movement(
                batch_id=batch_id,
                quantity=delta,
                doc_type='StockReconciliation',
                doc_id=recon.id,
                warehouse_id=warehouse_id,
            )

    return recon
