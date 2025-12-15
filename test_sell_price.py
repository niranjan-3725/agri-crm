import os
import sys
sys.path.append('c:/agri_crm')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django
django.setup()

from django.test import Client
from transactions.models import PurchaseInvoice

c = Client()

# Test new purchase page
r1 = c.get('/purchases/new/')
print(f'New Purchase GET: {r1.status_code}')
content1 = r1.content.decode('utf-8')
has_sell_price_header_new = 'Sell Price' in content1
has_sell_price_input_new = 'selling_price[]' in content1
print(f'[{"PASS" if has_sell_price_header_new else "FAIL"}] Sell Price header in new form')
print(f'[{"PASS" if has_sell_price_input_new else "FAIL"}] Sell Price input in new form')

# Test edit purchase page
invoice = PurchaseInvoice.objects.first()
if invoice:
    r2 = c.get(f'/purchases/{invoice.pk}/edit/')
    print(f'\nEdit Purchase GET: {r2.status_code}')
    content2 = r2.content.decode('utf-8')
    has_sell_price_header_edit = 'Sell Price' in content2
    has_sell_price_input_edit = 'selling_price[]' in content2
    print(f'[{"PASS" if has_sell_price_header_edit else "FAIL"}] Sell Price header in edit form')
    print(f'[{"PASS" if has_sell_price_input_edit else "FAIL"}] Sell Price input in edit form')
    
    # Check if selling_price value is pre-populated in JSON
    has_selling_price_json = '"selling_price"' in content2
    print(f'[{"PASS" if has_selling_price_json else "FAIL"}] selling_price in JSON data')
else:
    print('No invoices found')
