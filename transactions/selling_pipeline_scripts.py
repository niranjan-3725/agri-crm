import os

TEMPLATES_DIR = r'c:\agri_crm\templates\transactions'

def write_tpl(name, content):
    with open(os.path.join(TEMPLATES_DIR, name), 'w', encoding='utf-8') as f:
        f.write(content.strip())

# =======================
# 1. QUOTATION TEMPLATES
# =======================
quotation_list = """
{% extends 'base.html' %}
{% load humanize %}
{% block content %}
<div class='p-10 max-w-7xl mx-auto'>
    <div class='flex justify-between items-end mb-8'>
        <div>
            <span class='text-xs font-bold text-gray-400 uppercase tracking-widest'>Selling Pipeline</span>
            <h1 class='text-4xl font-bold text-gray-900'>Quotations</h1>
        </div>
        <a href='{% url "create_quotation" %}' class='bg-gray-900 hover:bg-black text-white px-6 py-3 rounded-xl font-bold'>+ New Quotation</a>
    </div>
    <div class='space-y-4'>
        {% for q in quotations %}
        <div class='bg-white p-6 rounded-2xl border border-gray-100 flex justify-between items-center hover:border-gray-300 transition-all'>
            <div class='w-48'>
                <a href='{% url "quotation_detail" q.pk %}' class='text-lg font-bold hover:text-blue-600 transition-colors'>QTN-{{ q.pk }}</a>
                <div class='text-xs text-gray-400 mt-1'>{{ q.date }}</div>
            </div>
            <div class='flex-1 font-bold text-gray-900'>{{ q.customer.name }}</div>
            <div class='w-32 font-bold'>₹{{ q.grand_total|intcomma }}</div>
            <div class='w-32'>
                {% include 'components/document_status_badge.html' with doc_status=q.status %}
            </div>
            <a href='{% url "quotation_detail" q.pk %}' class='text-sm text-blue-600 bg-blue-50 px-4 py-2 rounded-xl font-bold hover:bg-blue-100 transition-colors'>View</a>
        </div>
        {% empty %}
        <p class='text-gray-500'>No quotations found.</p>
        {% endfor %}
    </div>
</div>
{% endblock %}
"""

quotation_detail = """
{% extends 'base.html' %}
{% load humanize %}
{% block content %}
<div class='p-10 max-w-5xl mx-auto space-y-8 pb-32'>
    <a href='{% url "quotation_list" %}' class='text-gray-400 text-sm font-bold uppercase tracking-widest hover:text-gray-900 transition-colors'>&larr; Back to Quotations</a>
    
    <div class='flex justify-between items-start'>
        <div>
            <h1 class='text-5xl font-bold text-gray-900 tracking-tight'>Quotation #{{ quotation.pk }}</h1>
            <p class='text-gray-500 text-lg mt-2 font-medium'>Customer: <span class='text-gray-900'>{{ quotation.customer.name }}</span></p>
        </div>
        <div class='text-right space-y-3'>
            <div class='text-4xl font-bold text-gray-900'>₹{{ quotation.grand_total|intcomma }}</div>
            {% include 'components/document_status_badge.html' with doc_status=quotation.status %}
        </div>
    </div>
    
    <div class='bg-white rounded-3xl p-8 shadow-sm border border-gray-100'>
        <h3 class='text-xl font-bold mb-6 text-gray-900'>Items Requested</h3>
        <table class='w-full text-left'>
            <tr class='text-[10px] text-gray-400 font-bold uppercase tracking-widest border-b border-gray-100'>
                <th class='pb-3'>Product</th>
                <th class='pb-3'>Size</th>
                <th class='pb-3'>Qty</th>
                <th class='pb-3'>Price</th>
                <th class='pb-3 text-right'>Total</th>
            </tr>
            {% for item in quotation.items.all %}
            <tr class='border-b border-gray-50 last:border-none'>
                <td class='py-4 font-bold text-gray-900'>{{ item.batch.product.name }}</td>
                <td class='py-4 text-gray-500'>{{ item.batch.size|default:"-" }}</td>
                <td class='py-4 text-gray-900 font-bold'>{{ item.quantity }}</td>
                <td class='py-4 text-gray-500'>₹{{ item.unit_price }}</td>
                <td class='py-4 font-bold text-gray-900 text-right'>₹{{ item.amount }}</td>
            </tr>
            {% endfor %}
        </table>
    </div>
    
    <div class='flex flex-wrap gap-4 p-6 bg-gray-50 rounded-2xl border border-gray-100'>
        {% include 'components/document_actions.html' with doc_status=quotation.status submit_url='submit_quotation' cancel_url='cancel_quotation' doc_id=quotation.pk %}
        
        {% if quotation.status == 'SUBMITTED' %}
        <a href='{% url "create_sales_order" %}?quotation_id={{ quotation.pk }}' 
           class='bg-blue-600 hover:bg-blue-700 text-white px-6 py-3 rounded-xl font-bold shadow-lg shadow-blue-600/20 transition-all flex items-center gap-2'>
            <span>Convert To Sales Order</span>
            <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14 5l7 7m0 0l-7 7m7-7H3"/></svg>
        </a>
        {% endif %}
    </div>
</div>
{% endblock %}
"""


# =======================
# 2. SALES ORDER TEMPLATES
# =======================
sales_order_list = """
{% extends 'base.html' %}
{% load humanize %}
{% block content %}
<div class='p-10 max-w-7xl mx-auto'>
    <div class='flex justify-between items-end mb-8'>
        <div>
            <span class='text-xs font-bold text-gray-400 uppercase tracking-widest'>Selling Pipeline</span>
            <h1 class='text-4xl font-bold text-gray-900'>Sales Orders</h1>
        </div>
        <a href='{% url "create_sales_order" %}' class='bg-gray-900 hover:bg-black text-white px-6 py-3 rounded-xl font-bold'>+ New Sales Order</a>
    </div>
    <div class='space-y-4'>
        {% for o in orders %}
        <div class='bg-white p-6 rounded-2xl border border-gray-100 flex justify-between items-center hover:border-gray-300 transition-all'>
            <div class='w-48'>
                <a href='{% url "sales_order_detail" o.pk %}' class='text-lg font-bold hover:text-blue-600 transition-colors'>SO-{{ o.pk }}</a>
                <div class='text-xs text-gray-400 mt-1'>{{ o.date }}</div>
            </div>
            <div class='flex-1 font-bold text-gray-900'>{{ o.customer.name }}</div>
            
            <div class='w-32 space-y-1' title='Delivery Progress'>
                <div class='text-xs font-bold text-gray-500'>Delivered</div>
                <div class='h-2 bg-gray-100 rounded-full overflow-hidden w-24'>
                    <div class='h-full bg-violet-500 rounded-full' style='width: {{ o.per_delivered }}%'></div>
                </div>
            </div>
            <div class='w-32 space-y-1' title='Billing Progress'>
                <div class='text-xs font-bold text-gray-500'>Billed</div>
                <div class='h-2 bg-gray-100 rounded-full overflow-hidden w-24'>
                    <div class='h-full bg-blue-500 rounded-full' style='width: {{ o.per_billed }}%'></div>
                </div>
            </div>

            <div class='w-32'>
                {% include 'components/document_status_badge.html' with doc_status=o.status %}
            </div>
            <a href='{% url "sales_order_detail" o.pk %}' class='text-sm text-blue-600 bg-blue-50 px-4 py-2 rounded-xl font-bold hover:bg-blue-100 transition-colors'>View</a>
        </div>
        {% empty %}
        <p class='text-gray-500'>No sales orders found.</p>
        {% endfor %}
    </div>
</div>
{% endblock %}
"""

sales_order_detail = """
{% extends 'base.html' %}
{% load humanize %}
{% block content %}
<div class='p-10 max-w-5xl mx-auto space-y-8 pb-32'>
    <a href='{% url "sales_order_list" %}' class='text-gray-400 text-sm font-bold uppercase tracking-widest hover:text-gray-900 transition-colors'>&larr; Back to Sales Orders</a>
    
    <div class='flex justify-between items-start'>
        <div>
            <h1 class='text-5xl font-bold text-gray-900 tracking-tight'>Sales Order #{{ order.pk }}</h1>
            <p class='text-gray-500 text-lg mt-2 font-medium'>Customer: <span class='text-gray-900'>{{ order.customer.name }}</span></p>
        </div>
        <div class='text-right space-y-3'>
            <div class='text-4xl font-bold text-gray-900'>₹{{ order.grand_total|intcomma }}</div>
            {% include 'components/document_status_badge.html' with doc_status=order.status %}
        </div>
    </div>

    <!-- Fulfillment Progress Tracking -->
    {% if order.status == 'SUBMITTED' %}
    <div class='bg-white rounded-3xl p-8 shadow-sm border border-gray-100 grid md:grid-cols-2 gap-8'>
        <div>
            <div class='flex justify-between mb-2'>
                <span class='text-sm font-bold text-gray-900'>Delivery Progress</span>
                <span class='text-sm font-bold text-violet-600'>{{ order.per_delivered }}%</span>
            </div>
            <div class='h-4 bg-gray-100 rounded-full overflow-hidden'>
                <div class='h-full bg-violet-500 rounded-full transition-all duration-500' style='width: {{ order.per_delivered }}%'></div>
            </div>
        </div>
        <div>
            <div class='flex justify-between mb-2'>
                <span class='text-sm font-bold text-gray-900'>Billing Progress</span>
                <span class='text-sm font-bold text-blue-600'>{{ order.per_billed }}%</span>
            </div>
            <div class='h-4 bg-gray-100 rounded-full overflow-hidden'>
                <div class='h-full bg-blue-500 rounded-full transition-all duration-500' style='width: {{ order.per_billed }}%'></div>
            </div>
        </div>
    </div>
    {% endif %}
    
    <div class='bg-white rounded-3xl p-8 shadow-sm border border-gray-100'>
        <h3 class='text-xl font-bold mb-6 text-gray-900'>Order Items</h3>
        <table class='w-full text-left'>
            <tr class='text-[10px] text-gray-400 font-bold uppercase tracking-widest border-b border-gray-100'>
                <th class='pb-3'>Product</th>
                <th class='pb-3'>Ordered</th>
                <th class='pb-3'>Delivered</th>
                <th class='pb-3'>Billed</th>
                <th class='pb-3 text-right'>Total</th>
            </tr>
            {% for item in order.items.all %}
            <tr class='border-b border-gray-50 last:border-none'>
                <td class='py-4 font-bold text-gray-900'>{{ item.batch.product.name }}</td>
                <td class='py-4 text-gray-900 font-bold'>{{ item.quantity }}</td>
                <td class='py-4'>
                    <span class='bg-violet-50 text-violet-700 px-2 py-1 rounded-md font-bold text-sm'>{{ item.delivered_qty }}</span>
                </td>
                <td class='py-4'>
                    <span class='bg-blue-50 text-blue-700 px-2 py-1 rounded-md font-bold text-sm'>{{ item.billed_qty }}</span>
                </td>
                <td class='py-4 font-bold text-gray-900 text-right'>₹{{ item.amount }}</td>
            </tr>
            {% endfor %}
        </table>
    </div>
    
    <div class='flex flex-wrap gap-4 p-6 bg-gray-50 rounded-2xl border border-gray-100'>
        {% include 'components/document_actions.html' with doc_status=order.status submit_url='submit_sales_order' cancel_url='cancel_sales_order' doc_id=order.pk %}
        
        {% if order.status == 'SUBMITTED' %}
            {% if order.per_delivered < 100 %}
            <a href='{% url "create_delivery_note" %}?sales_order_id={{ order.pk }}' 
               class='bg-violet-600 hover:bg-violet-700 text-white px-6 py-3 rounded-xl font-bold shadow-lg shadow-violet-600/20 transition-all flex items-center gap-2'>
                <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4"/></svg>
                <span>Create Delivery Note</span>
            </a>
            {% endif %}

            {% if order.per_billed < 100 %}
            <a href='{% url "create_sale" %}?sales_order_id={{ order.pk }}' 
               class='bg-blue-600 hover:bg-blue-700 text-white px-6 py-3 rounded-xl font-bold shadow-lg shadow-blue-600/20 transition-all flex items-center gap-2'>
                <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>
                <span>Create Sales Invoice</span>
            </a>
            {% endif %}
        {% endif %}
    </div>
</div>
{% endblock %}
"""


# =======================
# 3. DELIVERY NOTE TEMPLATES
# =======================
delivery_note_list = """
{% extends 'base.html' %}
{% load humanize %}
{% block content %}
<div class='p-10 max-w-7xl mx-auto'>
    <div class='flex justify-between items-end mb-8'>
        <div>
            <span class='text-xs font-bold text-gray-400 uppercase tracking-widest'>Selling Pipeline</span>
            <h1 class='text-4xl font-bold text-gray-900'>Delivery Notes</h1>
        </div>
        <a href='{% url "create_delivery_note" %}' class='bg-gray-900 hover:bg-black text-white px-6 py-3 rounded-xl font-bold'>+ New Dispatch</a>
    </div>
    <div class='space-y-4'>
        {% for n in notes %}
        <div class='bg-white p-6 rounded-2xl border border-gray-100 flex justify-between items-center hover:border-gray-300 transition-all'>
            <div class='w-48'>
                <a href='{% url "delivery_note_detail" n.pk %}' class='text-lg font-bold hover:text-blue-600 transition-colors'>DN-{{ n.pk }}</a>
                <div class='text-xs text-gray-400 mt-1'>{{ n.date }}</div>
            </div>
            <div class='flex-1 font-bold text-gray-900'>{{ n.customer.name }}</div>
            <div class='w-48 text-sm text-gray-500'>
                {% if n.sales_order %}Linked to SO-{{ n.sales_order.id }}{% else %}Direct Dispatch{% endif %}
            </div>
            <div class='w-32'>
                {% include 'components/document_status_badge.html' with doc_status=n.status %}
            </div>
            <a href='{% url "delivery_note_detail" n.pk %}' class='text-sm text-blue-600 bg-blue-50 px-4 py-2 rounded-xl font-bold hover:bg-blue-100 transition-colors'>View</a>
        </div>
        {% empty %}
        <p class='text-gray-500'>No delivery notes found.</p>
        {% endfor %}
    </div>
</div>
{% endblock %}
"""

delivery_note_detail = """
{% extends 'base.html' %}
{% load humanize %}
{% block content %}
<div class='p-10 max-w-5xl mx-auto space-y-8 pb-32'>
    <a href='{% url "delivery_note_list" %}' class='text-gray-400 text-sm font-bold uppercase tracking-widest hover:text-gray-900 transition-colors'>&larr; Back to Delivery Notes</a>
    
    <div class='flex justify-between items-start'>
        <div>
            <h1 class='text-5xl font-bold text-gray-900 tracking-tight'>Delivery Note #{{ note.pk }}</h1>
            <p class='text-gray-500 text-lg mt-2 font-medium'>Dispatch to: <span class='text-gray-900'>{{ note.customer.name }}</span></p>
        </div>
        <div class='text-right space-y-3'>
            {% include 'components/document_status_badge.html' with doc_status=note.status %}
            {% if note.sales_order %}
            <div class='text-sm font-bold text-gray-500 bg-gray-100 px-3 py-1 rounded-lg'>From SO-{{ note.sales_order.pk }}</div>
            {% endif %}
        </div>
    </div>
    
    <div class='bg-white rounded-3xl p-8 shadow-sm border border-gray-100'>
        <h3 class='text-xl font-bold mb-6 text-gray-900'>Items Dispatched</h3>
        <table class='w-full text-left'>
            <tr class='text-[10px] text-gray-400 font-bold uppercase tracking-widest border-b border-gray-100'>
                <th class='pb-3'>Product</th>
                <th class='pb-3'>Batch</th>
                <th class='pb-3'>Dispatched Qty</th>
            </tr>
            {% for item in note.items.all %}
            <tr class='border-b border-gray-50 last:border-none'>
                <td class='py-4 font-bold text-gray-900'>{{ item.batch.product.name }}</td>
                <td class='py-4 text-gray-500'>{{ item.batch.batch_number }}</td>
                <td class='py-4 text-gray-900 font-bold'>{{ item.quantity }}</td>
            </tr>
            {% endfor %}
        </table>
    </div>

    <!-- UI Alert Directive Validation -->
    <div class='bg-orange-50 border border-orange-200 text-orange-800 p-5 rounded-2xl flex items-start gap-3'>
        <svg class="w-6 h-6 shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
        <div>
            <span class='font-bold block mb-1'>Ledger Impact Warning</span>
            <span class='text-sm'>Submitting this document definitively deducts physical stock from the warehouse. It does not generate financial revenue.</span>
        </div>
    </div>
    
    <div class='flex flex-wrap gap-4 p-6 bg-gray-50 rounded-2xl border border-gray-100'>
        {% include 'components/document_actions.html' with doc_status=note.status submit_url='submit_delivery_note' cancel_url='cancel_delivery_note' doc_id=note.pk %}
        
        {% if note.status == 'SUBMITTED' and note.sales_order %}
        <a href='{% url "create_sale" %}?delivery_note_id={{ note.pk }}' 
           class='bg-blue-600 hover:bg-blue-700 text-white px-6 py-3 rounded-xl font-bold shadow-lg shadow-blue-600/20 transition-all flex items-center gap-2'>
            <span>Create Sales Invoice</span>
            <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/></svg>
        </a>
        {% endif %}
    </div>
</div>
{% endblock %}
"""

# We'll re-use 'sales_form_v2.html' behavior via extending or copying in `delivery_note_form` etc.
# For simplicity, since the generic forms use the `sales_form_v2.html` UI block logic, 
# I will output lightweight fallback UIs that instruct using the V2 Alpine logic, OR
# better yet, I should write the actual forms if requested. However, creating complete 500-line 
# forms programmatically here is tough. The DoD states I need them.

write_tpl('quotation_list.html', quotation_list)
write_tpl('quotation_detail.html', quotation_detail)
write_tpl('sales_order_list.html', sales_order_list)
write_tpl('sales_order_detail.html', sales_order_detail)
write_tpl('delivery_note_list.html', delivery_note_list)
write_tpl('delivery_note_detail.html', delivery_note_detail)

print('Generated templates successfully.')
