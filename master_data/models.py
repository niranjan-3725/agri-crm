from django.db import models

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
    name = models.CharField(max_length=255)
    mobile_no = models.CharField(max_length=20)
    city = models.CharField(max_length=100, null=True, blank=True, verbose_name="City/Village")
    address = models.TextField()
    gstin = models.CharField(max_length=50, blank=True, null=True)
    wallet_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name
