from decimal import Decimal
from datetime import timedelta
from django.db import models, transaction
from django.core.exceptions import ValidationError

from django.utils import timezone
from master_data.models import Supplier, Customer
from inventory.models import Batch

# Sprint 11: ERP Document State Machine
DOCUMENT_STATUS_CHOICES = [
    ('DRAFT', 'Draft'),
    ('SUBMITTED', 'Submitted'),
    ('CANCELLED', 'Cancelled'),
]

def generate_invoice_number():
    return f"INV-{timezone.now().strftime('%Y%m%d%H%M%S')}"


# ═══════════════════════════════════════════════════════════════════════
# Part O: Order Pipeline (Sprint 14)
# ═══════════════════════════════════════════════════════════════════════

class Quotation(models.Model):
    """Sprint 14: Sales quotation / estimate.

    A non-binding price quote to a customer. Can be converted into
    a SalesOrder.  Has NO impact on stock or GL ledgers.
    """
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True)
    date = models.DateField(default=timezone.now)
    valid_until = models.DateField(null=True, blank=True)
    grand_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=DOCUMENT_STATUS_CHOICES, default='DRAFT')

    def submit(self):
        if self.status != 'DRAFT':
            raise ValidationError("Only draft documents can be submitted.")
        with transaction.atomic():
            self.status = 'SUBMITTED'
            self.save()

    def cancel(self):
        if self.status != 'SUBMITTED':
            raise ValidationError("Only submitted documents can be cancelled.")
        with transaction.atomic():
            self.status = 'CANCELLED'
            self.save()

    def delete(self, *args, **kwargs):
        if self.status != 'DRAFT':
            raise ValidationError("Submitted documents cannot be deleted.")
        models.Model.delete(self, *args, **kwargs)

    def __str__(self):
        return f"Quotation #{self.pk} for {self.customer}"


class QuotationItem(models.Model):
    quotation = models.ForeignKey(Quotation, related_name='items', on_delete=models.CASCADE)
    batch = models.ForeignKey(Batch, on_delete=models.PROTECT)
    quantity = models.IntegerField()
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    def __str__(self):
        return f"{self.quantity} x {self.batch} in QTN#{self.quotation_id}"


class SalesOrder(models.Model):
    """Sprint 14: Confirmed sales order from a customer.

    Tracks fulfillment progress through delivered_qty and billed_qty
    on its line items.  Has NO impact on stock or GL ledgers.
    """
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True)
    date = models.DateField(default=timezone.now)
    grand_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=DOCUMENT_STATUS_CHOICES, default='DRAFT')

    # Link back to the quotation this order was created from
    quotation = models.ForeignKey(
        Quotation, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='sales_orders'
    )

    @property
    def per_delivered(self):
        """Percentage of ordered qty that has been delivered."""
        items = self.items.all()
        if not items:
            return 0
        total_ordered = sum(i.quantity for i in items)
        total_delivered = sum(i.delivered_qty for i in items)
        if total_ordered == 0:
            return 0
        return round((total_delivered / total_ordered) * 100, 1)

    @property
    def per_billed(self):
        """Percentage of ordered qty that has been billed."""
        items = self.items.all()
        if not items:
            return 0
        total_ordered = sum(i.quantity for i in items)
        total_billed = sum(i.billed_qty for i in items)
        if total_ordered == 0:
            return 0
        return round((total_billed / total_ordered) * 100, 1)

    def submit(self):
        if self.status != 'DRAFT':
            raise ValidationError("Only draft documents can be submitted.")
        with transaction.atomic():
            self.status = 'SUBMITTED'
            self.save()

    def cancel(self):
        if self.status != 'SUBMITTED':
            raise ValidationError("Only submitted documents can be cancelled.")
        with transaction.atomic():
            self.status = 'CANCELLED'
            self.save()

    def delete(self, *args, **kwargs):
        if self.status != 'DRAFT':
            raise ValidationError("Submitted documents cannot be deleted.")
        models.Model.delete(self, *args, **kwargs)

    def __str__(self):
        return f"Sales Order #{self.pk} for {self.customer}"


class SalesOrderItem(models.Model):
    sales_order = models.ForeignKey(SalesOrder, related_name='items', on_delete=models.CASCADE)
    batch = models.ForeignKey(Batch, on_delete=models.PROTECT)
    quantity = models.IntegerField()
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    # Sprint 14: Fulfillment tracking
    delivered_qty = models.IntegerField(default=0)
    billed_qty = models.IntegerField(default=0)

    def __str__(self):
        return f"{self.quantity} x {self.batch} in SO#{self.sales_order_id}"


class PurchaseOrder(models.Model):
    """Sprint 14: Purchase order to a supplier.

    Tracks fulfillment progress through received_qty and billed_qty
    on its line items.  Has NO impact on stock or GL ledgers.
    """
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT)
    date = models.DateField(default=timezone.now)
    grand_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=DOCUMENT_STATUS_CHOICES, default='DRAFT')

    @property
    def per_received(self):
        """Percentage of ordered qty that has been received."""
        items = self.items.all()
        if not items:
            return 0
        total_ordered = sum(i.quantity for i in items)
        total_received = sum(i.received_qty for i in items)
        if total_ordered == 0:
            return 0
        return round((total_received / total_ordered) * 100, 1)

    @property
    def per_billed(self):
        """Percentage of ordered qty that has been billed."""
        items = self.items.all()
        if not items:
            return 0
        total_ordered = sum(i.quantity for i in items)
        total_billed = sum(i.billed_qty for i in items)
        if total_ordered == 0:
            return 0
        return round((total_billed / total_ordered) * 100, 1)

    def submit(self):
        if self.status != 'DRAFT':
            raise ValidationError("Only draft documents can be submitted.")
        self.status = 'SUBMITTED'
        self.save()

    def cancel(self):
        if self.status != 'SUBMITTED':
            raise ValidationError("Only submitted documents can be cancelled.")
        self.status = 'CANCELLED'
        self.save()

    def delete(self, *args, **kwargs):
        if self.status != 'DRAFT':
            raise ValidationError("Submitted documents cannot be deleted.")
        models.Model.delete(self, *args, **kwargs)

    def __str__(self):
        return f"Purchase Order #{self.pk} for {self.supplier}"


class PurchaseOrderItem(models.Model):
    purchase_order = models.ForeignKey(PurchaseOrder, related_name='items', on_delete=models.CASCADE)
    batch = models.ForeignKey(Batch, on_delete=models.PROTECT)
    quantity = models.IntegerField()
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    # Sprint 14: Fulfillment tracking
    received_qty = models.IntegerField(default=0)
    billed_qty = models.IntegerField(default=0)

    def __str__(self):
        return f"{self.quantity} x {self.batch} in PO#{self.purchase_order_id}"


# ═══════════════════════════════════════════════════════════════════════
# Part F: Fulfillment Documents (Sprint 13)
# ═══════════════════════════════════════════════════════════════════════

class PurchaseReceipt(models.Model):
    """Sprint 13: Inward stock fulfillment document.

    Records physical receipt of goods.  Stock levels and the
    Inventory-vs-SRNB GL pair are updated ONLY when this document
    is submitted — never by PurchaseInvoice directly.
    """
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT)
    date = models.DateField()
    status = models.CharField(max_length=20, choices=DOCUMENT_STATUS_CHOICES, default='DRAFT')

    # Sprint 14: Link to purchase order
    purchase_order = models.ForeignKey(
        PurchaseOrder, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='purchase_receipts'
    )

    def submit(self):
        from inventory.services import process_stock_movement
        if self.status != 'DRAFT':
            raise ValidationError("Only draft documents can be submitted.")

        with transaction.atomic():
            for item in self.items.all():
                process_stock_movement(
                    batch_id=item.batch.id,
                    quantity=item.quantity,
                    doc_type='PurchaseReceipt',
                    doc_id=self.id,
                )
                # Sprint 14: Update PO item received_qty
                if item.purchase_order_item:
                    item.purchase_order_item.received_qty += item.quantity
                    item.purchase_order_item.save(update_fields=['received_qty'])

            self.status = 'SUBMITTED'
            self.save()

    def cancel(self):
        from inventory.services import process_stock_movement
        if self.status != 'SUBMITTED':
            raise ValidationError("Only submitted documents can be cancelled.")

        with transaction.atomic():
            for item in self.items.all():
                process_stock_movement(
                    batch_id=item.batch.id,
                    quantity=-item.quantity,
                    doc_type='PurchaseReceiptCancel',
                    doc_id=self.id,
                )
                # Sprint 14: Reverse PO item received_qty
                if item.purchase_order_item:
                    item.purchase_order_item.received_qty -= item.quantity
                    item.purchase_order_item.save(update_fields=['received_qty'])

            self.status = 'CANCELLED'
            self.save()

    def delete(self, *args, **kwargs):
        if self.status != 'DRAFT':
            raise ValidationError(
                "Submitted documents cannot be deleted. Use .cancel() instead."
            )
        models.Model.delete(self, *args, **kwargs)

    def __str__(self):
        return f"Purchase Receipt #{self.pk} from {self.supplier}"


class PurchaseReceiptItem(models.Model):
    receipt = models.ForeignKey(PurchaseReceipt, related_name='items', on_delete=models.CASCADE)
    batch = models.ForeignKey(Batch, on_delete=models.PROTECT)
    quantity = models.IntegerField()

    # Sprint 14: Link to specific purchase order line item
    purchase_order_item = models.ForeignKey(
        PurchaseOrderItem, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='receipt_items'
    )

    def __str__(self):
        return f"{self.quantity} x {self.batch} in PR#{self.receipt_id}"


class DeliveryNote(models.Model):
    """Sprint 13: Outward stock fulfillment document.

    Records physical dispatch of goods.  Stock levels and the
    COGS-vs-Inventory GL pair are updated ONLY when this document
    is submitted — never by SalesInvoice directly.
    """
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True)
    date = models.DateField()
    status = models.CharField(max_length=20, choices=DOCUMENT_STATUS_CHOICES, default='DRAFT')

    # Sprint 14: Link to sales order
    sales_order = models.ForeignKey(
        SalesOrder, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='delivery_notes'
    )

    def submit(self):
        from inventory.services import process_stock_movement
        if self.status != 'DRAFT':
            raise ValidationError("Only draft documents can be submitted.")

        with transaction.atomic():
            for item in self.items.all():
                process_stock_movement(
                    batch_id=item.batch.id,
                    quantity=-item.quantity,
                    doc_type='DeliveryNote',
                    doc_id=self.id,
                )
                # Sprint 14: Update SO item delivered_qty
                if item.sales_order_item:
                    item.sales_order_item.delivered_qty += item.quantity
                    item.sales_order_item.save(update_fields=['delivered_qty'])

            self.status = 'SUBMITTED'
            self.save()

    def cancel(self):
        from inventory.services import process_stock_movement
        if self.status != 'SUBMITTED':
            raise ValidationError("Only submitted documents can be cancelled.")

        with transaction.atomic():
            for item in self.items.all():
                process_stock_movement(
                    batch_id=item.batch.id,
                    quantity=item.quantity,
                    doc_type='DeliveryNoteCancel',
                    doc_id=self.id,
                )
                # Sprint 14: Reverse SO item delivered_qty
                if item.sales_order_item:
                    item.sales_order_item.delivered_qty -= item.quantity
                    item.sales_order_item.save(update_fields=['delivered_qty'])

            self.status = 'CANCELLED'
            self.save()

    def delete(self, *args, **kwargs):
        if self.status != 'DRAFT':
            raise ValidationError(
                "Submitted documents cannot be deleted. Use .cancel() instead."
            )
        models.Model.delete(self, *args, **kwargs)

    def __str__(self):
        return f"Delivery Note #{self.pk} for {self.customer}"


class DeliveryNoteItem(models.Model):
    delivery_note = models.ForeignKey(DeliveryNote, related_name='items', on_delete=models.CASCADE)
    batch = models.ForeignKey(Batch, on_delete=models.PROTECT)
    quantity = models.IntegerField()

    # Sprint 14: Link to specific sales order line item
    sales_order_item = models.ForeignKey(
        SalesOrderItem, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='delivery_note_items'
    )

    def __str__(self):
        return f"{self.quantity} x {self.batch} in DN#{self.delivery_note_id}"


# ═══════════════════════════════════════════════════════════════════════
# Part A: Purchase (Inward)
# ═══════════════════════════════════════════════════════════════════════

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
    status = models.CharField(max_length=20, choices=DOCUMENT_STATUS_CHOICES, default='DRAFT')

    # Sprint 4: Amend Lifecycle
    amended_from = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='amendments'
    )

    # Sprint 13: Link to fulfillment document
    purchase_receipt = models.ForeignKey(
        PurchaseReceipt, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='invoices'
    )

    # Sprint 14: Link to purchase order
    purchase_order = models.ForeignKey(
        PurchaseOrder, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='purchase_invoices'
    )

    def save(self, *args, **kwargs):
        # Sprint 23: Auto Due Date
        if not self.due_date and self.date:
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
        
        if self.balance_due <= 0:
            self.payment_status = 'PAID'
            self.balance_due = 0
        elif self.balance_due == self.total_amount and self.total_amount > 0:
            self.payment_status = 'UNPAID'
        else:
            self.payment_status = 'PARTIAL'
            
        super().save(*args, **kwargs)

    def submit(self):
        """Sprint 13: Transition DRAFT → SUBMITTED.

        Auto-creates and submits a PurchaseReceipt (stock movement)
        if one is not already linked, then posts AP GL entries.
        """
        from accounting.services import post_purchase_invoice_gl
        if self.status != 'DRAFT':
            raise ValidationError("Only draft documents can be submitted.")

        with transaction.atomic():
            # Sprint 13: Auto-create fulfillment if not already linked
            if not self.purchase_receipt:
                pr = PurchaseReceipt.objects.create(
                    supplier=self.supplier,
                    date=self.date if not isinstance(self.date, str) else self.date,
                    purchase_order=self.purchase_order,
                )
                for item in self.items.all():
                    PurchaseReceiptItem.objects.create(
                        receipt=pr,
                        batch=item.batch,
                        quantity=item.quantity,
                        purchase_order_item=item.purchase_order_item,
                    )
                pr.submit()
                self.purchase_receipt = pr

            # Sprint 14: Update PO item billed_qty
            for item in self.items.all():
                if item.purchase_order_item:
                    item.purchase_order_item.billed_qty += item.quantity
                    item.purchase_order_item.save(update_fields=['billed_qty'])

            # Sprint 12: Post AP accounting entries (no stock here)
            post_purchase_invoice_gl(self)
            self.status = 'SUBMITTED'
            self.save()

    def cancel(self):
        """Atomically cancel: reverse AP GL, cancel linked receipt."""
        from accounting.services import reverse_document_gl
        if self.status != 'SUBMITTED':
            raise ValidationError("Only submitted documents can be cancelled.")

        with transaction.atomic():
            # Sprint 13: Cancel linked PurchaseReceipt (reverses stock + PO received_qty)
            if self.purchase_receipt and self.purchase_receipt.status == 'SUBMITTED':
                self.purchase_receipt.cancel()

            # Sprint 14: Reverse PO item billed_qty
            for item in self.items.all():
                if item.purchase_order_item:
                    item.purchase_order_item.billed_qty -= item.quantity
                    item.purchase_order_item.save(update_fields=['billed_qty'])

            # Sprint 12: Reverse AP accounting entries
            reverse_document_gl('PurchaseInvoice', self.id)
            self.status = 'CANCELLED'
            self.save()

    def delete(self, *args, **kwargs):
        if self.status != 'DRAFT':
            raise ValidationError(
                "Submitted documents cannot be deleted. Use .cancel() instead."
            )
        models.Model.delete(self, *args, **kwargs)

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
    
    def save(self, *args, **kwargs):
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new:
            # DEBIT_NOTE is handled by post_purchase_return_gl() in
            # PurchaseReturn.submit(). Skip here to avoid a duplicate/wrong entry.
            if self.payment_mode != 'DEBIT_NOTE':
                from accounting.services import post_supplier_payment_gl
                post_supplier_payment_gl(self)

    def __str__(self):
        return f"Payment {self.amount} for {self.invoice.invoice_number if self.invoice else 'N/A'}"

class PurchaseItem(models.Model):
    invoice = models.ForeignKey(PurchaseInvoice, related_name='items', on_delete=models.CASCADE)
    batch = models.ForeignKey(Batch, on_delete=models.PROTECT)
    quantity = models.IntegerField()
    basic_rate = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2)
    
    selling_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    profit_margin = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)

    # Sprint 14: Link to specific purchase order line item
    purchase_order_item = models.ForeignKey(
        PurchaseOrderItem, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='invoice_items'
    )

    def clean(self):
        """Mirror the UI price constraints as a DB-level safety net."""
        from django.core.exceptions import ValidationError
        errors = {}

        # Basic Rate vs Selling Price (fields we own directly)
        if self.basic_rate and self.selling_price:
            if self.selling_price < self.basic_rate:
                errors['selling_price'] = (
                    f"Selling Price (₹{self.selling_price}) cannot be less than Basic Rate (₹{self.basic_rate})."
                )

        # Basic Rate and Selling Price vs MRP (via related Batch)
        if self.batch_id:
            batch_mrp = getattr(self.batch, 'mrp', None)
            if batch_mrp:
                if self.basic_rate and self.basic_rate > batch_mrp:
                    errors['basic_rate'] = (
                        f"Basic Rate (₹{self.basic_rate}) cannot exceed MRP (₹{batch_mrp})."
                    )
                if self.selling_price and self.selling_price > batch_mrp:
                    errors.setdefault('selling_price',
                        f"Selling Price (₹{self.selling_price}) cannot exceed MRP (₹{batch_mrp})."
                    )

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"{self.quantity} x {self.batch} in {self.invoice}"


# ═══════════════════════════════════════════════════════════════════════
# Part B: Sales (Outward)
# ═══════════════════════════════════════════════════════════════════════

class SalesInvoice(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True)
    invoice_number = models.CharField(max_length=50, unique=True, default=generate_invoice_number)
    date = models.DateField(default=timezone.now)
    total_taxable = models.DecimalField(max_digits=12, decimal_places=2)
    total_cgst = models.DecimalField(max_digits=12, decimal_places=2)
    total_sgst = models.DecimalField(max_digits=12, decimal_places=2)
    grand_total = models.DecimalField(max_digits=12, decimal_places=2)

    PAYMENT_STATUS_CHOICES = [
        ('UNPAID', 'Unpaid'),
        ('PARTIAL', 'Partial'),
        ('PAID', 'Paid'),
    ]
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='UNPAID')
    amount_received = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    balance_due = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    due_date = models.DateField(null=True, blank=True)

    status = models.CharField(max_length=20, choices=DOCUMENT_STATUS_CHOICES, default='DRAFT')

    amended_from = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='amendments'
    )

    # Sprint 13: Link to fulfillment document
    delivery_note = models.ForeignKey(
        DeliveryNote, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='invoices'
    )

    # Sprint 14: Link to sales order
    sales_order = models.ForeignKey(
        SalesOrder, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='sales_invoices'
    )

    @property
    def total_tax(self):
        """Returns the sum of CGST and SGST as total tax."""
        return (self.total_cgst or Decimal('0')) + (self.total_sgst or Decimal('0'))

    def save(self, *args, **kwargs):
        if not self.due_date:
             self.due_date = self.date

        self.grand_total = Decimal(str(self.grand_total))
        self.amount_received = Decimal(str(self.amount_received))
        self.balance_due = self.grand_total - self.amount_received
        
        if self.balance_due <= Decimal('0.01'):
            self.payment_status = 'PAID'
            if self.balance_due < 0: self.balance_due = 0
        elif self.balance_due == self.grand_total:
             self.payment_status = 'UNPAID'
        else:
             self.payment_status = 'PARTIAL'

        super().save(*args, **kwargs)
        return f"Sales {self.invoice_number} to {self.customer}"

    def submit(self):
        """Transition DRAFT → SUBMITTED with three atomic announcements.

        Announcement 1 — Stock fulfillment (DeliveryNote):
            Dr  Stock Delivered But Not Billed   MAP × qty
            Cr  Stock In Hand                    MAP × qty

        Announcement 2 — SDNB clearance (COGS recognition):
            Dr  Cost of Goods Sold               MAP × qty
            Cr  Stock Delivered But Not Billed   MAP × qty

        Announcement 3 — Revenue / AR / Tax:
            Dr  Accounts Receivable              grand_total
            Cr  Sales Revenue                    taxable_amount
            Cr  CGST Payable                     cgst
            Cr  SGST Payable                     sgst

        SDNB nets to zero once the invoice is submitted.
        All three are wrapped in a single transaction.atomic() so any
        failure rolls back the entire operation.
        """
        from accounting.services import post_sales_invoice_gl, post_sdnb_clearance_gl
        if self.status != 'DRAFT':
            raise ValidationError("Only draft documents can be submitted.")

        with transaction.atomic():
            # ── Announcement 1: Stock fulfillment ───────────────────────────
            if not self.delivery_note:
                dn = DeliveryNote.objects.create(
                    customer=self.customer,
                    date=self.date if not isinstance(self.date, str) else self.date,
                    sales_order=self.sales_order,
                )
                for item in self.items.all():
                    DeliveryNoteItem.objects.create(
                        delivery_note=dn,
                        batch=item.batch,
                        quantity=item.quantity,
                        sales_order_item=item.sales_order_item,
                    )
                dn.submit()           # Posts: Dr SDNB / Cr Stock In Hand
                self.delivery_note = dn

            # ── Announcement 2: SDNB clearance (COGS recognition) ──────────
            post_sdnb_clearance_gl(self.delivery_note, self.id)

            # ── Announcement 3: Revenue / AR / Tax ─────────────────────────
            post_sales_invoice_gl(self)

            # ── SO tracking: update billed_qty with over-billing guard ──────
            for item in self.items.all():
                if item.sales_order_item:
                    so_item = item.sales_order_item
                    new_billed = so_item.billed_qty + item.quantity
                    if new_billed > so_item.quantity:
                        raise ValidationError(
                            f"Over-billing: {item.batch} — attempting to bill "
                            f"{new_billed} units but only {so_item.quantity} ordered."
                        )
                    so_item.billed_qty = new_billed
                    so_item.save(update_fields=['billed_qty'])

            self.status = 'SUBMITTED'
            self.save()

    def cancel(self):
        """Atomically cancel: reverse AR GL, cancel linked DN, refund wallet."""
        from accounting.services import reverse_document_gl
        if self.status != 'SUBMITTED':
            raise ValidationError("Only submitted documents can be cancelled.")

        with transaction.atomic():
            # Sprint 13: Cancel linked DeliveryNote (reverses stock + SO delivered_qty)
            if self.delivery_note and self.delivery_note.status == 'SUBMITTED':
                self.delivery_note.cancel()

            # Sprint 14: Reverse SO item billed_qty
            for item in self.items.all():
                if item.sales_order_item:
                    item.sales_order_item.billed_qty -= item.quantity
                    item.sales_order_item.save(update_fields=['billed_qty'])

            for payment in self.payments.filter(amount__gt=0, payment_mode='WALLET'):
                if self.customer:
                    self.customer.wallet_balance += payment.amount
                    self.customer.save()
            # Sprint 12: Reverse AR/Revenue/Tax accounting entries
            reverse_document_gl('SalesInvoice', self.id)
            self.status = 'CANCELLED'
            self.save()

    def delete(self, *args, **kwargs):
        if self.status != 'DRAFT':
            raise ValidationError(
                "Submitted documents cannot be deleted. Use .cancel() instead."
            )
        models.Model.delete(self, *args, **kwargs)

class SalesItem(models.Model):
    invoice = models.ForeignKey(SalesInvoice, related_name='items', on_delete=models.CASCADE)
    batch = models.ForeignKey(Batch, on_delete=models.PROTECT)
    quantity = models.IntegerField()
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2)
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)

    # Sprint 14: Link to specific sales order line item
    sales_order_item = models.ForeignKey(
        SalesOrderItem, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='invoice_items'
    )

    def clean(self):
        from django.core.exceptions import ValidationError
        available_stock = self.batch.current_quantity
        
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


# ═══════════════════════════════════════════════════════════════════════
# Part C: Returns (Adjustments)
# ═══════════════════════════════════════════════════════════════════════

class PurchaseReturn(models.Model):
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT)
    original_invoice = models.ForeignKey(PurchaseInvoice, on_delete=models.SET_NULL, null=True, blank=True)
    date = models.DateField()
    reason = models.CharField(max_length=255)
    total_refund_amount = models.DecimalField(max_digits=12, decimal_places=2)

    status = models.CharField(max_length=20, choices=DOCUMENT_STATUS_CHOICES, default='DRAFT')

    def _validate_return_quantities(self):
        """BUG-03 / Pattern 1: Server-side over-return guard.

        Called inside submit()'s atomic block, BEFORE any stock movement.
        Ensures that the total returned quantity (across all submitted returns
        for this invoice + batch) never exceeds the original invoiced quantity.

        Freeform returns (no original_invoice) are not capped — they are
        bounded by available stock, which process_stock_movement() enforces
        via InsufficientStockError.
        """
        if self.status != 'DRAFT':
            raise ValidationError(
                f"Cannot submit: document is already '{self.status}'."
            )
        if not self.original_invoice_id:
            return  # Freeform — stock cap is sufficient

        for item in self.items.select_related('batch').all():
            already_submitted = (
                PurchaseReturnItem.objects
                .filter(
                    return_invoice__original_invoice_id=self.original_invoice_id,
                    return_invoice__status='SUBMITTED',
                    batch=item.batch,
                )
                .exclude(return_invoice=self)
                .aggregate(total=Sum('quantity'))['total']
            ) or 0

            invoiced_qty = (
                PurchaseItem.objects
                .filter(
                    invoice_id=self.original_invoice_id,
                    batch=item.batch,
                )
                .aggregate(total=Sum('quantity'))['total']
            ) or 0

            remaining = invoiced_qty - already_submitted
            if item.quantity > remaining:
                raise ValidationError(
                    f"Over-return on '{item.batch}': "
                    f"only {remaining} unit(s) remain returnable "
                    f"(invoiced {invoiced_qty}, already returned {already_submitted})."
                )

    def submit(self):
        from inventory.services import process_stock_movement
        from accounting.services import post_purchase_return_gl

        with transaction.atomic():
            # Pattern 1: state guard + over-return guard (atomic boundary)
            self._validate_return_quantities()

            for item in self.items.all():
                process_stock_movement(
                    batch_id=item.batch.id,
                    quantity=-item.quantity,
                    doc_type='PurchaseReturn',
                    doc_id=self.id,
                    warehouse_id=item.warehouse_id if item.warehouse_id else None,
                )
            # Pattern 2: full Debit Note GL (Dr AP | Cr Purchase Returns | Cr GST)
            post_purchase_return_gl(self)

            self.status = 'SUBMITTED'
            self.save(update_fields=['status'])

    def cancel(self):
        from inventory.services import process_stock_movement
        from accounting.services import reverse_document_gl

        if self.status != 'SUBMITTED':
            raise ValidationError("Only submitted documents can be cancelled.")

        with transaction.atomic():
            for item in self.items.all():
                process_stock_movement(
                    batch_id=item.batch.id,
                    quantity=item.quantity,
                    doc_type='PurchaseReturnCancel',
                    doc_id=self.id,
                    warehouse_id=item.warehouse_id if item.warehouse_id else None,
                )
            # Reverse the Debit Note GL entries posted at submit time
            reverse_document_gl('PurchaseReturn', self.id)

            if hasattr(self, 'payment_entry') and self.payment_entry:
                self.payment_entry.delete()
            self.status = 'CANCELLED'
            self.save(update_fields=['status'])

    def delete(self, *args, **kwargs):
        if self.status != 'DRAFT':
            raise ValidationError(
                "Submitted returns cannot be deleted. Use .cancel() instead."
            )
        models.Model.delete(self, *args, **kwargs)

    def __str__(self):
        return f"Return to {self.supplier} on {self.date}"

class PurchaseReturnItem(models.Model):
    return_invoice = models.ForeignKey(PurchaseReturn, related_name='items', on_delete=models.CASCADE)
    batch = models.ForeignKey(Batch, on_delete=models.PROTECT)
    quantity = models.IntegerField()
    refund_price = models.DecimalField(max_digits=12, decimal_places=2)

    # BUG-07 fix / Pattern 2: Which warehouse does stock leave from?
    warehouse = models.ForeignKey(
        'inventory.Warehouse',
        on_delete=models.PROTECT,
        null=True, blank=True,
        help_text="Warehouse stock leaves from. Defaults to primary warehouse if blank.",
    )

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
    
    invoice = models.ForeignKey(SalesInvoice, related_name='payments', on_delete=models.PROTECT, null=True, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    payment_date = models.DateField(default=timezone.now)
    payment_mode = models.CharField(max_length=20, choices=PAYMENT_MODE_CHOICES, default='UPI')
    reference_id = models.CharField(max_length=50, blank=True, null=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    reversal_of = models.OneToOneField(
        'self',
        null=True, blank=True,
        on_delete=models.PROTECT,
        related_name='reversal_entry'
    )

    sales_return = models.OneToOneField(
        'SalesReturn',
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='payment_entry'
    )
    
    def save(self, *args, **kwargs):
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new:
            # SALES_RETURN and WALLET_CREDIT do not generate a Cash↔AR entry here.
            # The full Credit Note GL (Dr Sales Returns | Cr AR) is posted by
            # post_sales_return_gl() inside SalesReturn.submit() instead,
            # keeping GL posting in sync with the SUBMITTED state transition.
            if self.payment_mode not in ('SALES_RETURN', 'WALLET_CREDIT'):
                from accounting.services import post_customer_payment_gl
                post_customer_payment_gl(self)

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

    status = models.CharField(max_length=20, choices=DOCUMENT_STATUS_CHOICES, default='DRAFT')

    def _validate_return_quantities(self):
        """BUG-03 / Pattern 1: Server-side over-return guard.

        Called inside submit()'s atomic block, BEFORE any stock movement.
        Ensures that total returned quantity (across all SUBMITTED returns
        for this invoice + batch) never exceeds the original invoiced quantity.

        Freeform returns (no original_sale) are not capped here — they are
        bounded by physical stock, which process_stock_movement() enforces.
        """
        if self.status != 'DRAFT':
            raise ValidationError(
                f"Cannot submit: document is already '{self.status}'."
            )
        if not self.original_sale_id:
            return  # Freeform — stock cap is sufficient

        for item in self.items.select_related('batch').all():
            already_submitted = (
                SalesReturnItem.objects
                .filter(
                    return_invoice__original_sale_id=self.original_sale_id,
                    return_invoice__status='SUBMITTED',
                    batch=item.batch,
                )
                .exclude(return_invoice=self)
                .aggregate(total=Sum('quantity'))['total']
            ) or 0

            invoiced_qty = (
                SalesItem.objects
                .filter(
                    invoice_id=self.original_sale_id,
                    batch=item.batch,
                )
                .aggregate(total=Sum('quantity'))['total']
            ) or 0

            remaining = invoiced_qty - already_submitted
            if item.quantity > remaining:
                raise ValidationError(
                    f"Over-return on '{item.batch}': "
                    f"only {remaining} unit(s) remain returnable "
                    f"(invoiced {invoiced_qty}, already returned {already_submitted})."
                )

    def submit(self):
        from inventory.services import process_stock_movement
        from accounting.services import post_sales_return_gl

        with transaction.atomic():
            # Pattern 1: state guard + over-return guard (inside atomic boundary)
            self._validate_return_quantities()

            for item in self.items.all():
                process_stock_movement(
                    batch_id=item.batch.id,
                    quantity=item.quantity,
                    doc_type='SalesReturn',
                    doc_id=self.id,
                    warehouse_id=item.warehouse_id if item.warehouse_id else None,
                )
            # Pattern 2: full Credit Note GL (Dr Sales Returns | Cr AR)
            post_sales_return_gl(self)

            self.status = 'SUBMITTED'
            self.save(update_fields=['status'])

    def cancel(self):
        from inventory.services import process_stock_movement, InsufficientStockError
        from accounting.services import reverse_document_gl

        if self.status != 'SUBMITTED':
            raise ValidationError("Only submitted documents can be cancelled.")

        with transaction.atomic():
            for item in self.items.all():
                try:
                    process_stock_movement(
                        batch_id=item.batch.id,
                        quantity=-item.quantity,
                        doc_type='SalesReturnCancel',
                        doc_id=self.id,
                        warehouse_id=item.warehouse_id if item.warehouse_id else None,
                    )
                except InsufficientStockError as e:
                    raise ValidationError(f"Cannot revert return: {str(e)}")

            # Reverse the Credit Note GL entries posted at submit time
            reverse_document_gl('SalesReturn', self.id)

            if hasattr(self, 'payment_entry') and self.payment_entry:
                self.payment_entry.delete()
            self.status = 'CANCELLED'
            self.save(update_fields=['status'])

    def delete(self, *args, **kwargs):
        if self.status != 'DRAFT':
            raise ValidationError(
                "Submitted returns cannot be deleted. Use .cancel() instead."
            )
        models.Model.delete(self, *args, **kwargs)

    def __str__(self):
        return f"Return from {self.original_sale} on {self.date}"


class SalesReturnItem(models.Model):
    return_invoice = models.ForeignKey(SalesReturn, related_name='items', on_delete=models.CASCADE)
    batch = models.ForeignKey(Batch, on_delete=models.PROTECT)
    quantity = models.IntegerField()

    # BUG-05 fix / Phase 2.1: Store the invoiced unit price at return creation time.
    # Used by post_sales_return_gl() to compute proportional revenue/tax reversal.
    unit_price_at_invoice = models.DecimalField(
        max_digits=12, decimal_places=2,
        null=True, blank=True,
        help_text="Unit price from the original invoice, frozen at return creation.",
    )
    # BUG-07 fix / Pattern 2: Which warehouse does stock return to?
    warehouse = models.ForeignKey(
        'inventory.Warehouse',
        on_delete=models.PROTECT,
        null=True, blank=True,
        help_text="Warehouse stock returns to. Defaults to primary warehouse if blank.",
    )

    def __str__(self):
        return f"Return {self.quantity} x {self.batch}"
