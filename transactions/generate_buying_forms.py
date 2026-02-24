import os

TEMPLATES_DIR = r'c:\agri_crm\templates\transactions'
with open(os.path.join(TEMPLATES_DIR, 'purchase_form.html'), 'r', encoding='utf-8') as f:
    purchase_form = f.read()

# For Purchase Order
po_form = purchase_form.replace('{% if invoice %}Edit Entry{% else %}New Entry{% endif %}', 'New Purchase Order')
po_form = po_form.replace('''{% if invoice %}{% url 'purchase_edit' invoice.pk %}{% else %}{% url 'create_purchase' %}{% endif %}''', '''{% url 'create_purchase_order' %}''')
po_form = po_form.replace('Process Invoice', 'Create Purchase Order')

# Disable or remove the payment status controls since PO doesn't have it.
# Actually it's easier to just hide them using CSS or leave them but they won't do anything because we don't save payments for POs.
po_form = po_form.replace('<!-- Payment Status Control -->', '<!-- Payment Status Control --><div class="hidden">')
po_form = po_form.replace('<div class="p-8 bg-gray-50/50 border-t border-gray-100 mt-auto">', '</div><div class="p-8 bg-gray-50/50 border-t border-gray-100 mt-auto">')

# For Purchase Receipt
pr_form = purchase_form.replace('{% if invoice %}Edit Entry{% else %}New Entry{% endif %}', 'New Purchase Receipt')
pr_form = pr_form.replace('''{% if invoice %}{% url 'purchase_edit' invoice.pk %}{% else %}{% url 'create_purchase' %}{% endif %}''', '''{% url 'create_purchase_receipt' %}''')
pr_form = pr_form.replace('Process Invoice', 'Register Inward Goods')

pr_form = pr_form.replace('{% csrf_token %}', '{% csrf_token %}\n                <input type="hidden" name="source_purchase_order_id" value="{{ source_purchase_order_id|default:'' }}">\n')

alert_html = '''
<div class="bg-orange-50 border border-orange-200 text-orange-800 p-6 rounded-2xl flex items-start gap-4 mb-8 shadow-sm">
    <div class="bg-orange-100 p-2 rounded-xl mt-0.5">
        <svg class="w-6 h-6 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
        </svg>
    </div>
    <div>
        <span class="font-bold text-lg block mb-1">Ledger Impact Warning</span>
        <span class="text-sm font-medium">Submitting this document adds physical stock to the warehouse and hits the SRNB (Stock Received Not Billed) clearing account. It does NOT touch Accounts Payable.</span>
    </div>
</div>
'''
pr_form = pr_form.replace('<form method="post"', alert_html + '<form method="post"')
# Hide payment on PR too
pr_form = pr_form.replace('<!-- Payment Status Control -->', '<!-- Payment Status Control --><div class="hidden">')
pr_form = pr_form.replace('<div class="p-8 bg-gray-50/50 border-t border-gray-100 mt-auto">', '</div><div class="p-8 bg-gray-50/50 border-t border-gray-100 mt-auto">')


def write_tpl(name, content):
    with open(os.path.join(TEMPLATES_DIR, name), 'w', encoding='utf-8') as f:
        f.write(content)

write_tpl('purchase_order_form.html', po_form)
write_tpl('purchase_receipt_form.html', pr_form)

print('Forms created from purchase_form base.')
