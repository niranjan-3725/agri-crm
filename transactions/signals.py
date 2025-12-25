from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.db.models import Sum
from decimal import Decimal
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.db.models import Sum
from decimal import Decimal
from .models import SupplierPayment, CustomerPayment

@receiver([post_save, post_delete], sender=CustomerPayment)
def update_sales_invoice_payment_status(sender, instance, **kwargs):
    invoice = instance.invoice
    
    # Sprint 44: Wallet Logic
    if instance.payment_mode == 'WALLET' and invoice.customer:
        customer = invoice.customer
        if kwargs.get('created', False):
            # Deduction on Creation
            customer.wallet_balance -= instance.amount
            customer.save()
        elif kwargs.get('signal') == post_delete:
            # Refund on Deletion
            customer.wallet_balance += instance.amount
            customer.save()
    
    # Calculate total received
    total_received = invoice.payments.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    
    # Update fields
    invoice.amount_received = total_received
    invoice.balance_due = invoice.grand_total - total_received
    
    # Determine status
    if invoice.balance_due <= Decimal('0.01'):
        invoice.payment_status = 'PAID'
        if invoice.balance_due < 0:
            invoice.balance_due = 0
    elif invoice.balance_due == invoice.grand_total:
         if invoice.grand_total > 0:
            invoice.payment_status = 'UNPAID'
         else:
            invoice.payment_status = 'PAID'
    else:
        invoice.payment_status = 'PARTIAL'
        
    invoice.save()

@receiver([post_save, post_delete], sender=SupplierPayment)
def update_invoice_payment_status(sender, instance, **kwargs):
    invoice = instance.invoice
    
    # Calculate total paid
    total_paid = invoice.payments.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    
    # Update fields
    invoice.amount_paid = total_paid
    invoice.balance_due = invoice.total_amount - total_paid
    
    # Determine status
    if invoice.balance_due <= Decimal('0.01'):
        invoice.payment_status = 'PAID'
        # Optional: Set balance to 0 if negligible
        if invoice.balance_due < 0:
            invoice.balance_due = 0
    elif invoice.balance_due == invoice.total_amount:
        # Only if total amount is > 0
        if invoice.total_amount > 0:
             invoice.payment_status = 'UNPAID'
        else:
             invoice.payment_status = 'PAID' # Zero value invoice
    else:
        invoice.payment_status = 'PARTIAL'
        
    invoice.save()
