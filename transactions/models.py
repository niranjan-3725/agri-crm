from decimal import Decimal
from datetime import timedelta
from django.db import models

from django.utils import timezone
from master_data.models import Supplier, Customer
from inventory.models import Batch

def generate_invoice_number():
    return f"INV-{timezone.now().strftime('%Y%m%d%H%M%S')}"

# Part A: Purchase (Inward)
class PurchaseInvoice(models.Model):
    PAYMENT_STATUS_CHOICES = [
        ('UNPAID', 'Unpaid'),
        ('PARTIAL', 'Partial'),
        ('PAID', 'Full'),
    ]

    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT)
    invoice_number = models.CharField(max_length=50, unique=True)
    date = models.DateField()
    # Sprint 23: Due Date
    due_date = models.DateField(null=True, blank=True)
    
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    loading_charges = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    additional_discount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    # Sprint 22: Payment Status Tracking
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='UNPAID')
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    balance_due = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    file = models.FileField(upload_to='purchase_invoices/', blank=True, null=True)

    def save(self, *args, **kwargs):
        # Sprint 23: Auto Due Date
        if not self.due_date and self.date:
            # Ensure date is a date object, not a string
            from datetime import date as date_type
            if isinstance(self.date, str):
                from datetime import datetime
                self.date = datetime.strptime(self.date, '%Y-%m-%d').date()
            
            days = self.supplier.default_credit_period
            self.due_date = self.date + timedelta(days=days)

        # Calculate balance due
        self.amount_paid = Decimal(str(self.amount_paid))
        self.total_amount = Decimal(str(self.total_amount))
        self.balance_due = self.total_amount - self.amount_paid
        
        # Determine status based on balance
        if self.balance_due <= 0:
            self.payment_status = 'PAID'
            self.balance_due = 0 # Ensure no negative balance
        elif self.balance_due == self.total_amount and self.total_amount > 0:
            self.payment_status = 'UNPAID'
        else:
            self.payment_status = 'PARTIAL'
            
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Purchase {self.invoice_number} from {self.supplier}"

class SupplierPayment(models.Model):
    PAYMENT_MODE_CHOICES = [
        ('CASH', 'Cash'),
        ('UPI', 'UPI'),
        ('CHEQUE', 'Cheque'),
        ('BANK', 'Bank Transfer'),
    ]
    
    invoice = models.ForeignKey(PurchaseInvoice, related_name='payments', on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    payment_date = models.DateField(default=timezone.now)
    payment_mode = models.CharField(max_length=20, choices=PAYMENT_MODE_CHOICES, default='CASH')
    reference_id = models.CharField(max_length=50, blank=True, null=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"Payment {self.amount} for {self.invoice.invoice_number}"

class PurchaseItem(models.Model):
    invoice = models.ForeignKey(PurchaseInvoice, related_name='items', on_delete=models.CASCADE)
    batch = models.ForeignKey(Batch, on_delete=models.PROTECT)
    quantity = models.IntegerField()
    # unit_cost removed as per request 
    # User said: basic_rate (Price before tax), net_cost (Final Cost: Basic + Tax).
    # Existing unit_cost seems to have been used as "Purchase Rate" in views.
    # I will add the new fields.
    basic_rate = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2)
    # net_cost removed as per request
    
    selling_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    profit_margin = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)

    def __str__(self):
        return f"{self.quantity} x {self.batch} in {self.invoice}"

# Part B: Sales (Outward)
class SalesInvoice(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True)
    invoice_number = models.CharField(max_length=50, unique=True, default=generate_invoice_number)
    date = models.DateField(default=timezone.now)
    total_taxable = models.DecimalField(max_digits=12, decimal_places=2)
    total_cgst = models.DecimalField(max_digits=12, decimal_places=2)
    total_sgst = models.DecimalField(max_digits=12, decimal_places=2)
    grand_total = models.DecimalField(max_digits=12, decimal_places=2)

    def __str__(self):
        return f"Sales {self.invoice_number} to {self.customer}"

class SalesItem(models.Model):
    invoice = models.ForeignKey(SalesInvoice, related_name='items', on_delete=models.CASCADE)
    batch = models.ForeignKey(Batch, on_delete=models.PROTECT)
    quantity = models.IntegerField()
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2)
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)

    def clean(self):
        from django.core.exceptions import ValidationError
        # Check sufficient stock (Smart Validation)
        available_stock = self.batch.current_quantity
        
        # If editing, put back the old amount
        if self.pk:
            try:
                old_instance = SalesItem.objects.get(pk=self.pk)
                available_stock += old_instance.quantity
            except SalesItem.DoesNotExist:
                pass
        
        if self.quantity > available_stock:
            raise ValidationError(f"Insufficient Stock. Available: {available_stock}")

    def __str__(self):
        return f"{self.quantity} x {self.batch} in {self.invoice}"

# Part C: Returns (Adjustments)
class PurchaseReturn(models.Model):
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT)
    original_invoice = models.ForeignKey(PurchaseInvoice, on_delete=models.SET_NULL, null=True, blank=True)
    date = models.DateField()
    reason = models.CharField(max_length=255)
    total_refund_amount = models.DecimalField(max_digits=12, decimal_places=2)

    def __str__(self):
        return f"Return to {self.supplier} on {self.date}"

class PurchaseReturnItem(models.Model):
    return_invoice = models.ForeignKey(PurchaseReturn, related_name='items', on_delete=models.CASCADE)
    batch = models.ForeignKey(Batch, on_delete=models.PROTECT)
    quantity = models.IntegerField()
    refund_price = models.DecimalField(max_digits=12, decimal_places=2)

    def __str__(self):
        return f"Return {self.quantity} x {self.batch}"

class SalesReturn(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, null=True, blank=True)
    original_sale = models.ForeignKey(SalesInvoice, on_delete=models.PROTECT, null=True, blank=True)
    date = models.DateField()
    refund_amount = models.DecimalField(max_digits=12, decimal_places=2)

    def __str__(self):
        return f"Return from {self.original_sale} on {self.date}"

class SalesReturnItem(models.Model):
    return_invoice = models.ForeignKey(SalesReturn, related_name='items', on_delete=models.CASCADE)
    batch = models.ForeignKey(Batch, on_delete=models.PROTECT)
    quantity = models.IntegerField()

    def __str__(self):
        return f"Return {self.quantity} x {self.batch}"
