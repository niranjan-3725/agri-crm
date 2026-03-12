import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from inventory.models import StockMovement, StockBin, Batch, StockReconciliation
from transactions.models import (
    Quotation, QuotationItem,
    SalesOrder, SalesOrderItem,
    PurchaseOrder, PurchaseOrderItem,
    PurchaseReceipt, PurchaseReceiptItem,
    DeliveryNote, DeliveryNoteItem,
    PurchaseInvoice, PurchaseItem,
    SupplierPayment,
    SalesInvoice, SalesItem,
    PurchaseReturn, PurchaseReturnItem,
    CustomerPayment,
    SalesReturn, SalesReturnItem
)
from accounting.models import GLEntry

def clear_data():
    print("Clearing General Ledger...")
    GLEntry.objects.all().delete()

    print("Clearing Receivables (Customer Payments) & Payables (Supplier Payments)...")
    CustomerPayment.objects.all().delete()
    SupplierPayment.objects.all().delete()

    print("Clearing Returns (Sales Returns & Purchase Returns)...")
    SalesReturnItem.objects.all().delete()
    SalesReturn.objects.all().delete()
    PurchaseReturnItem.objects.all().delete()
    PurchaseReturn.objects.all().delete()
    
    print("Clearing Sales (Invoices, Delivery Notes, Sales Orders, Quotations)...")
    SalesItem.objects.all().delete()
    SalesInvoice.objects.all().delete()
    DeliveryNoteItem.objects.all().delete()
    DeliveryNote.objects.all().delete()
    SalesOrderItem.objects.all().delete()
    SalesOrder.objects.all().delete()
    QuotationItem.objects.all().delete()
    Quotation.objects.all().delete()

    print("Clearing Purchases (Invoices, Receipts, Purchase Orders)...")
    PurchaseItem.objects.all().delete()
    PurchaseInvoice.objects.all().delete()
    PurchaseReceiptItem.objects.all().delete()
    PurchaseReceipt.objects.all().delete()
    PurchaseOrderItem.objects.all().delete()
    PurchaseOrder.objects.all().delete()

    print("Clearing Inventory (Stock Movements, Stock Bins, Batches, Reconciliations)...")
    StockMovement.objects.all().delete()
    StockReconciliation.objects.all().delete()
    StockBin.objects.all().delete()
    Batch.objects.all().delete()

    print("Database transaction records cleared successfully!")

if __name__ == '__main__':
    clear_data()
