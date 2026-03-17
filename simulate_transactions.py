import os
import django
from decimal import Decimal
from datetime import date

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from master_data.models import Customer, Supplier, Product
from inventory.models import Warehouse, Batch
from accounting.models import GLEntry
from transactions.models import (
    PurchaseReceipt, PurchaseReceiptItem,
    PurchaseInvoice, PurchaseItem,
    PurchaseReturn, PurchaseReturnItem,
    DeliveryNote, DeliveryNoteItem,
    SalesInvoice, SalesItem,
    SalesReturn, SalesReturnItem
)

def run_simulation():
    supplier = Supplier.objects.first()
    customer = Customer.objects.first()
    product = Product.objects.first()
    warehouse = Warehouse.objects.first()
    
    if not all([supplier, customer, product, warehouse]):
        print("Missing master data. Run python manage.py loaddata or setup data.")
        return

    # Ensure a batch exists with some basic info
    batch, _ = Batch.objects.get_or_create(
        product=product,
        batch_number='SIM-BATCH-01',
        defaults={'manufacturing_date': date.today(), 'expiry_date': date(2099, 1, 1)}
    )

    # 1. Purchase Receipt
    print("--- 1. Purchase Receipt (10 units @ 100) ---")
    pr_doc = PurchaseReceipt.objects.create(
        supplier=supplier,
        receipt_date=date.today(),
        status='DRAFT'
    )
    PurchaseReceiptItem.objects.create(
        receipt=pr_doc,
        batch=batch,
        quantity=10
    )
    pr_doc.submit()
    
    # 2. Purchase Invoice
    print("--- 2. Purchase Invoice (10 units @ 100) ---")
    pi_doc = PurchaseInvoice.objects.create(
        supplier=supplier,
        invoice_date=date.today(),
        status='DRAFT',
        invoice_number='SIM-PI-001'
    )
    PurchaseItem.objects.create(
        invoice=pi_doc,
        batch=batch,
        quantity=10,
        basic_rate=Decimal('100.00'),
        tax_amount=Decimal('10.00'), # 10% tax for simplicity
        selling_price=Decimal('150.00'),
        profit_margin=Decimal('50.00'),
        total_amount=Decimal('1100.00')
    )
    pi_doc.total_amount = Decimal('1100.00')
    pi_doc.save()
    pi_doc.submit()
    
    # 3. Purchase Return (2 units)
    print("--- 3. Purchase Return (2 units) ---")
    pret_doc = PurchaseReturn.objects.create(
        supplier=supplier,
        return_date=date.today(),
        status='DRAFT',
        original_invoice=pi_doc
    )
    PurchaseReturnItem.objects.create(
        return_invoice=pret_doc,
        batch=batch,
        warehouse=warehouse,
        quantity=2,
        refund_price=Decimal('100.00')
    )
    pret_doc.total_amount = Decimal('220.00')
    pret_doc.save()
    pret_doc.submit()

    # 4. Cancel Purchase Return
    print("--- 4. Cancel Purchase Return ---")
    pret_doc.cancel()

    # 5. Delivery Note (5 units)
    print("--- 5. Delivery Note (5 units) ---")
    dn_doc = DeliveryNote.objects.create(
        customer=customer,
        delivery_date=date.today(),
        status='DRAFT'
    )
    DeliveryNoteItem.objects.create(
        delivery_note=dn_doc,
        batch=batch,
        quantity=5
    )
    dn_doc.submit()

    # 6. Sales Invoice (5 units)
    print("--- 6. Sales Invoice (5 units) ---")
    si_doc = SalesInvoice.objects.create(
        customer=customer,
        invoice_date=date.today(),
        status='DRAFT',
        invoice_number='SIM-SI-001'
    )
    SalesItem.objects.create(
        invoice=si_doc,
        batch=batch,
        quantity=5,
        unit_price=Decimal('150.00'),
        tax_rate=Decimal('10.00'),
        tax_amount=Decimal('75.00'),
        total_amount=Decimal('825.00')
    )
    si_doc.grand_total = Decimal('825.00')
    si_doc.total_taxable = Decimal('750.00')
    si_doc.total_cgst = Decimal('37.50')
    si_doc.total_sgst = Decimal('37.50')
    si_doc.save()
    si_doc.linked_delivery_notes.add(dn_doc)
    si_doc.submit()

    # 7. Sales Return (1 unit)
    print("--- 7. Sales Return (1 unit) ---")
    sret_doc = SalesReturn.objects.create(
        customer=customer,
        return_date=date.today(),
        status='DRAFT',
        original_sale=si_doc
    )
    SalesReturnItem.objects.create(
        return_invoice=sret_doc,
        batch=batch,
        warehouse=warehouse,
        quantity=1,
        unit_price_at_invoice=Decimal('150.00')
    )
    sret_doc.total_refund = Decimal('165.00')
    sret_doc.save()
    sret_doc.submit()

    # 8. Cancel Sales Return
    print("--- 8. Cancel Sales Return ---")
    sret_doc.cancel()

    # 9. Cancel Sales Invoice & Delivery note
    print("--- 9. Cancel Sales Invoice and DN ---")
    si_doc.cancel()
    dn_doc.cancel()

    # 10. Cancel Purchase Invoice & Receipt
    print("--- 10. Cancel Purchase Invoice and Receipt ---")
    pi_doc.cancel()
    pr_doc.cancel()

    print("\n\nAll simulation complete.")
    
    with open('simulation_gl_output.txt', 'w', encoding='utf-8') as f:
        f.write('=== GENERAL LEDGER ENTRIES ===\n')
        for gl in GLEntry.objects.all().order_by('id'):
            f.write(f'GL {gl.id}: {gl.reference_type}-{gl.reference_id} | {gl.account.name:<30} | Dr: {gl.debit:>9} | Cr: {gl.credit:>9} | {gl.remarks}\n')

        from django.db.models import Sum
        f.write('\n=== ACCOUNT BALANCES ===\n')
        for account in GLEntry.objects.values('account__name').annotate(tot_dr=Sum('debit'), tot_cr=Sum('credit')):
            bal = account['tot_dr'] - account['tot_cr']
            f.write(f"{account['account__name']:<30} | Net: {bal:>9}\n")

if __name__ == '__main__':
    run_simulation()
