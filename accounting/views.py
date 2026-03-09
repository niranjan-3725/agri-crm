"""
accounting.views
~~~~~~~~~~~~~~~~

Sprint 19: General Ledger UI.

Three views:
  general_ledger          — paginated, filterable GL table + Pattern-6 summary cards
  resolve_source_document — router: reference_type + reference_id -> source document detail
  validate_ledger         — HTMX partial: runs Rule-15 health checks inline
"""

import urllib.parse
from decimal import Decimal

from django.core.paginator import Paginator
from django.db.models import DecimalField, ExpressionWrapper, F, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import NoReverseMatch, reverse

from .models import Account, GLEntry


# ── Jump-to-Source Route Map ──────────────────────────────────────────────────
#
# Maps reference_type -> (url_name, kwarg_name).
# Every submitted document type that generates GL entries must appear here.

_DETAIL_ROUTE_MAP = {
    'SalesInvoice':    ('invoice_detail',         'pk'),
    'PurchaseInvoice': ('purchase_detail',         'pk'),
    'SalesReturn':     ('sales_return_detail',     'pk'),
    'PurchaseReturn':  ('purchase_return_detail',  'pk'),
    'CustomerPayment': ('customer_payment_detail', 'pk'),
    'SupplierPayment': ('supplier_payment_detail', 'pk'),
    'DeliveryNote':    ('delivery_note_detail',    'pk'),
    'PurchaseReceipt': ('purchase_receipt_detail', 'pk'),
}

# Cancel vouchers carry the same document PK as their base type — redirect there.
_CANCEL_TO_BASE = {
    'DeliveryNoteCancel':    'DeliveryNote',
    'PurchaseReceiptCancel': 'PurchaseReceipt',
    'SalesReturnCancel':     'SalesReturn',
    'PurchaseReturnCancel':  'PurchaseReturn',
}

_PAGE_SIZE = 50


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_gl_queryset(params):
    """Return a filtered, created_at-ascending GLEntry queryset from GET params."""
    qs = GLEntry.objects.select_related('account').order_by('created_at', 'pk')

    date_from    = params.get('date_from', '').strip()
    date_to      = params.get('date_to', '').strip()
    account_id   = params.get('account_id', '').strip()
    voucher_type = params.get('voucher_type', '').strip()
    ref_id       = params.get('ref_id', '').strip()
    q            = params.get('q', '').strip()

    if date_from:
        qs = qs.filter(created_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(created_at__date__lte=date_to)
    if account_id:
        qs = qs.filter(account_id=account_id)
    if voucher_type:
        qs = qs.filter(reference_type=voucher_type)
    if ref_id:
        qs = qs.filter(reference_id=ref_id)
    if q:
        qs = qs.filter(Q(remarks__icontains=q) | Q(account__name__icontains=q))

    return qs


def _attach_running_balance(entries_list):
    """Add a ``running_balance`` Decimal attribute to each entry (in-place).

    Entries must already be sorted by (created_at, pk) ascending so the
    running balance accumulates in chronological order.
    """
    balance = Decimal('0.00')
    for entry in entries_list:
        balance += (entry.debit or Decimal('0')) - (entry.credit or Decimal('0'))
        entry.running_balance = balance
    return entries_list


# ── Views ─────────────────────────────────────────────────────────────────────

def general_ledger(request):
    """Phase 1 — General Ledger dashboard.

    Supports URL-based filters: date_from, date_to, account_id, voucher_type,
    ref_id, q (full-text on remarks / account name).
    Shows Pattern-6 summary cards, a paginated running-balance table, and a
    Validate Ledger button that loads Rule-15 audit results via HTMX.
    """
    qs = _build_gl_queryset(request.GET)

    # Aggregate totals on the full filtered queryset (before pagination)
    agg          = qs.aggregate(total_debit=Sum('debit'), total_credit=Sum('credit'))
    total_debit  = agg['total_debit']  or Decimal('0.00')
    total_credit = agg['total_credit'] or Decimal('0.00')
    total_entries = qs.count()

    # Running balance must be computed on the full ordered list before slicing
    all_entries = list(qs)
    _attach_running_balance(all_entries)

    paginator = Paginator(all_entries, _PAGE_SIZE)
    page_obj  = paginator.get_page(request.GET.get('page', 1))

    # Dropdown data for filter controls
    accounts = Account.objects.order_by('account_type', 'name')
    voucher_types = (
        GLEntry.objects
        .values_list('reference_type', flat=True)
        .distinct()
        .order_by('reference_type')
    )

    # Build pagination query string (all current params except 'page')
    qs_params        = {k: v for k, v in request.GET.items() if k != 'page'}
    pagination_qstr  = urllib.parse.urlencode(qs_params)
    # pagination_prefix: ready to append "page=N" — includes trailing "&" when non-empty
    pagination_prefix = (pagination_qstr + '&') if pagination_qstr else ''

    return render(request, 'accounting/general_ledger.html', {
        'page_obj':          page_obj,
        'total_debit':       total_debit,
        'total_credit':      total_credit,
        'total_entries':     total_entries,
        'net_balance':       total_debit - total_credit,
        'accounts':          accounts,
        'voucher_types':     voucher_types,
        'active_filters':    {k: v for k, v in request.GET.items() if v and k != 'page'},
        'pagination_prefix': pagination_prefix,
        # Pre-fill filter form fields
        'f_date_from':       request.GET.get('date_from', ''),
        'f_date_to':         request.GET.get('date_to', ''),
        'f_account_id':      request.GET.get('account_id', ''),
        'f_voucher_type':    request.GET.get('voucher_type', ''),
        'f_ref_id':          request.GET.get('ref_id', ''),
        'f_q':               request.GET.get('q', ''),
        'single_account':    bool(request.GET.get('account_id', '').strip()),
    })


def resolve_source_document(request, reference_type, reference_id):
    """Phase 2 — Jump-to-source router.

    Redirects to the correct document detail page for any GL reference_type.
    Cancel variants are mapped to their base document (same PK, different page).
    StockReconciliation resolves via DB lookup to the batch_detail page.
    Unknown types fall back to the GL filtered by that voucher/ref pair.
    """
    # Normalise cancel variants -> base type (the document PK is unchanged)
    base_type = _CANCEL_TO_BASE.get(reference_type, reference_type)

    # StockReconciliation lives inside batch_detail — look up the batch
    if base_type == 'StockReconciliation':
        from inventory.models import StockReconciliation
        recon = get_object_or_404(StockReconciliation, pk=reference_id)
        return redirect('batch_detail', recon.batch_id)

    route = _DETAIL_ROUTE_MAP.get(base_type)
    if route is None:
        # Unknown type — filter the GL page to this voucher so user can see what it is
        fallback = reverse('general_ledger') + f'?voucher_type={reference_type}&ref_id={reference_id}'
        return redirect(fallback)

    url_name, kwarg_name = route
    try:
        url = reverse(url_name, kwargs={kwarg_name: reference_id})
    except NoReverseMatch:
        url = reverse('general_ledger') + f'?voucher_type={reference_type}&ref_id={reference_id}'

    return redirect(url)


def validate_ledger(request):
    """HTMX endpoint — Rule-15 health checks, returns HTML partial.

    Runs four checks:
      1. Double-entry balance (Dr == Cr per voucher group)
      2. Inventory MAP value vs GL 'Stock In Hand' balance
      3. Cancelled payments have zero net GL
      4. No orphaned GL entries (source document deleted)
    """
    from inventory.models import StockBin
    from transactions.models import (
        CustomerPayment, DeliveryNote, PurchaseInvoice,
        PurchaseReceipt, PurchaseReturn, SalesInvoice,
        SalesReturn, SupplierPayment,
    )

    results  = []
    all_pass = True
    THRESHOLD = Decimal('1.00')

    def check(label, passed, detail=''):
        nonlocal all_pass
        if not passed:
            all_pass = False
        results.append({'label': label, 'passed': passed, 'detail': detail})

    # ── Check 1: Double-entry balance ────────────────────────────────────────
    unbalanced = []
    for g in (
        GLEntry.objects
        .values('reference_type', 'reference_id')
        .annotate(total_debit=Sum('debit'), total_credit=Sum('credit'))
    ):
        diff = abs(
            (g['total_debit']  or Decimal('0'))
            - (g['total_credit'] or Decimal('0'))
        )
        if diff > THRESHOLD:
            unbalanced.append(
                f"{g['reference_type']}#{g['reference_id']} delta={diff}"
            )
    check(
        'Double-entry balance (Dr == Cr per voucher)',
        len(unbalanced) == 0,
        'All GL groups balance.' if not unbalanced else '; '.join(unbalanced),
    )

    # ── Check 2: Inventory MAP value vs GL 'Stock In Hand' ───────────────────
    map_value = (
        StockBin.objects
        .filter(actual_qty__gt=0)
        .annotate(
            bin_value=ExpressionWrapper(
                F('actual_qty') * F('batch__product__moving_average_price'),
                output_field=DecimalField(max_digits=15, decimal_places=2),
            )
        )
        .aggregate(total=Sum('bin_value'))['total']
    ) or Decimal('0.00')

    try:
        sih_account = Account.objects.get(name='Stock In Hand')
        gl_sih = GLEntry.objects.filter(account=sih_account).aggregate(
            total_debit=Sum('debit'), total_credit=Sum('credit'),
        )
        gl_balance = (
            (gl_sih['total_debit']  or Decimal('0'))
            - (gl_sih['total_credit'] or Decimal('0'))
        )
        diff = abs(map_value - gl_balance)
        check(
            'Inventory valuation (MAP vs GL Stock In Hand)',
            diff <= THRESHOLD,
            f'StockBin MAP Rs.{map_value:,.2f}  |  GL Rs.{gl_balance:,.2f}  |  Delta Rs.{diff:,.2f}',
        )
    except Account.DoesNotExist:
        check(
            'Inventory valuation (MAP vs GL Stock In Hand)',
            False,
            "'Stock In Hand' account not found in chart of accounts.",
        )

    # ── Check 3: Cancelled payments have zero net GL ──────────────────────────
    bad_payments = []
    for DocModel, rtype in [
        (CustomerPayment, 'CustomerPayment'),
        (SupplierPayment, 'SupplierPayment'),
    ]:
        for pay in DocModel.objects.filter(status='CANCELLED'):
            rows = GLEntry.objects.filter(reference_type=rtype, reference_id=pay.id)
            dr = rows.aggregate(s=Sum('debit'))['s']  or Decimal('0')
            cr = rows.aggregate(s=Sum('credit'))['s'] or Decimal('0')
            if abs(dr - cr) > THRESHOLD:
                bad_payments.append(f"{rtype}#{pay.id}")
    check(
        'Cancelled payments have zero net GL',
        len(bad_payments) == 0,
        'All cancelled payments are clean.' if not bad_payments else '; '.join(bad_payments),
    )

    # ── Check 4: No orphaned GL entries ──────────────────────────────────────
    DOC_MODEL_MAP = {
        'SalesInvoice':    SalesInvoice,
        'PurchaseInvoice': PurchaseInvoice,
        'SalesReturn':     SalesReturn,
        'PurchaseReturn':  PurchaseReturn,
        'CustomerPayment': CustomerPayment,
        'SupplierPayment': SupplierPayment,
        'DeliveryNote':    DeliveryNote,
        'PurchaseReceipt': PurchaseReceipt,
    }
    orphans = []
    for ref_type, DocModel in DOC_MODEL_MAP.items():
        gl_ids = set(
            GLEntry.objects
            .filter(reference_type=ref_type)
            .values_list('reference_id', flat=True)
            .distinct()
        )
        if not gl_ids:
            continue
        existing = set(DocModel.objects.filter(pk__in=gl_ids).values_list('pk', flat=True))
        for oid in sorted(gl_ids - existing):
            orphans.append(f"{ref_type}#{oid}")
    check(
        'No orphaned GL entries',
        len(orphans) == 0,
        'No orphaned entries found.' if not orphans else '; '.join(orphans),
    )

    return render(request, 'accounting/validate_ledger_partial.html', {
        'results':  results,
        'all_pass': all_pass,
    })
