from decimal import Decimal
from datetime import timedelta
from django.db import models, transaction
from django.core.exceptions import ValidationError

from django.utils import timezone
from master_data.models import Supplier, Customer
from inventory.models import Batch

INVOICE_STATUS_CHOICES = [
    ('ACTIVE', 'Active'),
    ('CANCELLED', 'Cancelled'),
]

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

    # Sprint 3: Immutable Document Lifecycle
    status = models.CharField(max_length=20, choices=INVOICE_STATUS_CHOICES, default='ACTIVE')

    # Sprint 4: Amend Lifecycle — links amended doc back to cancalled original
    amended_from = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='amendments'
    )

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

    def cancel(self):
        """Atomically cancel this invoice: reverse stock, mark CANCELLED.
        Does NOT delete any records — all data is preserved for audit."""
        from inventory.services import process_stock_movement
        if self.status == 'CANCELLED':
            raise ValidationError("This invoice is already cancelled.")

        with transaction.atomic():
            # 1. Reverse stock for every line item (outward = negative)
            for item in self.items.all():
                process_stock_movement(
                    batch_id=item.batch.id,
                    quantity=-item.quantity,
                    doc_type='PurchaseInvoiceCancel',
                    doc_id=self.id,
                )
            # 2. Mark cancelled and persist
            self.status = 'CANCELLED'
            self.save()

    def delete(self, *args, **kwargs):
        raise ValidationError(
            "Submitted invoices cannot be hard-deleted. "
            "Use .cancel() to reverse stock and mark as cancelled."
        )

    def __str__(self):
        return f"Purchase {self.invoice_number} from {self.supplier}"

class SupplierPayment(models.Model):
    PAYMENT_MODE_CHOICES = [
        ('CASH', 'Cash'),
        ('UPI', 'UPI'),
        ('CHEQUE', 'Cheque'),
        ('BANK', 'Bank Transfer'),
        ('DEBIT_NOTE', 'Debit Note'),
    ]
    
    invoice = models.ForeignKey(PurchaseInvoice, related_name='payments', on_delete=models.CASCADE, null=True, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    payment_date = models.DateField(default=timezone.now)
    payment_mode = models.CharField(max_length=20, choices=PAYMENT_MODE_CHOICES, default='CASH')
    reference_id = models.CharField(max_length=50, blank=True, null=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # Sprint 61: Link PurchaseReturn for Debit Note
    purchase_return = models.OneToOneField(
        'PurchaseReturn',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='payment_entry'
    )
    
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

    # Sprint 40: Payment Tracking
    PAYMENT_STATUS_CHOICES = [
        ('UNPAID', 'Unpaid'),
        ('PARTIAL', 'Partial'),
        ('PAID', 'Paid'),
    ]
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='UNPAID')
    amount_received = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    balance_due = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    due_date = models.DateField(null=True, blank=True)

    # Sprint 3: Immutable Document Lifecycle
    status = models.CharField(max_length=20, choices=INVOICE_STATUS_CHOICES, default='ACTIVE')

    # Sprint 4: Amend Lifecycle — links amended doc back to cancelled original
    amended_from = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='amendments'
    )

    @property
    def total_tax(self):
        """Returns the sum of CGST and SGST as total tax."""
        return (self.total_cgst or Decimal('0')) + (self.total_sgst or Decimal('0'))

    def save(self, *args, **kwargs):
        # Auto-set due date if not present (Default: Same day for now, can be +30)
        if not self.due_date:
             self.due_date = self.date

        # Calculate balance due unless it is explicitly handled by signals (signals handle updates mainly)
        # But for initial creation or direct edits:
        self.grand_total = Decimal(str(self.grand_total))
        self.amount_received = Decimal(str(self.amount_received))
        self.balance_due = self.grand_total - self.amount_received
        
        # Determine status
        if self.balance_due <= Decimal('0.01'):
            self.payment_status = 'PAID'
            if self.balance_due < 0: self.balance_due = 0
        elif self.balance_due == self.grand_total:
             self.payment_status = 'UNPAID'
        else:
             self.payment_status = 'PARTIAL'

        super().save(*args, **kwargs)
        return f"Sales {self.invoice_number} to {self.customer}"

    def cancel(self):
        """Atomically cancel this invoice: reverse stock, refund wallet, mark CANCELLED.
        Does NOT delete any records — all data is preserved for audit."""
        from inventory.services import process_stock_movement
        if self.status == 'CANCELLED':
            raise ValidationError("This invoice is already cancelled.")

        with transaction.atomic():
            # 1. Reverse stock for every line item (inward = positive, restoring stock)
            for item in self.items.all():
                process_stock_movement(
                    batch_id=item.batch.id,
                    quantity=item.quantity,
                    doc_type='SalesInvoiceCancel',
                    doc_id=self.id,
                )
            # 2. Refund wallet payments (only positive-amount WALLET entries)
            for payment in self.payments.filter(amount__gt=0, payment_mode='WALLET'):
                if self.customer:
                    self.customer.wallet_balance += payment.amount
                    self.customer.save()
            # 3. Mark cancelled and persist
            self.status = 'CANCELLED'
            self.save()

    def delete(self, *args, **kwargs):
        raise ValidationError(
            "Submitted invoices cannot be hard-deleted. "
            "Use .cancel() to reverse stock and mark as cancelled."
        )

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

    status = models.CharField(max_length=20, choices=INVOICE_STATUS_CHOICES, default='ACTIVE')

    def cancel(self):
        from inventory.services import process_stock_movement
        from django.core.exceptions import ValidationError
        from django.db import transaction
        if self.status == 'CANCELLED':
            raise ValidationError("This return is already cancelled.")

        with transaction.atomic():
            # 1. Reverse Inventory Impact via Ledger Service
            for item in self.items.all():
                process_stock_movement(
                    batch_id=item.batch.id,
                    quantity=item.quantity,
                    doc_type='PurchaseReturnCancel',
                    doc_id=self.id
                )
            
            # 2. Reverse Financial Impact
            if hasattr(self, 'payment_entry') and self.payment_entry:
                self.payment_entry.delete()
                
            # 3. Mark cancelled
            self.status = 'CANCELLED'
            self.save()

    def delete(self, *args, **kwargs):
        from django.core.exceptions import ValidationError
        raise ValidationError(
            "Submitted returns cannot be hard-deleted. "
            "Use .cancel() to reverse stock and mark as cancelled."
        )

    def __str__(self):
        return f"Return to {self.supplier} on {self.date}"

class PurchaseReturnItem(models.Model):
    return_invoice = models.ForeignKey(PurchaseReturn, related_name='items', on_delete=models.CASCADE)
    batch = models.ForeignKey(Batch, on_delete=models.PROTECT)
    quantity = models.IntegerField()
    refund_price = models.DecimalField(max_digits=12, decimal_places=2)

    def __str__(self):
        return f"Return {self.quantity} x {self.batch}"

class CustomerPayment(models.Model):
    PAYMENT_MODE_CHOICES = [
        ('CASH', 'Cash'),
        ('UPI', 'UPI'),
        ('CHEQUE', 'Cheque'),
        ('BANK', 'Bank Transfer'),
        ('WALLET', 'Wallet'),
        ('REFUND', 'Refund / Withdrawal'),
        ('WALLET_CREDIT', 'Wallet Credit'),
        ('SALES_RETURN', 'Sales Return Adjustment'),
    ]
    
    # Sprint 54: Changed from CASCADE to PROTECT to prevent 'Ghost Invoices'
    # Sprint 57: Allow null invoice for generic Wallet Credits (e.g. Sales Return)
    invoice = models.ForeignKey(SalesInvoice, related_name='payments', on_delete=models.PROTECT, null=True, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    payment_date = models.DateField(default=timezone.now)
    payment_mode = models.CharField(max_length=20, choices=PAYMENT_MODE_CHOICES, default='UPI')
    reference_id = models.CharField(max_length=50, blank=True, null=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    # Sprint 54: Strict reversal linking via FK instead of notes-based pattern matching
    # Prevents 'Fake Reversals' exploit by linking reversal to original payment by ID
    reversal_of = models.OneToOneField(
        'self',
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='reversal_entry'
    )

    # Sprint 57: Link Payment to SalesReturn for direct financial credit
    sales_return = models.OneToOneField(
        'SalesReturn',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='payment_entry'
    )
    
    def __str__(self):
        if self.invoice:
            return f"Receipt {self.amount} for {self.invoice.invoice_number}"
        elif self.sales_return:
            return f"Credit {self.amount} for Return #{self.sales_return.pk}"
        else:
            return f"Payment {self.amount} ({self.payment_mode})"

class SalesReturn(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, null=True, blank=True)
    original_sale = models.ForeignKey(SalesInvoice, on_delete=models.PROTECT, null=True, blank=True)
    date = models.DateField()
    refund_amount = models.DecimalField(max_digits=12, decimal_places=2)

    status = models.CharField(max_length=20, choices=INVOICE_STATUS_CHOICES, default='ACTIVE')

    def cancel(self):
        from inventory.services import process_stock_movement, InsufficientStockError
        from django.core.exceptions import ValidationError
        from django.db import transaction
        if self.status == 'CANCELLED':
            raise ValidationError("This return is already cancelled.")

        with transaction.atomic():
            # 1. Reverse Inventory Impact
            for item in self.items.all():
                try:
                    process_stock_movement(
                        batch_id=item.batch.id,
                        quantity=-item.quantity,
                        doc_type='SalesReturnCancel',
                        doc_id=self.id
                    )
                except InsufficientStockError as e:
                    raise ValidationError(f"Cannot revert return. Removing this return stock drops actual stock below zero: {str(e)}")
            
            # 2. Reverse Financial Impact
            if hasattr(self, 'payment_entry') and self.payment_entry:
                self.payment_entry.delete()
                
            # 3. Mark cancelled
            self.status = 'CANCELLED'
            self.save()

    def delete(self, *args, **kwargs):
        from django.core.exceptions import ValidationError
        raise ValidationError(
            "Submitted returns cannot be hard-deleted. "
            "Use .cancel() to reverse stock and mark as cancelled."
        )

    def __str__(self):
        return f"Return from {self.original_sale} on {self.date}"

class SalesReturnItem(models.Model):
    return_invoice = models.ForeignKey(SalesReturn, related_name='items', on_delete=models.CASCADE)
    batch = models.ForeignKey(Batch, on_delete=models.PROTECT)
    quantity = models.IntegerField()

    def __str__(self):
        return f"Return {self.quantity} x {self.batch}"
