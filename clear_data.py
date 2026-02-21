import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from inventory.models import Batch
from transactions.models import (
    PurchaseInvoice, PurchaseItem, SupplierPayment, 
    PurchaseReturn, PurchaseReturnItem,
    SalesInvoice, SalesItem, CustomerPayment,
    SalesReturn, SalesReturnItem
)

def clear_data():
    print("Starting data cleanup...")
    
    # Order matters due to PROTECT and ForeignKeys
    
    print("Deleting Sales Returns...")
    SalesReturnItem.objects.all().delete()
    SalesReturn.objects.all().delete()
    
    print("Deleting Sales Payments...")
    CustomerPayment.objects.all().delete()
    
    print("Deleting Sales...")
    SalesItem.objects.all().delete()
    SalesInvoice.objects.all().delete()
    
    print("Deleting Purchase Returns...")
    PurchaseReturnItem.objects.all().delete()
    PurchaseReturn.objects.all().delete()
    
    print("Deleting Purchase Payments...")
    SupplierPayment.objects.all().delete()
    
    print("Deleting Purchase Items...")
    PurchaseItem.objects.all().delete()
    
    print("Deleting Purchase Invoices...")
    PurchaseInvoice.objects.all().delete()
    
    print("Deleting Inventory Batches...")
    Batch.objects.all().delete()
    
    print("Cleanup complete!")

if __name__ == "__main__":
    clear_data()
