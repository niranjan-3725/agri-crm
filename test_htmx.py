import os
import django
from django.test import RequestFactory

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from master_data.views import CategoryListView

def test_htmx():
    factory = RequestFactory()
    # Simulate HTMX request with 'HX-Request: true' header
    # In WSGI, headers are HTTP_UPPERCASE_WITH_UNDERSCORES
    request = factory.get('/masters/categories/?q=test', HTTP_HX_REQUEST='true')
    
    view = CategoryListView.as_view()
    response = view(request)
    
    content = response.content.decode('utf-8')
    print("--- RESPONSE START ---")
    print(content[:500])
    print("--- RESPONSE END ---")

    if "<!DOCTYPE html>" in content or "<html" in content:
        print("FAIL: Full page returned")
    elif "rounded-3xl" in content or "No categories" in content:
         print("PASS: Partial returned")
    else:
         print("UNKNOWN: content weird")

if __name__ == "__main__":
    test_htmx()
