
import os

file_path = r'C:\agri_crm\templates\transactions\sales_form_v2.html'

if not os.path.exists(file_path):
    print("File not found!")
else:
    with open(file_path, 'rb') as f:
        content = f.read()
        print(f"File size: {len(content)}")
        # Find the header part
        start = content.find(b'<h1')
        end = content.find(b'/h1>')
        if start != -1 and end != -1:
            print(f"Header Context: {content[start:end+4]}")
        else:
            print("Header not found in first chunk")

        # Check for split tags in JS
        js_start = content.find(b'const existingItems')
        if js_start != -1:
             print(f"JS Context: {content[js_start:js_start+200]}")
