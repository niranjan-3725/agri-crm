path = r'C:\agri_crm\templates\transactions\sales_form.html'

# Read file
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# --- FIX ALL SPLIT TEMPLATE TAGS ---

# Fix 1: H1 tag (lines 18-19)
content = content.replace(
    '<h1 class="text-4xl md:text-5xl font-bold text-gray-900 tracking-tight">{% if invoice %}Edit Sale{% else\n                    %}New Sale{% endif %}</h1>',
    '<h1 class="text-4xl md:text-5xl font-bold text-gray-900 tracking-tight">{% if invoice %}Edit Sale{% else %}New Sale{% endif %}</h1>'
)

# Fix 2: P tag (lines 20-21)
content = content.replace(
    '<p class="text-gray-500">{% if invoice %}Modify sales invoice #{{ invoice.invoice_number }}{% else\n                    %}Create a new sales invoice{% endif %}</p>',
    '<p class="text-gray-500">{% if invoice %}Modify sales invoice #{{ invoice.invoice_number }}{% else %}Create a new sales invoice{% endif %}</p>'
)

# Fix 3: existingItems (lines 343-344)
content = content.replace(
    'const existingItems = {{ existing_items_json| safe |default: "[]"\n    }};',
    'const existingItems = {{ existing_items_json|safe|default:"[]" }};'
)

# Fix 4: existingCustomer - fix { { and } }
content = content.replace(
    'const existingCustomer = {% if invoice and invoice.customer %}{ id: { { invoice.customer.id } }, name: "{{ invoice.customer.name }}", city: "{{ invoice.customer.city|default:\'\' }}", mobile_no: "{{ invoice.customer.mobile_no|default:\'\' }}" } {% else %} null{% endif %};',
    'const existingCustomer = {% if invoice and invoice.customer %}{ id: {{ invoice.customer.id }}, name: "{{ invoice.customer.name }}", city: "{{ invoice.customer.city|default:\'\' }}", mobile_no: "{{ invoice.customer.mobile_no|default:\'\' }}" }{% else %}null{% endif %};'
)

# Write back
with open(path, 'w', encoding='utf-8') as f:
    f.write(content)

print('Fixed all split template tags')

# Verify
with open(path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

print('\nLines 18-21:')
for i in range(17, 22):
    if i < len(lines):
        print(f'{i+1}: {lines[i].rstrip()[:100]}')

print('\nLines 343-346:')
for i in range(342, 347):
    if i < len(lines):
        print(f'{i+1}: {lines[i].rstrip()[:100]}')
