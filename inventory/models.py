from django.db import models
from django.core.exceptions import ValidationError

from master_data.models import Product


# ── Sprint 8: Multi-Warehouse Architecture ──

class Warehouse(models.Model):
    """A physical storage location (e.g. 'Main Warehouse', 'Shop Floor')."""
    name = models.CharField(max_length=100, unique=True)
    location = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Batch(models.Model):
    """Represents a specific batch of a product in inventory.

    `current_quantity` is the **global** cached running total across ALL
    warehouses.  It is kept in sync by `process_stock_movement()` for
    backward compatibility but the authoritative per-location quantity
    lives in `StockBin.actual_qty`.
    """

    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name='batches'
    )
    batch_number = models.CharField(max_length=50)
    manufacturing_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    purchase_price = models.DecimalField(max_digits=10, decimal_places=2)
    mrp = models.DecimalField(
        max_digits=10, decimal_places=2, verbose_name="MRP"
    )
    base_selling_price = models.DecimalField(
        max_digits=10, decimal_places=2,
        help_text="Default selling price for this batch",
    )
    current_quantity = models.IntegerField(default=0)
    size = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    unit = models.CharField(max_length=20, default='kg')
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ('product', 'batch_number', 'mrp')
        constraints = [
            models.CheckConstraint(
                condition=models.Q(current_quantity__gte=0),
                name='batch_non_negative_stock',
            ),
        ]

    def clean(self):
        if self.base_selling_price and self.mrp and self.base_selling_price > self.mrp:
            raise ValidationError('Selling price cannot be higher than MRP')

    @property
    def days_to_expiry(self):
        if self.expiry_date:
            from django.utils import timezone
            return (self.expiry_date - timezone.now().date()).days
        return 999

    def __str__(self):
        return f"{self.product.name} ({self.batch_number}) - Qty: {self.current_quantity}"


class StockBin(models.Model):
    """Tracks the actual quantity of a Batch inside a specific Warehouse.

    This is the authoritative source of per-location stock.  The pair
    (warehouse, batch) is unique — one row per batch per warehouse.
    """
    warehouse = models.ForeignKey(
        Warehouse, on_delete=models.PROTECT, related_name='stock_bins',
    )
    batch = models.ForeignKey(
        Batch, on_delete=models.CASCADE, related_name='stock_bins',
    )
    actual_qty = models.IntegerField(default=0)

    class Meta:
        unique_together = ('warehouse', 'batch')
        constraints = [
            models.CheckConstraint(
                condition=models.Q(actual_qty__gte=0),
                name='stockbin_non_negative_qty',
            ),
        ]

    def __str__(self):
        return f"{self.batch} @ {self.warehouse} — qty: {self.actual_qty}"


class StockMovement(models.Model):
    """Append-only ledger recording every stock mutation.

    Every change to stock is captured here as an immutable event.
    Positive `quantity` = inward, negative = outward.
    Sprint 8: now records the warehouse where the movement occurred.
    """

    batch = models.ForeignKey(
        Batch, on_delete=models.CASCADE, related_name='movements'
    )
    warehouse = models.ForeignKey(
        Warehouse, on_delete=models.PROTECT,
        related_name='movements',
        null=True, blank=True,
        help_text="Warehouse where this movement occurred.",
    )
    quantity = models.IntegerField(
        help_text="Positive for inward, negative for outward.",
    )
    reference_document_type = models.CharField(
        max_length=50,
        help_text="E.g. 'PurchaseInvoice', 'SalesInvoice', 'ManualAdjustment'.",
    )
    reference_document_id = models.PositiveIntegerField()
    # Sprint 10: Snapshot of the per-unit valuation at time of movement.
    valuation_rate = models.DecimalField(
        max_digits=15, decimal_places=4, default=0,
        help_text="Per-unit cost at the time of this movement.",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(
                fields=['reference_document_type', 'reference_document_id'],
                name='idx_sm_ref_doc',
            ),
        ]

    def __str__(self):
        direction = "IN" if self.quantity > 0 else "OUT"
        wh = f" @ {self.warehouse}" if self.warehouse else ""
        return (
            f"{direction} {abs(self.quantity)} × {self.batch}{wh} "
            f"[{self.reference_document_type} #{self.reference_document_id}]"
        )


class StockReconciliation(models.Model):
    """Records a physical stock count and the resulting stock adjustment.

    When submitted, the system computes delta = new_quantity - previous_quantity
    and posts a StockMovement of that delta (positive = stock added, negative = removed).
    If delta == 0 no movement is posted, but this record is still persisted as an
    audit log proving the count was confirmed.
    """

    REASON_CHOICES = [
        ('Damage', 'Damage / Spoilage'),
        ('Theft', 'Theft / Shrinkage'),
        ('Count Error', 'Count Error / Correction'),
        ('Other', 'Other'),
    ]

    batch = models.ForeignKey(
        Batch,
        on_delete=models.PROTECT,
        related_name='reconciliations',
    )
    previous_quantity = models.IntegerField(
        help_text="System quantity at the time of reconciliation.",
    )
    new_quantity = models.IntegerField(
        help_text="Physical count entered by the admin.",
    )
    reason = models.CharField(max_length=20, choices=REASON_CHOICES, default='Count Error')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def delta(self):
        return self.new_quantity - self.previous_quantity

    def __str__(self):
        sign = "+" if self.delta >= 0 else ""
        return (
            f"Reconciliation #{self.pk}: {self.batch} | "
            f"{self.previous_quantity} → {self.new_quantity} ({sign}{self.delta})"
        )
