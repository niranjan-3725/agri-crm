import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from accounting.models import GLEntry
from inventory.models import StockMovement
from transactions.models import PurchaseInvoice, PurchaseReturn, SupplierPayment

print('--- Purchase Invoices ---')
for pi in PurchaseInvoice.objects.all():
    print(f'PI {pi.id}: {pi}')

print('\n--- Purchase Returns ---')
for pr in PurchaseReturn.objects.all():
    print(f'PR {pr.id}: {pr}')

print('\n--- Supplier Payments ---')
for sp in SupplierPayment.objects.all():
    print(f'SP {sp.id}: {sp}')

print('\n--- Stock Movements ---')
for sm in StockMovement.objects.all().order_by('id'):
    print(f'SM {sm.id}: {sm}')

print('\n--- GL Entries ---')
for gl in GLEntry.objects.all().order_by('id'):
    print(f'GL {gl.id}: {gl.reference_type}-{gl.reference_id} | {gl.account.name} | Dr: {gl.debit} | Cr: {gl.credit} | Rem: {gl.remarks}')
