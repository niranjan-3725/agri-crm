from django.db import models
from django.core.exceptions import ValidationError

from master_data.models import Product


class Batch(models.Model):
    """Represents a specific batch of a product in inventory.

    `current_quantity` is the cached running total and is ONLY mutated
    via `inventory.services.process_stock_movement()`.
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


class StockMovement(models.Model):
    """Append-only ledger recording every stock mutation.

    Every change to `Batch.current_quantity` is captured here as an
    immutable event.  Positive `quantity` = inward, negative = outward.
    """

    batch = models.ForeignKey(
        Batch, on_delete=models.CASCADE, related_name='movements'
    )
    quantity = models.IntegerField(
        help_text="Positive for inward, negative for outward.",
    )
    reference_document_type = models.CharField(
        max_length=50,
        help_text="E.g. 'PurchaseInvoice', 'SalesInvoice', 'ManualAdjustment'.",
    )
    reference_document_id = models.PositiveIntegerField()
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
        return (
            f"{direction} {abs(self.quantity)} × {self.batch} "
            f"[{self.reference_document_type} #{self.reference_document_id}]"
        )
