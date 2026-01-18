import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'agri_crm.settings')
django.setup()

from transactions.models import CustomerPayment

last_txn = CustomerPayment.objects.last()
if last_txn and "Reversal of" in last_txn.notes:
    print(f"Deleting bad reversal: {last_txn.amount} - {last_txn.notes}")
    last_txn.delete()
    print("Deleted.")
else:
    print("No reversal found to delete.")
