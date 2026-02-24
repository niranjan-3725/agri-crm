import os

TEMPLATES_DIR = r'c:\agri_crm\templates\transactions'

# Update purchase_form.html
form_path = os.path.join(TEMPLATES_DIR, 'purchase_form.html')
with open(form_path, 'r', encoding='utf-8') as f:
    form_text = f.read()

alert_html = '''
            <div class="bg-blue-50 border border-blue-200 text-blue-800 p-6 rounded-2xl flex items-start gap-4 mb-8 shadow-sm">
                <div class="bg-blue-100 p-2 rounded-xl mt-0.5">
                    <svg class="w-6 h-6 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
                    </svg>
                </div>
                <div>
                    <span class="font-bold text-lg block mb-1">Ledger & AP Impact Warning</span>
                    <span class="text-sm font-medium">Submitting this document clears the temporary SRNB liability and posts to Accounts Payable. Physical inventory deduction happens via a linked Purchase Receipt.</span>
                </div>
            </div>
'''

if 'Ledger & AP Impact Warning' not in form_text:
    form_text = form_text.replace('<form method="post"', alert_html + '\n            <form method="post"')

hidden_inputs = '''
            <input type="hidden" name="source_purchase_order_id" value="{{ source_purchase_order_id|default:'' }}">
            <input type="hidden" name="source_purchase_receipt_id" value="{{ source_purchase_receipt_id|default:'' }}">
'''

if 'source_purchase_order_id' not in form_text:
    form_text = form_text.replace('{% csrf_token %}', '{% csrf_token %}\n' + hidden_inputs)

with open(form_path, 'w', encoding='utf-8') as f:
    f.write(form_text)


# Update purchase_detail.html
detail_path = os.path.join(TEMPLATES_DIR, 'purchase_detail.html')
with open(detail_path, 'r', encoding='utf-8') as f:
    detail_text = f.read()

header_html = '''
    <div class="flex items-start justify-between">
        <div>
            <h1 class="text-3xl md:text-5xl font-bold text-gray-900 tracking-tight flex items-center gap-4">
                {{ invoice.supplier.name }}
            </h1>
'''

linked_docs = '''
            {% if invoice.purchase_order %}
            <div class="mt-4">
                <a href="{% url 'purchase_order_detail' invoice.purchase_order.id %}" class="inline-flex items-center gap-2 px-3 py-1.5 bg-blue-50 text-blue-700 text-sm font-bold rounded-lg border border-blue-100 hover:bg-blue-100 transition-colors">
                    <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1"/></svg>
                    Generated from Purchase Order #{{ invoice.purchase_order.id }}
                </a>
            </div>
            {% endif %}
            {% if invoice.purchase_receipt %}
            <div class="mt-2">
                <a href="{% url 'purchase_receipt_detail' invoice.purchase_receipt.id %}" class="inline-flex items-center gap-2 px-3 py-1.5 bg-violet-50 text-violet-700 text-sm font-bold rounded-lg border border-violet-100 hover:bg-violet-100 transition-colors">
                     <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1"/></svg>
                     Generated from Purchase Receipt #{{ invoice.purchase_receipt.id }}
                </a>
            </div>
            {% endif %}
'''
if 'Generated from Purchase Order' not in detail_text:
    detail_text = detail_text.replace('</h1>', '</h1>' + linked_docs)

# Updating the items loop to cleanly split tax-exclusive vs tax amount
item_card_old = '''                        <div class="grid grid-cols-2 lg:grid-cols-4 gap-4 mt-4">
                            <div>
                                <p class="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-1">Quantity</p>
                                <p class="text-base font-bold text-gray-900">{{ item.quantity }}</p>
                            </div>
                            <div>
                                <p class="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-1">Rate</p>
                                <p class="text-base font-bold text-gray-900">₹{{ item.basic_rate|intcomma }}</p>
                            </div>
                            <div>
                                <p class="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-1">Tax</p>
                                <p class="text-base font-bold text-gray-900">₹{{ item.tax_amount|intcomma }}</p>
                            </div>
                            <div class="lg:text-right">
                                <p class="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-1">Total</p>
                                <p class="text-lg font-bold text-blue-600">₹{{ item.total_amount|intcomma }}</p>
                            </div>
                        </div>'''

item_card_new = '''                        <div class="grid grid-cols-2 lg:grid-cols-4 gap-4 mt-4 bg-gray-50/50 p-4 rounded-xl border border-gray-100/50">
                            <div>
                                <p class="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-1">Quantity</p>
                                <p class="text-base font-bold text-gray-900">{{ item.quantity }}</p>
                            </div>
                            <div class="bg-white p-2 rounded-lg border border-gray-100 shadow-sm">
                                <p class="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-1 text-blue-600">Tax-Exclusive Base Rate</p>
                                <p class="text-base font-bold text-gray-900 text-blue-900">₹{{ item.basic_rate|intcomma }}</p>
                            </div>
                            <div>
                                <p class="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-1">Tax Amount</p>
                                <p class="text-base font-bold text-gray-500">₹{{ item.tax_amount|intcomma }}</p>
                            </div>
                            <div class="lg:text-right flex flex-col justify-end">
                                <p class="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-1">Line Total</p>
                                <p class="text-lg font-bold text-gray-900">₹{{ item.total_amount|intcomma }}</p>
                            </div>
                        </div>'''

if 'Tax-Exclusive Base Rate' not in detail_text:
    detail_text = detail_text.replace(item_card_old, item_card_new)

with open(detail_path, 'w', encoding='utf-8') as f:
    f.write(detail_text)

print('Forms explicitly updated with UI alerts and features.')
