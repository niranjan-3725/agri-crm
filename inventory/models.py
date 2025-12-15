from django.db import models

from django.core.exceptions import ValidationError
from master_data.models import Product

class Batch(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='batches')
    batch_number = models.CharField(max_length=50)
    manufacturing_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    purchase_price = models.DecimalField(max_digits=10, decimal_places=2)
    mrp = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="MRP")
    base_selling_price = models.DecimalField(max_digits=10, decimal_places=2, help_text="Default selling price for this batch")
    current_quantity = models.IntegerField(default=0)
    size = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    unit = models.CharField(max_length=20, default='kg')
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ('product', 'batch_number', 'mrp')

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
