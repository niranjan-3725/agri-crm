from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.db.models import Sum
from decimal import Decimal
from .models import SupplierPayment, CustomerPayment, PurchaseReceipt, PurchaseInvoice, PurchaseItem

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
        # Rule 13.4 (Playbook): Only SUBMITTED payments reduce the balance.
        # CANCELLED payments must not inflate amount_received.
        total_received = (
            invoice.payments
            .filter(status='SUBMITTED')
            .aggregate(total=Sum('amount'))['total']
        ) or Decimal('0.00')

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
        # Only count SUBMITTED payments — cancelled payments must not inflate the total.
        total_paid = invoice.payments.filter(status='SUBMITTED').aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        
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


# DISABLED Sprint 23: Hybrid pattern replaces Two-Stage flow — no ghost invoices needed.
# @receiver(post_save, sender=PurchaseReceipt)
def create_ghost_purchase_invoice(sender, instance, **kwargs):
    """Rule 22 (Material-First): On PurchaseReceipt submission, auto-create
    a Ghost Draft PurchaseInvoice pre-linked to this receipt.

    Runs inside PurchaseReceipt.submit()'s atomic block — failures roll back
    the entire receipt submission.

    Idempotency guard (FP3): skip if any invoice already linked to this receipt.
    Ghost items are zero-rate; PurchaseItem.clean() skips 0-value validation.
    """
    if instance.status != 'SUBMITTED':
        return
    # FP3: Idempotency — handle signal double-fires and manual re-saves
    if PurchaseInvoice.objects.filter(purchase_receipt=instance).exists():
        return

    ghost_invoice = PurchaseInvoice.objects.create(
        status='DRAFT',
        purchase_receipt=instance,
        supplier=instance.supplier,
        purchase_order=instance.purchase_order,
        date=instance.date,
        invoice_number=f'DRAFT-PR-{instance.pk}',
        total_amount=0,
        loading_charges=0,
        additional_discount=0,
    )
    for item in instance.items.select_related('batch', 'purchase_order_item').all():
        PurchaseItem.objects.create(
            invoice=ghost_invoice,
            batch=item.batch,
            quantity=item.quantity,
            basic_rate=0,
            tax_amount=0,
            selling_price=0,
            profit_margin=0,
            total_amount=0,
            purchase_order_item=item.purchase_order_item,
        )
