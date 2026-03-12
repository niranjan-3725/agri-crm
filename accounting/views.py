"""
accounting.views
~~~~~~~~~~~~~~~~

Sprint 19 / 19.1 / 19.2: General Ledger UI.

Three views:
  general_ledger          — paginated, filterable GL table with Transaction Threading
  resolve_source_document — router: reference_type + reference_id -> source document detail
  validate_ledger         — HTMX partial: runs Rule-15 health checks inline

Threading: PurchaseInvoice ← PurchaseReceipt (FK) and SalesInvoice ← DeliveryNote (FK)
are merged into a single "Audit Group" card so related physical + financial events
appear as one coherent business transaction.
"""

import re
import urllib.parse
from decimal import Decimal
from itertools import groupby as _groupby

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

_PAGE_SIZE = 20

# ── Voucher display metadata ───────────────────────────────────────────────────

_VOUCHER_DISPLAY = {
    'SalesInvoice':          'Sales Invoice',
    'DeliveryNote':          'Delivery Note',
    'DeliveryNoteCancel':    'Delivery Note (Cancel)',
    'CustomerPayment':       'Customer Payment',
    'PurchaseInvoice':       'Purchase Invoice',
    'PurchaseReceipt':       'Purchase Receipt',
    'PurchaseReceiptCancel': 'Purchase Receipt (Cancel)',
    'SupplierPayment':       'Supplier Payment',
    'SalesReturn':           'Sales Return',
    'SalesReturnCancel':     'Sales Return (Cancel)',
    'PurchaseReturn':        'Purchase Return',
    'PurchaseReturnCancel':  'Purchase Return (Cancel)',
    'StockReconciliation':   'Stock Reconciliation',
}

_VOUCHER_BADGE = {
    'SalesInvoice':          'bg-blue-50 text-blue-700',
    'DeliveryNote':          'bg-blue-50 text-blue-700',
    'DeliveryNoteCancel':    'bg-gray-100 text-gray-500',
    'CustomerPayment':       'bg-emerald-50 text-emerald-700',
    'PurchaseInvoice':       'bg-amber-50 text-amber-700',
    'PurchaseReceipt':       'bg-amber-50 text-amber-700',
    'PurchaseReceiptCancel': 'bg-gray-100 text-gray-500',
    'SupplierPayment':       'bg-orange-50 text-orange-700',
    'SalesReturn':           'bg-rose-50 text-rose-700',
    'SalesReturnCancel':     'bg-gray-100 text-gray-500',
    'PurchaseReturn':        'bg-rose-50 text-rose-700',
    'PurchaseReturnCancel':  'bg-gray-100 text-gray-500',
    'StockReconciliation':   'bg-violet-50 text-violet-700',
}

_DEFAULT_BADGE = 'bg-gray-100 text-gray-600'


# ── Helpers ───────────────────────────────────────────────────────────────────


def _group_entries(entries_with_balance):
    """Group a running-balance-annotated list of entries into voucher groups.

    Returns a list of dicts — one per (reference_type, reference_id) pair —
    with pre-computed group totals, balanced flag, and the entry sub-list.
    Input must already be sorted by (created_at, pk) ascending.
    """
    groups = []
    for (ref_type, ref_id), group_iter in _groupby(
        entries_with_balance,
        key=lambda e: (e.reference_type, e.reference_id),
    ):
        entries = list(group_iter)
        total_dr = sum((e.debit  or Decimal('0.00') for e in entries), Decimal('0.00'))
        total_cr = sum((e.credit or Decimal('0.00') for e in entries), Decimal('0.00'))
        groups.append({
            'reference_type':      ref_type,
            'reference_id':        ref_id,
            'display_name':        _VOUCHER_DISPLAY.get(ref_type)
                                   or re.sub(r'([A-Z])', r' \1', ref_type).strip(),
            'badge_class':         _VOUCHER_BADGE.get(ref_type, _DEFAULT_BADGE),
            'date':                entries[0].created_at,
            'entry_count':         len(entries),
            'total_debit':         total_dr,
            'total_credit':        total_cr,
            'balanced':            abs(total_dr - total_cr) < Decimal('0.01'),
            'entries':             entries,
            'end_running_balance': entries[-1].running_balance,
        })
    return groups

def _build_audit_groups(voucher_groups):
    """Second-pass grouping: thread related vouchers into a single Audit Group.

    Supported threads (uses FK on the financial document):
      PurchaseInvoice.purchase_receipt  →  bundles PurchaseReceipt entries first
      SalesInvoice.delivery_note        →  bundles DeliveryNote entries first

    Algorithm (two-pass to avoid ordering bugs):
      Pass 1 — query domain models to discover which receipt/DN groups are
               absorbed into their parent invoice; build ``absorbed_keys`` set.
      Pass 2 — iterate voucher_groups in chronological order, emit one
               audit-group dict per transaction (skipping absorbed groups).

    Returns a list of audit-group dicts with keys:
      master_type, master_id, label, party, amount, date,
      badge_class, display_name, is_threaded, voucher_groups,
      total_entries, doc_count
    """
    # Index all voucher groups for O(1) lookup
    group_index    = {(g['reference_type'], g['reference_id']): g for g in voucher_groups}
    absorbed_keys  = set()   # (ref_type, ref_id) pairs that appear inside a parent group

    # ── Pass 1: Discover purchase-cycle threads ───────────────────────────────
    pi_ids = [g['reference_id'] for g in voucher_groups if g['reference_type'] == 'PurchaseInvoice']
    invoice_meta = {}
    if pi_ids:
        from transactions.models import PurchaseInvoice
        for row in (
            PurchaseInvoice.objects
            .filter(pk__in=pi_ids)
            .select_related('supplier')
            .values('pk', 'invoice_number', 'purchase_receipt_id', 'total_amount', 'supplier__name')
        ):
            invoice_meta[row['pk']] = row
            if row['purchase_receipt_id']:
                absorbed_keys.add(('PurchaseReceipt', row['purchase_receipt_id']))

    # ── Pass 1: Discover sales-cycle threads ─────────────────────────────────
    si_ids = [g['reference_id'] for g in voucher_groups if g['reference_type'] == 'SalesInvoice']
    sales_meta = {}
    if si_ids:
        from transactions.models import SalesInvoice
        for row in (
            SalesInvoice.objects
            .filter(pk__in=si_ids)
            .select_related('customer')
            .values('pk', 'invoice_number', 'delivery_note_id', 'grand_total', 'customer__name')
        ):
            sales_meta[row['pk']] = row
            if row['delivery_note_id']:
                absorbed_keys.add(('DeliveryNote', row['delivery_note_id']))

    # ── Pass 2: Emit audit groups ─────────────────────────────────────────────
    audit_groups = []

    for group in voucher_groups:
        key      = (group['reference_type'], group['reference_id'])
        ref_type = group['reference_type']
        ref_id   = group['reference_id']

        if key in absorbed_keys:
            continue  # this group is a sub-section inside its parent invoice

        # ── Purchase cycle ────────────────────────────────────────────────────
        if ref_type == 'PurchaseInvoice' and ref_id in invoice_meta:
            meta       = invoice_meta[ref_id]
            receipt_id = meta['purchase_receipt_id']
            rcpt_group = group_index.get(('PurchaseReceipt', receipt_id)) if receipt_id else None

            sub_groups = []
            if rcpt_group:
                sub_groups.append(rcpt_group)   # physical doc first
            sub_groups.append(group)             # financial doc last

            audit_groups.append({
                'master_type':   'PurchaseInvoice',
                'master_id':     ref_id,
                'label':         meta['invoice_number'] or f'PI-{ref_id}',
                'party':         meta['supplier__name'] or '',
                'amount':        meta['total_amount'] or Decimal('0.00'),
                'date':          group['date'],
                'badge_class':   group['badge_class'],
                'display_name':  group['display_name'],
                'is_threaded':   rcpt_group is not None,
                'voucher_groups': sub_groups,
                'total_entries': sum(g['entry_count'] for g in sub_groups),
                'doc_count':     len(sub_groups),
            })

        # ── Sales cycle ───────────────────────────────────────────────────────
        elif ref_type == 'SalesInvoice' and ref_id in sales_meta:
            meta    = sales_meta[ref_id]
            dn_id   = meta['delivery_note_id']
            dn_group = group_index.get(('DeliveryNote', dn_id)) if dn_id else None

            sub_groups = []
            if dn_group:
                sub_groups.append(dn_group)   # physical doc first
            sub_groups.append(group)           # financial doc last

            audit_groups.append({
                'master_type':   'SalesInvoice',
                'master_id':     ref_id,
                'label':         meta['invoice_number'] or f'INV-{ref_id}',
                'party':         meta['customer__name'] or '',
                'amount':        meta['grand_total'] or Decimal('0.00'),
                'date':          group['date'],
                'badge_class':   group['badge_class'],
                'display_name':  group['display_name'],
                'is_threaded':   dn_group is not None,
                'voucher_groups': sub_groups,
                'total_entries': sum(g['entry_count'] for g in sub_groups),
                'doc_count':     len(sub_groups),
            })

        # ── Standalone transaction ────────────────────────────────────────────
        else:
            audit_groups.append({
                'master_type':   ref_type,
                'master_id':     ref_id,
                'label':         group['display_name'],
                'party':         '',
                'amount':        max(group['total_debit'], group['total_credit']),
                'date':          group['date'],
                'badge_class':   group['badge_class'],
                'display_name':  group['display_name'],
                'is_threaded':   False,
                'voucher_groups': [group],
                'total_entries': group['entry_count'],
                'doc_count':     1,
            })

    return audit_groups


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

    # Running balance must be computed on the full ordered list before grouping.
    # Then: voucher groups → audit groups (threading applied).
    all_entries      = list(qs)
    _attach_running_balance(all_entries)
    all_groups       = _group_entries(all_entries)
    all_audit_groups = _build_audit_groups(all_groups)

    paginator = Paginator(all_audit_groups, _PAGE_SIZE)
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
        'page_obj':           page_obj,
        'total_debit':        total_debit,
        'total_credit':       total_credit,
        'total_entries':      total_entries,
        'total_vouchers':     len(all_groups),
        'total_transactions': len(all_audit_groups),
        'net_balance':        total_debit - total_credit,
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
