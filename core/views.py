from django.shortcuts import render
from django.utils import timezone
from django.db.models import Sum, F, ExpressionWrapper, DecimalField
from datetime import timedelta
from decimal import Decimal
import json

from inventory.models import Batch, StockMovement
from transactions.models import SalesInvoice, SalesItem, PurchaseInvoice
from accounting.models import GLEntry


def dashboard(request):
    today             = timezone.now().date()
    yesterday         = today - timedelta(days=1)
    thirty_days_ago   = today - timedelta(days=30)
    thirty_days_later = today + timedelta(days=30)
    sixty_days_ago    = today - timedelta(days=60)
    seven_days_ago    = today - timedelta(days=6)

    # ── Query 1: Revenue & Profit ──────────────────────────────────────────
    _cogs_expr = ExpressionWrapper(
        F('quantity') * F('batch__purchase_price'),
        output_field=DecimalField(max_digits=15, decimal_places=2),
    )

    def _day_agg(date):
        return SalesItem.objects.filter(
            invoice__status='ACTIVE', invoice__date=date
        ).aggregate(revenue=Sum('total_amount'), cogs=Sum(_cogs_expr))

    today_agg     = _day_agg(today)
    yesterday_agg = _day_agg(yesterday)

    revenue_today     = today_agg['revenue']     or Decimal('0')
    cogs_today        = today_agg['cogs']        or Decimal('0')
    profit_today      = revenue_today - cogs_today
    revenue_yesterday = yesterday_agg['revenue'] or Decimal('0')

    revenue_trend = 'up' if revenue_today >= revenue_yesterday else 'down'
    if revenue_yesterday > 0:
        revenue_delta_pct = round(
            float(abs(revenue_today - revenue_yesterday)) / float(revenue_yesterday) * 100, 1
        )
    else:
        revenue_delta_pct = None

    # ── Query 2: Unbilled SRNB Liability (GL-authoritative) ───────────────
    srnb_gl = GLEntry.objects.filter(
        account__name='Stock Received But Not Billed'
    ).aggregate(dr=Sum('debit'), cr=Sum('credit'))
    srnb_balance = (srnb_gl['cr'] or 0) - (srnb_gl['dr'] or 0)
    pending_finalization_count = PurchaseInvoice.objects.filter(status='RECEIVED').count()

    # ── Query 3: Inventory Alerts ─────────────────────────────────────────
    low_stock_count   = Batch.objects.filter(current_quantity__lt=10, is_active=True).count()
    low_stock_batches = (
        Batch.objects
        .filter(current_quantity__gt=0, current_quantity__lt=10, is_active=True)
        .select_related('product')
        .order_by('current_quantity')[:6]
    )
    expiring_soon_count = Batch.objects.filter(
        expiry_date__range=[today, thirty_days_later],
        is_active=True, current_quantity__gt=0,
    ).count()

    # Dead stock: active, in-stock batches with no outward movement in 60 days
    recently_moved_ids = StockMovement.objects.filter(
        created_at__date__gte=sixty_days_ago, quantity__lt=0,
    ).values_list('batch_id', flat=True)
    dead_stock_count = (
        Batch.objects
        .filter(is_active=True, current_quantity__gt=0)
        .exclude(id__in=recently_moved_ids)
        .count()
    )

    # ── Query 4: Top 5 Products by Gross Margin (30-day window) ──────────
    top_products = list(
        SalesItem.objects
        .filter(invoice__date__gte=thirty_days_ago, invoice__status='ACTIVE')
        .values('batch__product__name')
        .annotate(
            revenue=Sum('total_amount'),
            cogs=Sum(_cogs_expr),
        )
        .annotate(
            margin=ExpressionWrapper(
                F('revenue') - F('cogs'),
                output_field=DecimalField(max_digits=15, decimal_places=2),
            )
        )
        .order_by('-margin')[:5]
    )
    max_margin = max((float(p['margin'] or 0) for p in top_products), default=1) or 1
    for p in top_products:
        m = float(p['margin'] or 0)
        r = float(p['revenue'] or 0)
        p['bar_pct']    = int(m / max_margin * 100) if max_margin else 0
        p['margin_pct'] = round(m / r * 100, 1) if r else 0

    # ── Query 5: 7-Day Sales Trend (Chart.js) ─────────────────────────────
    daily_qs = list(
        SalesInvoice.objects
        .filter(date__gte=seven_days_ago, status='ACTIVE')
        .values('date')
        .annotate(total=Sum('grand_total'))
        .order_by('date')
    )
    chart_labels = [
        (seven_days_ago + timedelta(days=i)).strftime('%d %b') for i in range(7)
    ]
    daily_map  = {row['date'].strftime('%d %b'): float(row['total'] or 0) for row in daily_qs}
    chart_data = [daily_map.get(lbl, 0) for lbl in chart_labels]

    context = {
        # Revenue / Profit
        'revenue_today':      revenue_today,
        'profit_today':       profit_today,
        'revenue_yesterday':  revenue_yesterday,
        'revenue_trend':      revenue_trend,
        'revenue_delta_pct':  revenue_delta_pct,
        # Unbilled liability
        'srnb_balance':               srnb_balance,
        'pending_finalization_count': pending_finalization_count,
        # Inventory
        'low_stock_count':    low_stock_count,
        'low_stock_batches':  low_stock_batches,
        'expiring_soon_count': expiring_soon_count,
        'dead_stock_count':   dead_stock_count,
        # Top products
        'top_products': top_products,
        # Chart
        'chart_labels_json': json.dumps(chart_labels),
        'chart_data_json':   json.dumps(chart_data),
    }
    return render(request, 'core/dashboard.html', context)
