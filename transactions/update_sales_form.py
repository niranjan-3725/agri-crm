import os

fp = r'c:\agri_crm\templates\transactions\sales_form_v2.html'
with open(fp, 'r', encoding='utf-8') as f:
    text = f.read()

alert_html = '''
            <div class="bg-blue-50 border border-blue-200 text-blue-800 p-6 rounded-2xl flex items-start gap-4 mb-8 shadow-sm">
                <div class="bg-blue-100 p-2 rounded-xl mt-0.5">
                    <svg class="w-6 h-6 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
                    </svg>
                </div>
                <div>
                    <span class="font-bold text-lg block mb-1">Ledger Impact Warning</span>
                    <span class="text-sm font-medium">Submitting this document strictly posts Accounts Receivable & Revenue to the General Ledgers. Physical inventory deduction happens via a linked Delivery Note.</span>
                </div>
            </div>
'''
if 'Ledger Impact Warning' not in text:
    text = text.replace('<form method="POST"', alert_html + '<form method="POST"')

hidden_inputs = '''
                <input type="hidden" name="delivery_note_id" value="{{ delivery_note_id|default:'' }}">
                <input type="hidden" name="sales_order_id" value="{{ sales_order_id|default:'' }}">
'''
if 'name="delivery_note_id"' not in text:
    text = text.replace('{% csrf_token %}', '{% csrf_token %}' + hidden_inputs)

with open(fp, 'w', encoding='utf-8') as f:
    f.write(text)
print('Updated sales_form_v2.html')
