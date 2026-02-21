import datetime
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.views.decorators.http import require_http_methods
from django.db.models import Q, Sum, F
from django.core.paginator import Paginator
from django.utils import timezone
from .models import Batch, StockReconciliation
from .services import reconcile_stock, InsufficientStockError


def inventory_list(request):
    all_batches_qs = Batch.objects.select_related('product', 'product__category').all()

    # ---------- Filters ----------
    query = request.GET.get('q', '').strip()
    if query:
        all_batches_qs = all_batches_qs.filter(
            Q(product__name__icontains=query) |
            Q(batch_number__icontains=query)
        )

    status = request.GET.get('status', '')
    today = timezone.now().date()

    filtered_qs = all_batches_qs.order_by('product__name', 'batch_number')

    if status == 'low':
        filtered_qs = filtered_qs.filter(current_quantity__lt=10, current_quantity__gt=0)
    elif status == 'out':
        filtered_qs = filtered_qs.filter(current_quantity=0)
    elif status == 'expired':
        filtered_qs = filtered_qs.filter(expiry_date__lt=today)

    # ---------- Annotate row-level stock value ----------
    filtered_qs = filtered_qs.annotate(stock_value=F('current_quantity') * F('purchase_price'))

    # ---------- Aggregate KPIs (over the filtered set) ----------
    total_value_data = filtered_qs.aggregate(total_value=Sum(F('current_quantity') * F('purchase_price')))
    total_stock_value = total_value_data['total_value'] or 0

    # ---------- Right-Panel Stats (always over FULL unfiltered set) ----------
    base_qs = Batch.objects.all()
    expiry_threshold = today + datetime.timedelta(days=30)

    low_stock_count = base_qs.filter(current_quantity__gt=0, current_quantity__lt=10).count()
    out_of_stock_count = base_qs.filter(current_quantity=0).count()
    expiring_soon_count = base_qs.filter(
        expiry_date__lte=expiry_threshold,
        expiry_date__gte=today
    ).count()

    # Top 5 categories by total stock value
    top_categories = (
        base_qs
        .values('product__category__name')
        .annotate(total_value=Sum(F('current_quantity') * F('purchase_price')))
        .order_by('-total_value')[:5]
    )

    # Total count over full base (for hero card sub-line)
    total_batch_count = base_qs.count()

    # ---------- Pagination ----------
    paginator = Paginator(filtered_qs, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'batches': page_obj,
        'total_stock_value': total_stock_value,
        'q': query,
        'status': status,
        'today': today,
        # Right panel
        'low_stock_count': low_stock_count,
        'out_of_stock_count': out_of_stock_count,
        'expiring_soon_count': expiring_soon_count,
        'top_categories': top_categories,
        'total_batch_count': total_batch_count,
    }

    if request.headers.get('HX-Request'):
        return render(request, 'inventory/partials/inventory_table.html', context)

    return render(request, 'inventory/inventory_list.html', context)


@require_http_methods(["GET", "POST"])
def stock_reconcile(request, batch_id):
    """Admin view: submit a physical stock count and reconcile the batch."""
    batch = get_object_or_404(Batch, pk=batch_id)

    if request.method == 'POST':
        try:
            new_qty_str = request.POST.get('new_quantity', '').strip()
            reason = request.POST.get('reason', 'Count Error')
            notes = request.POST.get('notes', '')

            if not new_qty_str:
                raise ValueError("New quantity is required.")

            new_quantity = int(new_qty_str)
            recon = reconcile_stock(
                batch_id=batch.id,
                new_quantity=new_quantity,
                reason=reason,
                notes=notes,
            )

            if recon.delta == 0:
                messages.info(
                    request,
                    f"Stock confirmed: {batch} already has {new_quantity} units. No adjustment needed.",
                )
            else:
                direction = "added" if recon.delta > 0 else "removed"
                messages.success(
                    request,
                    f"Reconciliation complete: {abs(recon.delta)} units {direction} for {batch}. "
                    f"New quantity: {new_quantity}.",
                )
            return redirect('inventory_list')

        except ValueError as e:
            messages.error(request, f"Invalid input: {e}")
        except InsufficientStockError as e:
            messages.error(request, f"Reconciliation failed: {e}")
        except Exception as e:
            messages.error(request, f"Unexpected error: {e}")

    past_reconciliations = batch.reconciliations.order_by('-created_at')[:10]
    return render(request, 'inventory/stock_reconcile.html', {
        'batch': batch,
        'reason_choices': StockReconciliation.REASON_CHOICES,
        'past_reconciliations': past_reconciliations,
    })
