import os
import re

TEMPLATES_DIR = r'c:\agri_crm\templates\transactions'

with open(os.path.join(TEMPLATES_DIR, 'sales_order_list.html'), 'r', encoding='utf-8') as f:
    so_list = f.read()

po_list = so_list.replace('Sales Order', 'Purchase Order').replace('sales parameter', 'purchase parameter')
po_list = po_list.replace('create_sales_order', 'create_purchase_order')
po_list = po_list.replace('sales_order_detail', 'purchase_order_detail')
po_list = po_list.replace('customer', 'supplier')

with open(os.path.join(TEMPLATES_DIR, 'purchase_order_list.html'), 'w', encoding='utf-8') as f:
    f.write(po_list)

pr_list = so_list.replace('Sales Order', 'Purchase Receipt')
pr_list = pr_list.replace('create_sales_order', 'create_purchase_receipt')
pr_list = pr_list.replace('sales_order_detail', 'purchase_receipt_detail')
pr_list = pr_list.replace('orders', 'receipts')
pr_list = pr_list.replace('order.', 'receipt.')
pr_list = pr_list.replace('order ', 'receipt ')
pr_list = pr_list.replace('customer', 'supplier')

with open(os.path.join(TEMPLATES_DIR, 'purchase_receipt_list.html'), 'w', encoding='utf-8') as f:
    f.write(pr_list)


with open(os.path.join(TEMPLATES_DIR, 'sales_order_detail.html'), 'r', encoding='utf-8') as f:
    so_detail = f.read()

po_detail = so_detail.replace('Sales Order', 'Purchase Order').replace('sales_order', 'purchase_order')
po_detail = re.sub(r'\border\b', 'po', po_detail) # proper word boundary
po_detail = po_detail.replace('create_delivery_note', 'create_purchase_receipt')
po_detail = po_detail.replace('Delivery Note', 'Purchase Receipt')
po_detail = po_detail.replace('create_sale', 'create_purchase')
po_detail = po_detail.replace('Sales Invoice', 'Purchase Invoice')
po_detail = po_detail.replace('customer', 'supplier')
po_detail = po_detail.replace('per_delivered', 'per_received')
po_detail = po_detail.replace('delivery_notes', 'purchase_receipts')
po_detail = po_detail.replace('delivery_note_detail', 'purchase_receipt_detail')
po_detail = po_detail.replace('item.delivered_qty', 'item.received_qty')

with open(os.path.join(TEMPLATES_DIR, 'purchase_order_detail.html'), 'w', encoding='utf-8') as f:
    f.write(po_detail)


with open(os.path.join(TEMPLATES_DIR, 'delivery_note_detail.html'), 'r', encoding='utf-8') as f:
    dn_detail = f.read()

pr_detail = dn_detail.replace('Delivery Note', 'Purchase Receipt')
pr_detail = pr_detail.replace('create_sale', 'create_purchase')
pr_detail = pr_detail.replace('Sales Invoice', 'Purchase Invoice')
pr_detail = pr_detail.replace('customer', 'supplier')
pr_detail = pr_detail.replace('sales_order', 'purchase_order')
pr_detail = re.sub(r'\bnote\b', 'receipt', pr_detail)

with open(os.path.join(TEMPLATES_DIR, 'purchase_receipt_detail.html'), 'w', encoding='utf-8') as f:
    f.write(pr_detail)

print('List and Details generated properly')
