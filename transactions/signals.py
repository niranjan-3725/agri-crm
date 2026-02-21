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
    
    # Determine Customer
    customer = None
    if invoice:
        customer = invoice.customer
    elif hasattr(instance, 'sales_return') and instance.sales_return:
        customer = instance.sales_return.customer
        
    # Sprint 44 & 51 & 57: Wallet Logic (Inflow/Outflow)
    if customer:
        should_save = False
        
        # Outflow (Debit): Usage or Refund
        if instance.payment_mode in ['WALLET', 'REFUND']:
            if kwargs.get('created', False):
                customer.wallet_balance -= instance.amount
                should_save = True
            elif kwargs.get('signal') == post_delete:
                customer.wallet_balance += instance.amount
                should_save = True
        
        # Inflow (Credit): Return or Manual Credit
        elif instance.payment_mode == 'WALLET_CREDIT':
            if kwargs.get('created', False):
                customer.wallet_balance += instance.amount
                should_save = True
            elif kwargs.get('signal') == post_delete:
                customer.wallet_balance -= instance.amount
                should_save = True
                
        if should_save:
            customer.save()
    
    # Update Invoice (Only if tied to invoice)
    if invoice:
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
    
    if invoice:
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
