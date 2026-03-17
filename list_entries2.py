import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from accounting.models import GLEntry
from inventory.models import StockMovement
from transactions.models import PurchaseInvoice, PurchaseReturn, SupplierPayment

with open('list_entries_output.txt', 'w', encoding='utf-8') as f:
    f.write('--- Purchase Invoices ---\n')
    for pi in PurchaseInvoice.objects.all():
        f.write(f'PI {pi.id}: {pi}\n')

    f.write('\n--- Purchase Returns ---\n')
    for pr in PurchaseReturn.objects.all():
        f.write(f'PR {pr.id}: {pr}\n')

    f.write('\n--- Supplier Payments ---\n')
    for sp in SupplierPayment.objects.all():
        f.write(f'SP {sp.id}: {sp}\n')

    f.write('\n--- Stock Movements ---\n')
    for sm in StockMovement.objects.all().order_by('id'):
        f.write(f'SM {sm.id}: {sm}\n')

    f.write('\n--- GL Entries ---\n')
    for gl in GLEntry.objects.all().order_by('id'):
        f.write(f'GL {gl.id}: {gl.reference_type}-{gl.reference_id} | {gl.account.name} | Dr: {gl.debit} | Cr: {gl.credit} | Rem: {gl.remarks}\n')
