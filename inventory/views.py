import datetime
import json

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.views.decorators.http import require_http_methods
from django.db.models import (
    DecimalField, ExpressionWrapper, F, Prefetch, Q, Sum,
)
from django.core.paginator import Paginator
from django.utils import timezone

from .models import Batch, StockBin, StockMovement, StockReconciliation, Warehouse
from .services import reconcile_stock, InsufficientStockError


# ── Shared MAP-value expression factory ────────────────────────────────────
# INV-01: ALL stock valuation uses moving_average_price, never purchase_price.
def _map_expr():
    """Return a fresh ExpressionWrapper for current_quantity × MAP."""
    return ExpressionWrapper(
        F('current_quantity') * F('product__moving_average_price'),
        output_field=DecimalField(max_digits=15, decimal_places=2),
    )


def _bin_prefetch():
    """Return a Prefetch that annotates each StockBin with its MAP-based value."""
    return Prefetch(
        'stock_bins',
        queryset=StockBin.objects.select_related('warehouse').annotate(
            bin_value=ExpressionWrapper(
                F('actual_qty') * F('batch__product__moving_average_price'),
                output_field=DecimalField(max_digits=15, decimal_places=2),
            )
        ),
    )


# ── inventory_list ──────────────────────────────────────────────────────────

def inventory_list(request):
    base_qs = Batch.objects.select_related(
        'product', 'product__category'
    ).prefetch_related(_bin_prefetch())

    # ---------- Filters ----------
    query = request.GET.get('q', '').strip()
    if query:
        base_qs = base_qs.filter(
            Q(product__name__icontains=query) | Q(batch_number__icontains=query)
        )

    status = request.GET.get('status', '')
    today = timezone.now().date()
    expiry_threshold = today + datetime.timedelta(days=30)

    filtered_qs = base_qs.order_by('product__name', 'batch_number')

    if status == 'low':
        filtered_qs = filtered_qs.filter(current_quantity__lt=10, current_quantity__gt=0)
    elif status == 'out':
        filtered_qs = filtered_qs.filter(current_quantity=0)
    elif status == 'expired':
        filtered_qs = filtered_qs.filter(expiry_date__lt=today)
    elif status == 'expiring':
        # INV-07 fix: 'expiring' filter covers batches within the 30-day window
        filtered_qs = filtered_qs.filter(expiry_date__gte=today, expiry_date__lte=expiry_threshold)

    # INV-01: annotate each row with MAP-based stock value
    filtered_qs = filtered_qs.annotate(stock_value=_map_expr())

    # Aggregate total over the filtered set — reuse the annotation field name
    total_stock_value = filtered_qs.aggregate(tv=Sum('stock_value'))['tv'] or 0

    # ---------- Right-Panel Stats (always over FULL unfiltered set) ----------
    all_batches = Batch.objects.all()

    low_stock_count = all_batches.filter(current_quantity__gt=0, current_quantity__lt=10).count()
    out_of_stock_count = all_batches.filter(current_quantity=0).count()
    expiring_soon_count = all_batches.filter(
        expiry_date__gte=today,
        expiry_date__lte=expiry_threshold,
    ).count()

    # INV-01: Top categories — MAP-based value
    top_categories = (
        all_batches
        .values('product__category__name')
        .annotate(
            total_value=Sum(
                ExpressionWrapper(
                    F('current_quantity') * F('product__moving_average_price'),
                    output_field=DecimalField(max_digits=15, decimal_places=2),
                )
            )
        )
        .order_by('-total_value')[:5]
    )

    total_batch_count = all_batches.count()
    warehouse_count = Warehouse.objects.count()

    # ---------- Pagination ----------
    paginator = Paginator(filtered_qs, 20)
    page_obj = paginator.get_page(request.GET.get('page'))

    context = {
        'batches': page_obj,
        'total_stock_value': total_stock_value,
        'q': query,
        'status': status,
        'today': today,
        'low_stock_count': low_stock_count,
        'out_of_stock_count': out_of_stock_count,
        'expiring_soon_count': expiring_soon_count,
        'top_categories': top_categories,
        'total_batch_count': total_batch_count,
        'warehouse_count': warehouse_count,
    }

    if request.headers.get('HX-Request'):
        return render(request, 'inventory/partials/inventory_table.html', context)

    return render(request, 'inventory/inventory_list.html', context)


# ── batch_detail ────────────────────────────────────────────────────────────

def batch_detail(request, batch_id):
    """Drill-down page: batch summary + full StockMovement ledger timeline."""
    batch = get_object_or_404(
        Batch.objects.select_related('product', 'product__category')
                     .prefetch_related(_bin_prefetch()),
        pk=batch_id,
    )
    stock_movements = (
        StockMovement.objects.filter(batch=batch)
        .select_related('warehouse', 'batch__product')
        .order_by('-created_at')[:50]
    )
    reconciliations = (
        batch.reconciliations
        .select_related('warehouse')
        .order_by('-created_at')[:10]
    )
    today = timezone.now().date()

    return render(request, 'inventory/batch_detail.html', {
        'batch': batch,
        'stock_movements': stock_movements,
        'reconciliations': reconciliations,
        'today': today,
    })


# ── stock_reconcile ─────────────────────────────────────────────────────────

@require_http_methods(["GET", "POST"])
def stock_reconcile(request, batch_id):
    """Physical stock count form. INV-04 fix: warehouse is now required."""
    batch = get_object_or_404(Batch, pk=batch_id)

    if request.method == 'POST':
        try:
            new_qty_str = request.POST.get('new_quantity', '').strip()
            reason = request.POST.get('reason', 'Count Error')
            notes = request.POST.get('notes', '')
            warehouse_id_str = request.POST.get('warehouse_id', '').strip()

            if not new_qty_str:
                raise ValueError("New quantity is required.")
            if not warehouse_id_str:
                raise ValueError("Warehouse is required.")

            new_quantity = int(new_qty_str)
            warehouse_id = int(warehouse_id_str)

            recon = reconcile_stock(
                batch_id=batch.id,
                new_quantity=new_quantity,
                reason=reason,
                notes=notes,
                warehouse_id=warehouse_id,
            )

            if recon.delta == 0:
                messages.info(
                    request,
                    f"Stock confirmed: {batch} already has {new_quantity} units "
                    f"in {recon.warehouse}. No adjustment needed.",
                )
            else:
                direction = "added" if recon.delta > 0 else "removed"
                messages.success(
                    request,
                    f"Reconciliation complete: {abs(recon.delta)} units {direction} "
                    f"for {batch} in {recon.warehouse}. New quantity: {new_quantity}.",
                )
            return redirect('inventory_list')

        except ValueError as e:
            messages.error(request, f"Invalid input: {e}")
        except InsufficientStockError as e:
            messages.error(request, f"Reconciliation failed: {e}")
        except Exception as e:
            messages.error(request, f"Unexpected error: {e}")

    # ── Build bin-qty map for Alpine.js delta preview ──────────────────────
    # INV-04: warehouse_id (string key) → actual_qty for the Alpine reactive map
    bin_qtys = {
        str(sb.warehouse_id): sb.actual_qty
        for sb in batch.stock_bins.select_related('warehouse').all()
    }
    warehouses = Warehouse.objects.filter(is_active=True)
    past_reconciliations = (
        batch.reconciliations
        .select_related('warehouse')
        .order_by('-created_at')[:10]
    )

    return render(request, 'inventory/stock_reconcile.html', {
        'batch': batch,
        'reason_choices': StockReconciliation.REASON_CHOICES,
        'past_reconciliations': past_reconciliations,
        'warehouses': warehouses,
        'bin_quantities_json': json.dumps(bin_qtys),
    })
