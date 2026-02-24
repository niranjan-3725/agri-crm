import os

TEMPLATES_DIR = r'c:\agri_crm\templates\transactions'
with open(os.path.join(TEMPLATES_DIR, 'sales_form_v2.html'), 'r', encoding='utf-8') as f:
    sales_form = f.read()

# For Quotation
q_form = sales_form.replace('{% if invoice %}Edit Sale{% else %}New Sale{% endif %}', 'New Quotation')
q_form = q_form.replace('''{% if invoice %}{% url 'edit_sale' invoice.pk %}{% else %}{% url 'create_sale' %}{% endif %}''', '''{% url 'create_quotation' %}''')
q_form = q_form.replace('Complete Sale', 'Save Quotation')

# For Sales Order
s_form = sales_form.replace('{% if invoice %}Edit Sale{% else %}New Sale{% endif %}', 'New Sales Order')
s_form = s_form.replace('''{% if invoice %}{% url 'edit_sale' invoice.pk %}{% else %}{% url 'create_sale' %}{% endif %}''', '''{% url 'create_sales_order' %}''')
s_form = s_form.replace('{% csrf_token %}', '{% csrf_token %}\n                <input type="hidden" name="source_quotation_id" value="{{ source_quotation_id|default:'' }}">\n')
s_form = s_form.replace('Complete Sale', 'Create Sales Order')

# For Delivery Note
d_form = sales_form.replace('{% if invoice %}Edit Sale{% else %}New Sale{% endif %}', 'New Delivery Note')
d_form = d_form.replace('''{% if invoice %}{% url 'edit_sale' invoice.pk %}{% else %}{% url 'create_sale' %}{% endif %}''', '''{% url 'create_delivery_note' %}''')
d_form = d_form.replace('{% csrf_token %}', '{% csrf_token %}\n                <input type="hidden" name="source_sales_order_id" value="{{ source_sales_order_id|default:'' }}">\n')

alert_html = '''
<div class="bg-orange-50 border border-orange-200 text-orange-800 p-5 rounded-[2rem] flex items-start gap-4 mb-8 shadow-sm">
    <div class="bg-orange-100 p-2 rounded-xl mt-0.5">
        <svg class="w-6 h-6 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
        </svg>
    </div>
    <div>
        <span class="font-bold text-lg block mb-1">Ledger Impact Warning</span>
        <span class="text-sm font-medium">Submitting this document definitively deducts physical stock from the warehouse. It does not generate financial revenue.</span>
    </div>
</div>
'''
d_form = d_form.replace('<form method="POST"', alert_html + '<form method="POST"')
d_form = d_form.replace('Complete Sale', 'Dispatch Inventory (DN)')

def write_tpl(name, content):
    with open(os.path.join(TEMPLATES_DIR, name), 'w', encoding='utf-8') as f:
        f.write(content)

write_tpl('quotation_form.html', q_form)
write_tpl('sales_order_form.html', s_form)
write_tpl('delivery_note_form.html', d_form)

print('Forms created from sales_form_v2 base.')
