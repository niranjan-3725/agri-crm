import os

path = r'C:\agri_crm\templates\transactions\invoice_detail.html'

print(f"Reading {path}...")
with open(path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Line 192 (index 191) and 193 (index 192) are the targets
# Let's inspect them
print(f"Line 192: {repr(lines[191])}")
print(f"Line 193: {repr(lines[192])}")

# Check if they match our expectation
if '{%' in lines[191] and 'endif %}' in lines[192]:
    print("Found split tag. Fixing...")
    # Remove newline from 191
    lines[191] = lines[191].rstrip()
    # Remove leading spaces from 192 and append
    lines[191] += ' ' + lines[192].strip() + '\n'
    # Delete line 192 (replace with empty string or remove)
    # Better to pop it
    lines.pop(192)
    
    # Write back
    with open(path, 'w', encoding='utf-8') as f:
        f.writelines(lines)
    print("File written successfully.")
else:
    print("Lines did not match expected pattern. No changes made.")
