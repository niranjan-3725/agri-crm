from django.shortcuts import render
from django.db.models import Q, Sum, F
from django.core.paginator import Paginator
from django.utils import timezone
from .models import Batch

def inventory_list(request):
    batches = Batch.objects.select_related('product', 'product__category').all().order_by('product__name', 'batch_number')
    
    # Filters
    query = request.GET.get('q')
    if query:
        batches = batches.filter(
            Q(product__name__icontains=query) |
            Q(batch_number__icontains=query)
        )
    
    status = request.GET.get('status')
    today = timezone.now().date()
    
    if status == 'low':
        batches = batches.filter(current_quantity__lt=10, current_quantity__gt=0)
    elif status == 'out':
        batches = batches.filter(current_quantity=0)
    elif status == 'expired':
        batches = batches.filter(expiry_date__lt=today)
        
    # Calculate Total Stock Value
    total_value_data = batches.aggregate(total_value=Sum(F('current_quantity') * F('purchase_price')))
    total_stock_value = total_value_data['total_value'] or 0
    
    # Annotate row value for the template
    batches = batches.annotate(stock_value=F('current_quantity') * F('purchase_price'))
    
    # Pagination
    paginator = Paginator(batches, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'batches': page_obj,
        'total_stock_value': total_stock_value,
        'q': query,
        'status': status,
        'today': today,
    }
    
    if request.headers.get('HX-Request'):
        return render(request, 'inventory/partials/inventory_table.html', context)
        
    return render(request, 'inventory/inventory_list.html', context)
