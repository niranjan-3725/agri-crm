import re
import os

files_to_fix = [
    r'c:\agri_crm\templates\transactions\wallet_passbook.html',
    r'c:\agri_crm\templates\transactions\partials\receivables_customer_list.html',
    r'c:\agri_crm\templates\transactions\receivables_dashboard.html'
]

def fix_file(filepath):
    if not os.path.exists(filepath):
        print(f"File not found: {filepath}")
        return

    print(f"Processing {filepath}...")
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Pattern to match {{ ... }} spanning multiple lines
    # (?s) enables dotall mode (dot matches newline)
    # We match {{ followed by anything (non-greedy) until }}
    
    def replacer(match):
        text = match.group(0)
        if '\n' in text:
            # Replace newlines and extra spaces with a single space
            fixed = re.sub(r'\s+', ' ', text)
            print(f"  Fixed: {fixed[:50]}...")
            return fixed
        return text

    # Fix {{ ... }}
    new_content = re.sub(r'\{\{.+?\}\}', replacer, content, flags=re.DOTALL)
    
    # Fix {% ... %}
    new_content = re.sub(r'\{%.+?%\}', replacer, new_content, flags=re.DOTALL)

    if new_content != content:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print("  Saved changes.")
    else:
        print("  No changes needed.")

if __name__ == '__main__':
    for f in files_to_fix:
        fix_file(f)
