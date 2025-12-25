import re

path = r'C:\agri_crm\templates\transactions\invoice_detail.html'

print(f"Reading {path}...")
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

original_content = content

# Pattern 1: Fix {{ variable }} tags split across lines (opening then newline)
# Match {{ followed by content, newline, whitespace, then closing }}
pattern1 = re.compile(r'\{\{\s*([^}]+?)\s*\n\s*([^}]*)\}\}')
def fix_tag(match):
    # Combine the parts and normalize whitespace
    parts = (match.group(1) + ' ' + match.group(2)).strip()
    parts = re.sub(r'\s+', ' ', parts)
    return '{{ ' + parts + ' }}'

content = pattern1.sub(fix_tag, content)

# Pattern 2: Fix {%...%} split across lines (e.g. {% endif %} split)
pattern2 = re.compile(r'\{%\s*([^%]+?)\s*\n\s*([^%]*)\%\}')
def fix_block_tag(match):
    parts = (match.group(1) + ' ' + match.group(2)).strip()
    parts = re.sub(r'\s+', ' ', parts)
    return '{% ' + parts + ' %}'

content = pattern2.sub(fix_block_tag, content)

if content != original_content:
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print("File written successfully with fixes applied.")
else:
    print("No changes needed.")

# Verification
print("\nVerifying - checking for any remaining split tags:")
issues = re.findall(r'\{[%{][^\}]+\n', content)
if issues:
    print("Still found issues:")
    for i in issues:
        print(repr(i))
else:
    print("No split tags found. Template should be clean!")
