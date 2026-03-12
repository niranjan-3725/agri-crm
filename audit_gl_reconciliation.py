"""
AgriCRM System-Wide GL Reconciliation Audit Script
===================================================
Read-only audit ? NO data mutations.

Checks:
  1. Double-Entry Balancing  ? every GL group sums to zero (Dr == Cr)
  2. Document-to-Ledger Parity ? Invoice totals match their GL debit totals
  3. Inventory Valuation      ? StockBin MAP value vs GL 'Stock In Hand' balance
  4. Payment State Integrity  ? CANCELLED payments have zero GL; balance_due is consistent
"""

import os
import sys
import django
from decimal import Decimal

# ?? Bootstrap ??????????????????????????????????????????????????????????
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
django.setup()

from django.db.models import Sum, F, DecimalField, ExpressionWrapper
from accounting.models import GLEntry, Account
from transactions.models import (
    SalesInvoice, PurchaseInvoice,
    SalesReturn, PurchaseReturn,
    CustomerPayment, SupplierPayment,
    Quotation, SalesOrder, DeliveryNote,
    PurchaseOrder, PurchaseReceipt,
)
from inventory.models import StockBin, Batch

# ?? Helpers ?????????????????????????????????????????????????????????????
PASS  = "[PASS]"
FAIL  = "[CRITICAL ERROR]"
WARN  = "[WARN]"
THRESHOLD = Decimal('1.00')

discrepancy_tickets = []
total_errors = 0


def section(title):
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}")


def flag_critical(ticket_id, document_type, doc_id, description, raw_data=None):
    global total_errors
    total_errors += 1
    ticket = {
        'id': ticket_id,
        'type': document_type,
        'doc_id': doc_id,
        'description': description,
        'raw': raw_data,
    }
    discrepancy_tickets.append(ticket)
    print(f"  {FAIL}  [{ticket_id}]  {document_type} #{doc_id} ? {description}")
    if raw_data:
        print(f"    RAW DATA: {raw_data}")
    return ticket


# ???????????????????????????????????????????????????????????????????????
# CHECK 1: Double-Entry Balancing
# Every GLEntry group (reference_type + reference_id) must have
# Sum(debit) == Sum(credit).  Any deviation > Rs.1 is a CRITICAL ERROR.
# ???????????????????????????????????????????????????????????????????????

section("CHECK 1 ? Double-Entry Balancing (Sum(Dr) == Sum(Cr) per document)")

gl_groups = (
    GLEntry.objects
    .values('reference_type', 'reference_id')
    .annotate(
        total_debit=Sum('debit'),
        total_credit=Sum('credit'),
    )
    .order_by('reference_type', 'reference_id')
)

unbalanced_count = 0
checked_count = 0
for g in gl_groups:
    checked_count += 1
    diff = abs((g['total_debit'] or Decimal('0')) - (g['total_credit'] or Decimal('0')))
    if diff > THRESHOLD:
        unbalanced_count += 1
        flag_critical(
            f"C1-{g['reference_type']}-{g['reference_id']}",
            g['reference_type'],
            g['reference_id'],
            f"Dr={g['total_debit']}  Cr={g['total_credit']}  ?={diff}",
            raw_data=dict(g),
        )

if unbalanced_count == 0:
    print(f"  {PASS}  {checked_count} GL groups checked ? all balanced.")
else:
    print(f"  ? {unbalanced_count} unbalanced group(s) out of {checked_count} total.")


# ???????????????????????????????????????????????????????????????????????
# CHECK 2A: Sales Invoice ? Document Total vs GL AR Debit
# Every SUBMITTED SalesInvoice: grand_total must equal the GL Dr to
# Accounts Receivable for that reference_id.
# ???????????????????????????????????????????????????????????????????????

section("CHECK 2A ? SalesInvoice: grand_total == GL Accounts Receivable debit")

try:
    ar_account = Account.objects.get(name='Accounts Receivable')
except Account.DoesNotExist:
    print(f"  {WARN}  'Accounts Receivable' account not found ? skipping check 2A.")
    ar_account = None

submitted_invoices = SalesInvoice.objects.filter(status='SUBMITTED')
si_checked = 0
si_errors = 0
for inv in submitted_invoices:
    si_checked += 1
    if ar_account:
        gl_ar = (
            GLEntry.objects
            .filter(reference_type='SalesInvoice', reference_id=inv.id, account=ar_account)
            .aggregate(total=Sum('debit'))['total']
        ) or Decimal('0.00')
    else:
        gl_ar = Decimal('0.00')

    diff = abs(Decimal(str(inv.grand_total)) - gl_ar)
    if diff > THRESHOLD:
        si_errors += 1
        flag_critical(
            f"C2A-SI-{inv.id}",
            'SalesInvoice',
            inv.id,
            f"grand_total={inv.grand_total}  GL AR debit={gl_ar}  ?={diff}  [{inv.invoice_number}]",
            raw_data={
                'invoice_id': inv.id,
                'invoice_number': inv.invoice_number,
                'grand_total': str(inv.grand_total),
                'gl_ar_debit': str(gl_ar),
                'delta': str(diff),
            }
        )

if si_errors == 0:
    print(f"  {PASS}  {si_checked} SUBMITTED SalesInvoices verified.")
else:
    print(f"  ? {si_errors} mismatch(es) out of {si_checked} SalesInvoices.")


# ???????????????????????????????????????????????????????????????????????
# CHECK 2B: Purchase Invoice ? total_amount vs GL AP Credit
# ???????????????????????????????????????????????????????????????????????

section("CHECK 2B ? PurchaseInvoice: total_amount == GL Accounts Payable credit")

try:
    ap_account = Account.objects.get(name='Accounts Payable')
except Account.DoesNotExist:
    print(f"  {WARN}  'Accounts Payable' account not found ? skipping check 2B.")
    ap_account = None

submitted_purchases = PurchaseInvoice.objects.filter(status='SUBMITTED')
pi_checked = 0
pi_errors = 0
for inv in submitted_purchases:
    pi_checked += 1
    if ap_account:
        gl_ap = (
            GLEntry.objects
            .filter(reference_type='PurchaseInvoice', reference_id=inv.id, account=ap_account)
            .aggregate(total=Sum('credit'))['total']
        ) or Decimal('0.00')
    else:
        gl_ap = Decimal('0.00')

    diff = abs(Decimal(str(inv.total_amount)) - gl_ap)
    if diff > THRESHOLD:
        pi_errors += 1
        flag_critical(
            f"C2B-PI-{inv.id}",
            'PurchaseInvoice',
            inv.id,
            f"total_amount={inv.total_amount}  GL AP credit={gl_ap}  ?={diff}  [{inv.invoice_number}]",
            raw_data={
                'invoice_id': inv.id,
                'invoice_number': inv.invoice_number,
                'total_amount': str(inv.total_amount),
                'gl_ap_credit': str(gl_ap),
                'delta': str(diff),
            }
        )

if pi_errors == 0:
    print(f"  {PASS}  {pi_checked} SUBMITTED PurchaseInvoices verified.")
else:
    print(f"  ? {pi_errors} mismatch(es) out of {pi_checked} PurchaseInvoices.")


# ???????????????????????????????????????????????????????????????????????
# CHECK 2C: SalesReturn ? GL Credit Notes (AR Credit) integrity
# ???????????????????????????????????????????????????????????????????????

section("CHECK 2C ? SalesReturn: GL Accounts Receivable credit > 0 for SUBMITTED returns")

submitted_sreturns = SalesReturn.objects.filter(status='SUBMITTED')
sr_checked = 0
sr_errors = 0
for ret in submitted_sreturns:
    sr_checked += 1
    if ar_account:
        gl_ar_cr = (
            GLEntry.objects
            .filter(reference_type='SalesReturn', reference_id=ret.id, account=ar_account)
            .aggregate(total=Sum('credit'))['total']
        ) or Decimal('0.00')
    else:
        gl_ar_cr = None

    # Only flag if AR account exists AND credit is unexpectedly zero
    if ar_account and gl_ar_cr == Decimal('0.00'):
        sr_errors += 1
        flag_critical(
            f"C2C-SR-{ret.id}",
            'SalesReturn',
            ret.id,
            f"SUBMITTED SalesReturn has no AR credit GL entries ? possible orphan",
            raw_data={'return_id': ret.id, 'gl_ar_credit': '0.00'}
        )

if sr_errors == 0:
    print(f"  {PASS}  {sr_checked} SUBMITTED SalesReturns verified (AR credit entries exist).")
else:
    print(f"  ? {sr_errors} missing GL entries out of {sr_checked} SalesReturns.")


# ???????????????????????????????????????????????????????????????????????
# CHECK 2D: PurchaseReturn ? GL Debit Notes (AP Debit) integrity
# ???????????????????????????????????????????????????????????????????????

section("CHECK 2D ? PurchaseReturn: GL Accounts Payable debit > 0 for SUBMITTED returns")

submitted_preturns = PurchaseReturn.objects.filter(status='SUBMITTED')
pr_checked = 0
pr_errors = 0
for ret in submitted_preturns:
    pr_checked += 1
    if ap_account:
        gl_ap_dr = (
            GLEntry.objects
            .filter(reference_type='PurchaseReturn', reference_id=ret.id, account=ap_account)
            .aggregate(total=Sum('debit'))['total']
        ) or Decimal('0.00')
    else:
        gl_ap_dr = None

    if ap_account and gl_ap_dr == Decimal('0.00'):
        pr_errors += 1
        flag_critical(
            f"C2D-PR-{ret.id}",
            'PurchaseReturn',
            ret.id,
            f"SUBMITTED PurchaseReturn has no AP debit GL entries ? possible orphan",
            raw_data={'return_id': ret.id, 'gl_ap_debit': '0.00'}
        )

if pr_errors == 0:
    print(f"  {PASS}  {pr_checked} SUBMITTED PurchaseReturns verified (AP debit entries exist).")
else:
    print(f"  ? {pr_errors} missing GL entries out of {pr_checked} PurchaseReturns.")


# ???????????????????????????????????????????????????????????????????????
# CHECK 3: Inventory Valuation ? StockBin MAP Value vs GL 'Stock In Hand'
# Compare: Sum(StockBin.actual_qty * Product.moving_average_price)
#      vs: GL 'Stock In Hand' net balance (total_debit - total_credit)
# ???????????????????????????????????????????????????????????????????????

section("CHECK 3 ? Inventory Valuation: StockBin MAP value vs GL 'Stock In Hand' balance")

# Calculate MAP-based inventory value from StockBins
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

# Calculate net GL balance of 'Stock In Hand'
try:
    sih_account = Account.objects.get(name='Stock In Hand')
    gl_sih = GLEntry.objects.filter(account=sih_account).aggregate(
        total_debit=Sum('debit'),
        total_credit=Sum('credit'),
    )
    gl_sih_balance = (gl_sih['total_debit'] or Decimal('0')) - (gl_sih['total_credit'] or Decimal('0'))
except Account.DoesNotExist:
    print(f"  {WARN}  'Stock In Hand' GL account not found ? skipping balance comparison.")
    gl_sih_balance = None
    sih_account = None

print(f"  StockBin MAP-based inventory value : Rs.{map_value:,.2f}")
if gl_sih_balance is not None:
    print(f"  GL 'Stock In Hand' net balance     : Rs.{gl_sih_balance:,.2f}")
    diff = abs(map_value - gl_sih_balance)
    print(f"  ? Difference                       : Rs.{diff:,.2f}")
    if diff > THRESHOLD:
        flag_critical(
            "C3-INV-VALUATION",
            'Inventory',
            0,
            f"StockBin MAP value Rs.{map_value:,.2f} ? GL Stock In Hand Rs.{gl_sih_balance:,.2f}  ?=Rs.{diff:,.2f}",
            raw_data={
                'map_inventory_value': str(map_value),
                'gl_stock_in_hand_balance': str(gl_sih_balance),
                'delta': str(diff),
                'note': (
                    'Expected divergence if the Purchase Receipt ? PurchaseInvoice '
                    'SDNB-clearance pattern is in use. '
                    'SRNB is an intermediate staging account and is NOT "Stock In Hand".'
                )
            }
        )
    else:
        print(f"  {PASS}  Inventory valuation is within Rs.{THRESHOLD} tolerance.")


# ???????????????????????????????????????????????????????????????????????
# CHECK 4A: CustomerPayment ? CANCELLED must have zero net GL impact
# ???????????????????????????????????????????????????????????????????????

section("CHECK 4A ? CustomerPayment: CANCELLED payments have zero net GL impact")

cancelled_cps = CustomerPayment.objects.filter(status='CANCELLED')
cp_cancelled_checked = 0
cp_cancelled_errors = 0
for pay in cancelled_cps:
    cp_cancelled_checked += 1
    gl_rows = GLEntry.objects.filter(reference_type='CustomerPayment', reference_id=pay.id)
    total_dr = gl_rows.aggregate(s=Sum('debit'))['s'] or Decimal('0')
    total_cr = gl_rows.aggregate(s=Sum('credit'))['s'] or Decimal('0')
    net = abs(total_dr - total_cr)
    if net > THRESHOLD:
        cp_cancelled_errors += 1
        flag_critical(
            f"C4A-CP-{pay.id}",
            'CustomerPayment',
            pay.id,
            f"CANCELLED payment has non-zero net GL ?=Rs.{net} (Dr={total_dr}, Cr={total_cr})",
            raw_data={
                'payment_id': pay.id,
                'status': pay.status,
                'amount': str(pay.amount),
                'gl_total_debit': str(total_dr),
                'gl_total_credit': str(total_cr),
                'net_impact': str(net),
            }
        )

if cp_cancelled_errors == 0:
    print(f"  {PASS}  {cp_cancelled_checked} CANCELLED CustomerPayments ? zero net GL impact confirmed.")
else:
    print(f"  ? {cp_cancelled_errors} orphaned GL entries in CANCELLED CustomerPayments.")


# ???????????????????????????????????????????????????????????????????????
# CHECK 4B: SupplierPayment ? CANCELLED must have zero net GL impact
# ???????????????????????????????????????????????????????????????????????

section("CHECK 4B ? SupplierPayment: CANCELLED payments have zero net GL impact")

cancelled_sps = SupplierPayment.objects.filter(status='CANCELLED')
sp_cancelled_checked = 0
sp_cancelled_errors = 0
for pay in cancelled_sps:
    sp_cancelled_checked += 1
    gl_rows = GLEntry.objects.filter(reference_type='SupplierPayment', reference_id=pay.id)
    total_dr = gl_rows.aggregate(s=Sum('debit'))['s'] or Decimal('0')
    total_cr = gl_rows.aggregate(s=Sum('credit'))['s'] or Decimal('0')
    net = abs(total_dr - total_cr)
    if net > THRESHOLD:
        sp_cancelled_errors += 1
        flag_critical(
            f"C4B-SP-{pay.id}",
            'SupplierPayment',
            pay.id,
            f"CANCELLED payment has non-zero net GL ?=Rs.{net} (Dr={total_dr}, Cr={total_cr})",
            raw_data={
                'payment_id': pay.id,
                'status': pay.status,
                'amount': str(pay.amount),
                'gl_total_debit': str(total_dr),
                'gl_total_credit': str(total_cr),
                'net_impact': str(net),
            }
        )

if sp_cancelled_errors == 0:
    print(f"  {PASS}  {sp_cancelled_checked} CANCELLED SupplierPayments ? zero net GL impact confirmed.")
else:
    print(f"  ? {sp_cancelled_errors} orphaned GL entries in CANCELLED SupplierPayments.")


# ???????????????????????????????????????????????????????????????????????
# CHECK 4C: CustomerPayment SUBMITTED ? balance_due consistency
# invoice.balance_due must equal invoice.grand_total - sum(SUBMITTED payments)
# ???????????????????????????????????????????????????????????????????????

section("CHECK 4C ? CustomerPayment: balance_due == grand_total - sum(SUBMITTED payments)")

submitted_invoices_cp = SalesInvoice.objects.filter(status='SUBMITTED')
cp_bd_checked = 0
cp_bd_errors = 0
for inv in submitted_invoices_cp:
    cp_bd_checked += 1
    computed_paid = (
        inv.payments.filter(status='SUBMITTED').aggregate(total=Sum('amount'))['total']
    ) or Decimal('0.00')
    computed_balance = Decimal(str(inv.grand_total)) - computed_paid
    stored_balance = Decimal(str(inv.balance_due))
    diff = abs(computed_balance - stored_balance)
    if diff > THRESHOLD:
        cp_bd_errors += 1
        flag_critical(
            f"C4C-SI-{inv.id}",
            'SalesInvoice',
            inv.id,
            f"balance_due mismatch: stored={stored_balance}  computed={computed_balance}  ?={diff}  [{inv.invoice_number}]",
            raw_data={
                'invoice_id': inv.id,
                'invoice_number': inv.invoice_number,
                'grand_total': str(inv.grand_total),
                'stored_balance_due': str(stored_balance),
                'computed_balance_due': str(computed_balance),
                'total_submitted_payments': str(computed_paid),
                'delta': str(diff),
            }
        )

if cp_bd_errors == 0:
    print(f"  {PASS}  {cp_bd_checked} SalesInvoices ? balance_due is consistent with SUBMITTED payments.")
else:
    print(f"  ? {cp_bd_errors} balance_due discrepancies in SalesInvoices.")


# ???????????????????????????????????????????????????????????????????????
# CHECK 4D: SupplierPayment SUBMITTED ? balance_due consistency
# invoice.balance_due must equal invoice.total_amount - sum(SUBMITTED payments)
# ???????????????????????????????????????????????????????????????????????

section("CHECK 4D ? SupplierPayment: balance_due == total_amount - sum(SUBMITTED payments)")

submitted_purchases_sp = PurchaseInvoice.objects.filter(status='SUBMITTED')
sp_bd_checked = 0
sp_bd_errors = 0
for inv in submitted_purchases_sp:
    sp_bd_checked += 1
    computed_paid = (
        inv.payments.filter(status='SUBMITTED').aggregate(total=Sum('amount'))['total']
    ) or Decimal('0.00')
    computed_balance = Decimal(str(inv.total_amount)) - computed_paid
    stored_balance = Decimal(str(inv.balance_due))
    diff = abs(computed_balance - stored_balance)
    if diff > THRESHOLD:
        sp_bd_errors += 1
        flag_critical(
            f"C4D-PI-{inv.id}",
            'PurchaseInvoice',
            inv.id,
            f"balance_due mismatch: stored={stored_balance}  computed={computed_balance}  ?={diff}  [{inv.invoice_number}]",
            raw_data={
                'invoice_id': inv.id,
                'invoice_number': inv.invoice_number,
                'total_amount': str(inv.total_amount),
                'stored_balance_due': str(stored_balance),
                'computed_balance_due': str(computed_balance),
                'total_submitted_payments': str(computed_paid),
                'delta': str(diff),
            }
        )

if sp_bd_errors == 0:
    print(f"  {PASS}  {sp_bd_checked} PurchaseInvoices ? balance_due is consistent with SUBMITTED payments.")
else:
    print(f"  ? {sp_bd_errors} balance_due discrepancies in PurchaseInvoices.")


# ???????????????????????????????????????????????????????????????????????
# CHECK 5: Orphaned GL Entries (no matching source document found)
# reference_type/reference_id combos where the source document was deleted
# ???????????????????????????????????????????????????????????????????????

section("CHECK 5 ? Orphaned GL Entries (source document deleted / hard-deleted)")

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

orphan_count = 0
for ref_type, Model in DOC_MODEL_MAP.items():
    # Get all distinct reference_ids in GL for this type
    gl_ids = (
        GLEntry.objects
        .filter(reference_type=ref_type)
        .values_list('reference_id', flat=True)
        .distinct()
    )
    if not gl_ids:
        continue
    existing_ids = set(Model.objects.filter(pk__in=list(gl_ids)).values_list('pk', flat=True))
    gl_id_set = set(gl_ids)
    orphan_ids = gl_id_set - existing_ids
    for oid in sorted(orphan_ids):
        orphan_count += 1
        gl_for_orphan = GLEntry.objects.filter(reference_type=ref_type, reference_id=oid)
        dr = gl_for_orphan.aggregate(s=Sum('debit'))['s'] or Decimal('0')
        cr = gl_for_orphan.aggregate(s=Sum('credit'))['s'] or Decimal('0')
        flag_critical(
            f"C5-ORPHAN-{ref_type}-{oid}",
            ref_type,
            oid,
            f"GL entries reference a deleted {ref_type} (Dr={dr}, Cr={cr})",
            raw_data={
                'reference_type': ref_type,
                'reference_id': oid,
                'gl_entry_count': gl_for_orphan.count(),
                'total_debit': str(dr),
                'total_credit': str(cr),
            }
        )

if orphan_count == 0:
    print(f"  {PASS}  No orphaned GL entries found across all document types.")
else:
    print(f"  ? {orphan_count} orphaned GL entry group(s) found.")


# ???????????????????????????????????????????????????????????????????????
# SUMMARY REPORT
# ???????????????????????????????????????????????????????????????????????

section("AUDIT SUMMARY")

if total_errors == 0:
    print("""
  +------------------------------------------------------------------+
  |  [PASS]  CLEAN BILL OF HEALTH                                    |
  |                                                                  |
  |  All General Ledger checks passed:                               |
  |    - Double-entry balance: CLEAN                                 |
  |    - Document-to-ledger parity: CLEAN                            |
  |    - Inventory valuation: CLEAN                                  |
  |    - Payment state integrity: CLEAN                              |
  |    - No orphaned GL entries: CLEAN                               |
  +------------------------------------------------------------------+
""")
else:
    print(f"\n  {FAIL}  {total_errors} discrepancy ticket(s) raised:\n")
    for i, t in enumerate(discrepancy_tickets, 1):
        print(f"  [{i:02d}] Ticket {t['id']}")
        print(f"       Type   : {t['type']} #{t['doc_id']}")
        print(f"       Issue  : {t['description']}")
        if t.get('raw'):
            print(f"       Raw DB : {t['raw']}")
        print()

print("\n  Audit complete. Report generated by audit_gl_reconciliation.py\n")
