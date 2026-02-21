"""
inventory.services
~~~~~~~~~~~~~~~~~~~

Central service layer for all stock mutations.

EVERY change to ``Batch.current_quantity`` MUST go through
``process_stock_movement()`` so that:

1. The ``StockMovement`` ledger row and the ``Batch`` cache update
   happen inside the **same** database transaction.
2. The cache update uses an ``F()`` expression, making it immune to
   race conditions (no Python-level read-modify-write).
3. The MySQL ``CHECK`` constraint on ``current_quantity >= 0`` acts
   as the ultimate backstop against negative stock.
"""

from django.db import IntegrityError, transaction
from django.db.models import F

from .models import Batch, StockMovement


class InsufficientStockError(Exception):
    """Raised when a stock movement would push quantity below zero."""
    pass


def process_stock_movement(
    batch_id: int,
    quantity: int,
    doc_type: str,
    doc_id: int,
) -> StockMovement:
    """Atomically record a stock movement and update the batch cache.

    Parameters
    ----------
    batch_id : int
        PK of the ``Batch`` to mutate.
    quantity : int
        Change amount.  **Positive** for inward (purchase, sales-return),
        **negative** for outward (sale, purchase-return).
    doc_type : str
        Source document class name, e.g. ``'PurchaseInvoice'``.
    doc_id : int
        PK of the source document.

    Returns
    -------
    StockMovement
        The newly created ledger entry.

    Raises
    ------
    InsufficientStockError
        If the update would push ``current_quantity`` below zero
        (wraps the MySQL ``IntegrityError`` from the CHECK constraint).
    Batch.DoesNotExist
        If ``batch_id`` is invalid.
    """
    try:
        with transaction.atomic():
            # 1. Verify batch exists (will raise DoesNotExist if not).
            Batch.objects.get(pk=batch_id)

            # 2. Atomic, race-condition-proof cache update via F().
            rows = Batch.objects.filter(pk=batch_id).update(
                current_quantity=F('current_quantity') + quantity
            )
            if rows == 0:
                raise Batch.DoesNotExist(
                    f"Batch with pk={batch_id} not found."
                )

            # 3. Create the immutable ledger entry.
            movement = StockMovement.objects.create(
                batch_id=batch_id,
                quantity=quantity,
                reference_document_type=doc_type,
                reference_document_id=doc_id,
            )

            return movement

    except IntegrityError as exc:
        # The CHECK constraint fires when current_quantity would go < 0.
        # Wrap it in a domain-specific exception for callers.
        if 'batch_non_negative_stock' in str(exc):
            raise InsufficientStockError(
                f"Insufficient stock in Batch {batch_id}. "
                f"Attempted change: {quantity}."
            ) from exc
        # Re-raise any other IntegrityError (e.g. unique violations).
        raise
