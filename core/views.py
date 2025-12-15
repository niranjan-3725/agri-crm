from django.shortcuts import render
from django.utils import timezone
from django.db.models import Sum
from inventory.models import Batch
from transactions.models import SalesInvoice

def dashboard(request):
    # Low Stock: Qty < 10 and Active
    low_stock_count = Batch.objects.filter(current_quantity__lt=10, is_active=True).count()
    
    # Expiring Soon: Next 30 days
    today = timezone.now().date()
    thirty_days_later = today + timezone.timedelta(days=30)
    expiring_soon = Batch.objects.filter(expiry_date__range=[today, thirty_days_later], is_active=True).count()
    
    # Today's Sales
    todays_sales = SalesInvoice.objects.filter(date=today).aggregate(Sum('grand_total'))['grand_total__sum'] or 0
    
    context = {
        'low_stock_count': low_stock_count,
        'expiring_soon': expiring_soon,
        'todays_sales': todays_sales,
    }
    return render(request, 'core/dashboard.html', context)
