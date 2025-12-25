import re

path = r'C:\agri_crm\templates\transactions\sales_form.html'

# Read file with explicit encoding
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Count original issues
issues_before = content.count('{ {') + content.count('} }') + content.count('| safe |')
print(f'Issues found before fix: {issues_before}')

# Fix all split braces - replace { { with {{ and } } with }}
content = content.replace('{ {', '{{')
content = content.replace('} }', '}}')

# Fix split filters - replace | safe | with |safe|
content = content.replace('| safe |', '|safe|')

# Fix default filter spacing - replace |d efault: with |default:
content = content.replace('|d efault:', '|default:')
content = content.replace('|default: ', '|default:')

# Fix split else/endif tags
content = content.replace('{% else %} ', '{% else %}')
content = content.replace(' {% endif %}', '{% endif %}')

# Fix any double newline in {{ }}
content = re.sub(r'\{\{\s*\n\s*\}\}', '}}', content)
content = re.sub(r'\{\{\s*([^}]+)\s*\n\s*\}\}', r'{{ \1 }}', content)

# Fix split default value
content = content.replace('|default:"[]"\n    }}', '|default:"[]" }}')

# Write back with explicit flush
with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
    f.flush()

# Verify changes
with open(path, 'r', encoding='utf-8') as f:
    new_content = f.read()

issues_after = new_content.count('{ {') + new_content.count('} }') + new_content.count('| safe |')
print(f'Issues after fix: {issues_after}')

# Print key lines to verify
lines = new_content.split('\n')
print(f'\nLine 343: {lines[342][:100] if len(lines) > 342 else "N/A"}')
print(f'Line 344: {lines[343][:100] if len(lines) > 343 else "N/A"}')
print(f'Line 345: {lines[344][:100] if len(lines) > 344 else "N/A"}')
print(f'Line 401: {lines[400][:100] if len(lines) > 400 else "N/A"}')
print(f'Line 402: {lines[401][:100] if len(lines) > 401 else "N/A"}')
