import os
import re

path = r'C:\agri_crm\templates\transactions\invoice_detail.html'

print(f"Reading {path}...")
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Regex to find split template tags ({{ ... }} or {% ... %} broken across lines)
# Pattern: opening brace followed by content, then newline+whitespace, then closing
# We need to handle both {{ variable }} and {% tag %} styles

original_content = content

# Fix split {{ variable }} tags
# Match: {{ followed by content, then newline + whitespace, then more content ending with }}
pattern1 = r'\{\{\s*\n\s+'
# Replace with: {{ (no newline)
replacement1 = '{{ '
content = re.sub(pattern1, replacement1, content)

# Fix the opposite: content followed by }} on new line 
pattern2 = r'\s*\n\s*\}\}'
replacement2 = ' }}'
# Be careful with this one - only apply if there's an opening {{ on the same logical unit
# Actually let's be more targeted

# Let me use a different approach - fix specific known issues

# Reload original
content = original_content

# Known problematic lines to fix:
fixes = [
    # Line 51-52: #{{ invoice.invoice_number }} split across lines
    (r'\#\{\{\s*\n\s+invoice\.invoice_number\s+\}\}', '#{{ invoice.invoice_number }}'),
    
    # Line 108-109: {{ invoice.items.count }} split across lines  
    (r'\{\{\s*invoice\.items\.count\s*\n\s*\}\}', '{{ invoice.items.count }}'),
    
    # Line 132-133: {{ item.batch.expiry_date|date:"M y" }} split across lines
    (r'\{\{\s*\n\s+item\.batch\.expiry_date\|date:"M y"\s*\}\}', '{{ item.batch.expiry_date|date:"M y" }}'),
    
    # Line 190-191: {{ payment.payment_mode }} split across lines
    (r'\{\{\s*\n\s+payment\.payment_mode\s*\}\}', '{{ payment.payment_mode }}'),
]

for pattern, replacement in fixes:
    if re.search(pattern, content):
        print(f"Found and fixing: {pattern[:50]}...")
        content = re.sub(pattern, replacement, content)
    else:
        print(f"Pattern not found: {pattern[:50]}...")

if content != original_content:
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print("File written successfully.")
else:
    print("No changes made.")
