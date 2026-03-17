"""
Full purchase/return/cancel/sales lifecycle test + GL audit.
Run: python run_lifecycle_test.py
"""
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django
django.setup()

from decimal import Decimal
from django.utils import timezone
from master_data.models import Product, Supplier, Customer
from inventory.models import Batch, Warehouse
from transactions.models import (
    PurchaseInvoice, PurchaseItem, PurchaseReturn, PurchaseReturnItem,
    SalesInvoice, SalesItem,
)
from accounting.models import GLEntry
from collections import defaultdict

PROD  = Product.objects.get(id=10)   # Avtar, MAP=632
SUPP  = Supplier.objects.get(id=1)   # Indofil Industries Limited
CUST  = Customer.objects.get(id=1)   # Niranjan Kumar M
WH    = Warehouse.objects.get(id=1)  # Main Warehouse
TODAY = timezone.now().date()

SEP = "=" * 100
results = {}   # label -> bool


def show_gl(label, ref_type, ref_id):
    entries = list(
        GLEntry.objects.filter(reference_type=ref_type, reference_id=ref_id).order_by('id')
    )
    total_dr = total_cr = Decimal('0')
    print("  %s:" % label)
    for e in entries:
        print("    GL#%-3d  [%-28s]  %-40s  Dr=%10s  Cr=%10s" % (
            e.id, e.reference_type, e.account.name, e.debit, e.credit))
        total_dr += e.debit
        total_cr += e.credit
    balanced = total_dr == total_cr
    tag = "BALANCED" if balanced else "*** UNBALANCED ***"
    print("         %-35s  Dr=%10s  Cr=%10s  [%s]" % ("TOTALS", total_dr, total_cr, tag))
    results[label] = balanced
    return balanced


def net_balances(label, from_gl_id=0):
    qs = GLEntry.objects.filter(id__gte=from_gl_id).select_related('account')
    net = defaultdict(Decimal)
    for e in qs:
        net[e.account.name] += e.debit - e.credit
    print("  NET ACCOUNT BALANCES (%s):" % label)
    any_nonzero = False
    for acct in sorted(net.keys()):
        bal = net[acct]
        if bal != 0:
            flag = "  *** NON-ZERO — DANGLING BALANCE ***"
            any_nonzero = True
        else:
            flag = ""
        print("    %-40s  Net=%12s%s" % (acct, bal, flag))
    key = "NET ZERO: %s" % label
    results[key] = not any_nonzero
    if any_nonzero:
        print("  *** BALANCE DISCREPANCY DETECTED ***")
    else:
        print("  All accounts net to zero — no dangling balances.")


# ── Create test batch ─────────────────────────────────────────────────
batch = Batch.objects.create(
    product=PROD,
    batch_number='BATCH-TEST-001',
    purchase_price=Decimal('632.00'),
    mrp=Decimal('900.00'),
    base_selling_price=Decimal('750.00'),
    current_quantity=0,
    size=Decimal('500'),
    unit='Bag',
)

# ═════════════════════════════════════════════════════════════════════
# STEP 1: Purchase Invoice (20 units @ 632, GST 18%)
# Expected totals:
#   Base: 20 × 632 = 12,640   GST 18%: 2,275.20   Total: 14,915.20
# ═════════════════════════════════════════════════════════════════════
pinv = PurchaseInvoice.objects.create(
    supplier=SUPP,
    invoice_number='PINV-TEST-001',
    date=TODAY,
    total_amount=Decimal('14915.20'),
)
PurchaseItem.objects.create(
    invoice=pinv, batch=batch, quantity=20,
    basic_rate=Decimal('632.00'),
    tax_amount=Decimal('2275.20'),
    total_amount=Decimal('14915.20'),
)
pinv.submit()
batch.refresh_from_db()

print()
print(SEP)
print("STEP 1: Purchase Invoice %s  |  Stock: %d (expected 20)" % (pinv.invoice_number, batch.current_quantity))
print(SEP)
print("  EXPECTED PurchaseReceipt: Dr Stock In Hand 12640 | Cr SRBNB 12640")
print("  EXPECTED PurchaseInvoice: Dr SRBNB 12640 + Dr CGST 1137.60 + Dr SGST 1137.60 | Cr AP 14915.20")
show_gl("PurchaseReceipt Stock GL", 'PurchaseReceipt', pinv.purchase_receipt.id)
show_gl("PurchaseInvoice AP/Tax GL", 'PurchaseInvoice', pinv.id)
net_balances("after STEP 1 only", from_gl_id=GLEntry.objects.order_by('id').first().id)

# ═════════════════════════════════════════════════════════════════════
# STEP 2: Purchase Return (5 units)
# Expected: 5 × 632 = 3,160 net; GST 18%: 568.80; Total: 3,728.80
# ═════════════════════════════════════════════════════════════════════
pr = PurchaseReturn.objects.create(
    supplier=SUPP,
    original_invoice=pinv,
    date=TODAY,
    reason='Damaged goods',
    total_refund_amount=Decimal('3728.80'),
)
PurchaseReturnItem.objects.create(
    return_invoice=pr, batch=batch,
    quantity=5, refund_price=Decimal('632.00'),
    warehouse=WH,
)
pr.submit()
batch.refresh_from_db()
gl_before_pr = GLEntry.objects.filter(reference_type__in=['PurchaseReturn', 'PurchaseReturnDebitNote']).order_by('id').first().id

print()
print(SEP)
print("STEP 2: Purchase Return submitted  |  Stock: %d (expected 15)" % batch.current_quantity)
print(SEP)
print("  EXPECTED PurchaseReturn stock GL:      Dr SRBNB 3160   | Cr Stock In Hand 3160")
print("  EXPECTED PurchaseReturnDebitNote GL:   Dr AP 3728.80   | Cr SRBNB 3160 | Cr CGST 284.40 | Cr SGST 284.40")
show_gl("PurchaseReturn Stock GL (step2)", 'PurchaseReturn', pr.id)
show_gl("PurchaseReturnDebitNote GL (step2)", 'PurchaseReturnDebitNote', pr.id)
net_balances("after STEP 2 only (PR stock + debit note)", from_gl_id=gl_before_pr)

# ═════════════════════════════════════════════════════════════════════
# STEP 3: Cancel Purchase Return
# ═════════════════════════════════════════════════════════════════════
pr.cancel()
batch.refresh_from_db()
cancel_gl_start = GLEntry.objects.filter(reference_type__in=['PurchaseReturnCancel']).order_by('id').first().id

print()
print(SEP)
print("STEP 3: Purchase Return CANCELLED  |  Stock: %d (expected 20)" % batch.current_quantity)
print(SEP)
print("  EXPECTED PurchaseReturnCancel stock GL: Dr Stock In Hand 3160 | Cr SRBNB 3160")
print("  EXPECTED PurchaseReturnDebitNote reversal: Cr AP 3728.80 | Dr SRBNB 3160 | Dr CGST 284.40 | Dr SGST 284.40")
print("  EXPECTED: SRBNB nets to ZERO across all return+cancel entries")
show_gl("PurchaseReturnCancel Stock GL (step3)", 'PurchaseReturnCancel', pr.id)
# Show ALL debit note entries (original + reversal, same ref_type/id)
show_gl("PurchaseReturnDebitNote ALL entries (step2+3)", 'PurchaseReturnDebitNote', pr.id)
net_balances("STEP 2 + STEP 3 combined (return lifecycle)", from_gl_id=gl_before_pr)

# ═════════════════════════════════════════════════════════════════════
# STEP 4: Sales Invoice (10 units @ 750, GST 18%)
# Expected: taxable 7500, CGST 675, SGST 675, grand_total 8850
# COGS = 10 × 632 (MAP) = 6320
# ═════════════════════════════════════════════════════════════════════
si = SalesInvoice.objects.create(
    customer=CUST,
    date=TODAY,
    total_taxable=Decimal('7500.00'),
    total_cgst=Decimal('675.00'),
    total_sgst=Decimal('675.00'),
    grand_total=Decimal('8850.00'),
)
SalesItem.objects.create(
    invoice=si, batch=batch, quantity=10,
    unit_price=Decimal('750.00'),
    tax_rate=Decimal('18.00'),
    tax_amount=Decimal('1350.00'),
    total_amount=Decimal('8850.00'),
)
si.submit()
batch.refresh_from_db()
si_gl_start = GLEntry.objects.filter(reference_type__in=['DeliveryNote', 'SalesInvoice']).order_by('id').first().id

print()
print(SEP)
print("STEP 4: Sales Invoice %s  |  Stock: %d (expected 10)" % (si.invoice_number, batch.current_quantity))
print(SEP)
print("  EXPECTED DeliveryNote:      Dr SDNB 6320   | Cr Stock In Hand 6320")
print("  EXPECTED SalesInvoice COGS: Dr COGS 6320   | Cr SDNB 6320")
print("  EXPECTED SalesInvoice AR:   Dr AR 8850     | Cr Sales Rev 7500 | Cr CGST Pay 675 | Cr SGST Pay 675")
show_gl("DeliveryNote Stock GL (step4)", 'DeliveryNote', si.delivery_note.id)
show_gl("SalesInvoice COGS+AR+Tax GL (step4)", 'SalesInvoice', si.id)
net_balances("after STEP 4 only (SI lifecycle)", from_gl_id=si_gl_start)

# ═════════════════════════════════════════════════════════════════════
# STEP 5: Cancel Sales Invoice
# ═════════════════════════════════════════════════════════════════════
dn_id = si.delivery_note.id
si.cancel()
batch.refresh_from_db()

print()
print(SEP)
print("STEP 5: Sales Invoice CANCELLED  |  Stock: %d (expected 20)" % batch.current_quantity)
print(SEP)
print("  EXPECTED DeliveryNoteCancel: Dr Stock In Hand 6320 | Cr SDNB 6320")
print("  EXPECTED SalesInvoice reversal: Cr COGS 6320 | Dr SDNB 6320 | Cr AR 8850 | Dr Sales Rev 7500 | Dr CGST Pay 675 | Dr SGST Pay 675")
show_gl("DeliveryNoteCancel Stock GL (step5)", 'DeliveryNoteCancel', dn_id)
show_gl("SalesInvoice ALL entries (step4+5)", 'SalesInvoice', si.id)
net_balances("STEP 4 + STEP 5 combined (SI lifecycle)", from_gl_id=si_gl_start)

# ═════════════════════════════════════════════════════════════════════
# STEP 6: Cancel Purchase Invoice
# ═════════════════════════════════════════════════════════════════════
pr_id = pinv.purchase_receipt.id
pinv.cancel()
batch.refresh_from_db()
pinv_cancel_start = GLEntry.objects.filter(reference_type='PurchaseReceiptCancel').order_by('id').first().id

print()
print(SEP)
print("STEP 6: Purchase Invoice CANCELLED  |  Stock: %d (expected 0)" % batch.current_quantity)
print(SEP)
print("  EXPECTED PurchaseReceiptCancel: Dr SRBNB 12640 | Cr Stock In Hand 12640")
print("  EXPECTED PurchaseInvoice reversal: Cr SRBNB 12640 | Cr CGST Rcv 1137.60 | Cr SGST Rcv 1137.60 | Dr AP 14915.20")
show_gl("PurchaseReceiptCancel Stock GL (step6)", 'PurchaseReceiptCancel', pr_id)
show_gl("PurchaseInvoice ALL entries (step1+6)", 'PurchaseInvoice', pinv.id)
net_balances("STEP 1 + STEP 6 combined (PINV lifecycle)", from_gl_id=GLEntry.objects.order_by('id').first().id)

# ═════════════════════════════════════════════════════════════════════
# GRAND TOTAL: All steps combined
# ═════════════════════════════════════════════════════════════════════
print()
print(SEP)
print("GRAND NET BALANCES — ALL STEPS (should ALL be zero)")
print(SEP)
net_balances("ALL GL entries combined", from_gl_id=0)

# ─── RESULT SUMMARY ───────────────────────────────────────────────────
print()
print(SEP)
print("RESULT SUMMARY")
print(SEP)
all_ok = all(results.values())
for lbl, ok in results.items():
    print("  [%s] %s" % ("PASS" if ok else "FAIL", lbl))
print()
print("  OVERALL: %s" % ("ALL CHECKS PASSED" if all_ok else "SOME CHECKS FAILED"))
