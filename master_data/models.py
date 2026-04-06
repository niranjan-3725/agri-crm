from django.db import models


class Village(models.Model):
    name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Category(models.Model):
    name = models.CharField(max_length=255)
    cgst_rate = models.DecimalField(max_digits=10, decimal_places=2)
    sgst_rate = models.DecimalField(max_digits=10, decimal_places=2)
    igst_rate = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    @property
    def total_tax(self):
        return self.cgst_rate + self.sgst_rate

    def __str__(self):
        return self.name

class Manufacturer(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.name

class Product(models.Model):
    UNIT_CHOICES = [
        ('Bag', 'Bag'),
        ('Packet', 'Packet'),
        ('Bottle', 'Bottle'),
        ('Kg', 'Kg'),
        ('Ltr', 'Ltr'),
    ]
    name = models.CharField(max_length=255)
    hsn_code = models.CharField(max_length=50)
    unit_type = models.CharField(max_length=20, choices=UNIT_CHOICES)
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name='products')
    manufacturer = models.ForeignKey(Manufacturer, on_delete=models.CASCADE, related_name='products')
    # Sprint 10: Moving Average Valuation
    moving_average_price = models.DecimalField(
        max_digits=15, decimal_places=4, default=0,
        help_text="Weighted-average cost, recalculated on purchase inward.",
    )

    class Meta:
        # Rule 33 (Identity Pair Invariant): A product is uniquely identified by
        # its name + manufacturer combination. Two products from different
        # manufacturers may share a name; the same manufacturer may not list
        # the same product twice.
        constraints = [
            models.UniqueConstraint(
                fields=['name', 'manufacturer'],
                name='unique_product_name_manufacturer',
            )
        ]

    def __str__(self):
        return self.name

class Supplier(models.Model):
    name = models.CharField(max_length=255)
    gstin = models.CharField(max_length=50)
    phone = models.CharField(max_length=20)
    address = models.TextField()
    is_distributor = models.BooleanField(default=False)
    default_credit_period = models.IntegerField(default=30, help_text="Default credit days for this supplier")

    def __str__(self):
        return self.name

class Customer(models.Model):
    # --- Identity (Rule 31: Identity Uniqueness Invariant) ---
    name = models.CharField(max_length=255)
    mobile_no = models.CharField(max_length=20, unique=True, verbose_name="Mobile Number")
    # --- Location ---
    village = models.ForeignKey(
        Village, on_delete=models.SET_NULL, null=True, blank=True,
        verbose_name="City/Village",
    )
    address = models.TextField()
    # --- Business ---
    gstin = models.CharField(max_length=50, blank=True, null=True)
    wallet_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    created_at = models.DateTimeField(auto_now_add=True)
    # --- Farm Profile (optional) ---
    father_name = models.CharField(
        max_length=255, null=True, blank=True, verbose_name="Father's Name"
    )
    land_size = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True,
        verbose_name="Land Size (acres)",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['mobile_no'], name='unique_customer_mobile_no'),
        ]

    def __str__(self):
        return self.name
