"""
Sprint 16 — Tax-Exclusive Stock Valuation & SRNB Reconciliation.

Fixes existing data so that:
1. batch.purchase_price stores the pre-tax basic rate (not tax-inclusive).
2. Product.moving_average_price is recalculated from corrected batch prices.
3. All GL entries for existing SUBMITTED Purchase Receipts and Purchase Invoices
   are wiped and regenerated with correct tax-exclusive values.
"""
from decimal import Decimal
from django.db import migrations


def fix_valuation(apps, schema_editor):
    """
    For every PurchaseItem in the system:
    - Recompute batch.purchase_price = basic_rate (pre-tax)
    - Regenerate GL entries for the linked PurchaseReceipt + PurchaseInvoice
    """
    Batch = apps.get_model('inventory', 'Batch')
    Product = apps.get_model('master_data', 'Product')
    PurchaseItem = apps.get_model('transactions', 'PurchaseItem')
    GLEntry = apps.get_model('accounting', 'GLEntry')
    StockMovement = apps.get_model('inventory', 'StockMovement')

    # ── Step 1: Fix each batch's purchase_price using PurchaseItem.basic_rate ──
    # Group by batch and use the latest PurchaseItem's basic_rate.
    batches_fixed = set()
    for item in PurchaseItem.objects.select_related('batch').order_by('id'):
        batch = item.batch
        if batch.pk in batches_fixed:
            continue
        if item.basic_rate and item.basic_rate > 0:
            batch.purchase_price = Decimal(str(item.basic_rate))
            batch.save(update_fields=['purchase_price'])
            batches_fixed.add(batch.pk)

    # ── Step 2: Recalculate Product.moving_average_price ──
    for product in Product.objects.all():
        batches = Batch.objects.filter(product=product, current_quantity__gt=0)
        total_qty = 0
        total_value = Decimal('0')
        for b in batches:
            total_qty += b.current_quantity
            total_value += Decimal(str(b.current_quantity)) * b.purchase_price

        if total_qty > 0:
            product.moving_average_price = total_value / Decimal(total_qty)
        else:
            # Fall back to latest batch price if no stock
            latest = Batch.objects.filter(product=product).order_by('-id').first()
            product.moving_average_price = latest.purchase_price if latest else Decimal('0')
        product.save(update_fields=['moving_average_price'])

    # ── Step 3: Wipe and regenerate GL for all PurchaseReceipts ──
    PurchaseReceipt = apps.get_model('transactions', 'PurchaseReceipt')
    Account = apps.get_model('accounting', 'Account')

    try:
        stock_in_hand = Account.objects.get(name='Stock In Hand')
        srnb = Account.objects.get(name='Stock Received But Not Billed')
    except Account.DoesNotExist:
        return  # Accounts not seeded yet — skip

    for pr in PurchaseReceipt.objects.filter(status='SUBMITTED'):
        # Delete old PR GL entries
        GLEntry.objects.filter(
            reference_type='PurchaseReceipt', reference_id=pr.pk,
        ).delete()

        # Recalculate: sum of (item.basic_rate * item.quantity)
        PurchaseReceiptItem = apps.get_model('transactions', 'PurchaseReceiptItem')
        items = PurchaseReceiptItem.objects.filter(receipt=pr).select_related('batch')

        base_value = Decimal('0')
        for ri in items:
            # Use the corrected batch.purchase_price (now tax-exclusive)
            base_value += Decimal(str(ri.quantity)) * ri.batch.purchase_price

        if base_value > 0:
            GLEntry.objects.create(
                account=stock_in_hand,
                debit=base_value, credit=Decimal('0'),
                reference_type='PurchaseReceipt', reference_id=pr.pk,
                remarks=f'Sprint 16 fix: PurchaseReceipt #{pr.pk}',
            )
            GLEntry.objects.create(
                account=srnb,
                debit=Decimal('0'), credit=base_value,
                reference_type='PurchaseReceipt', reference_id=pr.pk,
                remarks=f'Sprint 16 fix: PurchaseReceipt #{pr.pk}',
            )

        # Also update StockMovement valuation_rate to match corrected price
        for ri in PurchaseReceiptItem.objects.filter(receipt=pr).select_related('batch'):
            StockMovement.objects.filter(
                reference_document_type='PurchaseReceipt',
                reference_document_id=pr.pk,
                batch=ri.batch,
            ).update(valuation_rate=ri.batch.purchase_price)

    # ── Step 4: Wipe and regenerate GL for all PurchaseInvoices ──
    PurchaseInvoice = apps.get_model('transactions', 'PurchaseInvoice')
    try:
        ap = Account.objects.get(name='Accounts Payable')
        cgst = Account.objects.get(name='CGST Receivable')
        sgst = Account.objects.get(name='SGST Receivable')
    except Account.DoesNotExist:
        return

    for pi in PurchaseInvoice.objects.filter(status='SUBMITTED'):
        GLEntry.objects.filter(
            reference_type='PurchaseInvoice', reference_id=pi.pk,
        ).delete()

        total_amount = Decimal(str(pi.total_amount))
        if total_amount == 0:
            continue

        total_tax = Decimal('0')
        for item in PurchaseItem.objects.filter(invoice=pi):
            total_tax += Decimal(str(item.tax_amount))

        total_cgst = (total_tax / 2).quantize(Decimal('0.01'))
        total_sgst = total_tax - total_cgst
        base_amount = total_amount - total_tax

        entries = [
            (srnb, base_amount, Decimal('0')),
            (cgst, total_cgst, Decimal('0')),
            (sgst, total_sgst, Decimal('0')),
            (ap, Decimal('0'), total_amount),
        ]
        for acct, dr, cr in entries:
            if dr > 0 or cr > 0:
                GLEntry.objects.create(
                    account=acct, debit=dr, credit=cr,
                    reference_type='PurchaseInvoice', reference_id=pi.pk,
                    remarks=f'Sprint 16 fix: PurchaseInvoice #{pi.pk}',
                )


def reverse_fix(apps, schema_editor):
    """No-op reverse — manual cleanup would be needed."""
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('accounting', '0004_sprint13_sdnb_account'),
        ('inventory', '0008_sprint10_valuation_fields'),
        ('transactions', '0022_sprint14_order_pipeline'),
    ]

    operations = [
        migrations.RunPython(fix_valuation, reverse_fix),
    ]
