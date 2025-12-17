import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from transactions.models import PurchaseInvoice

def inspect_dates():
    invoices = PurchaseInvoice.objects.all()
    print(f"Total Invoices: {invoices.count()}")
    for i, invoice in enumerate(invoices):
        date_type = type(invoice.date)
        print(f"ID: {invoice.pk}, Date: {invoice.date}, Type: {date_type}")
        if i >= 10: break

if __name__ == "__main__":
    inspect_dates()
