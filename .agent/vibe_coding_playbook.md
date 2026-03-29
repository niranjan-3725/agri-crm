# AgriCRM — Vibe Coding Playbook

> Permanent memory for AI agents. Read this before touching templates, views, or models.
> Last updated: 2026-03-18

---

## 1. The Literal Template Tag Trap

**Symptom:** A `{% include %}`, `{% block %}`, or `{% url %}` tag renders as visible text in the browser instead of executing.

**Root cause:** Django's `tag_re` (in `django/template/base.py`) is compiled **without `re.DOTALL`**. The dot `.` does not match newlines, so any `{% ... %}` construct that wraps across two lines is invisible to the tokeniser and falls through as a raw string.

```html
<!-- ✗ BROKEN — spans two lines, tag_re never matches -->
{% include 'components/ledger_timeline.html' with gl_entries=gl_entries
gl_total_debit=gl_total_debit %}

<!-- ✓ CORRECT — single line, always works -->
{% include 'components/ledger_timeline.html' with gl_entries=gl_entries gl_total_debit=gl_total_debit %}
```

**Rule:** Every `{% ... %}` tag must open and close on the **same line**. No exceptions.

**Detection script — run after every merge to main:**
```bash
python -c "
import os, re
for root, _, files in os.walk('templates'):
    for f in files:
        if not f.endswith('.html'): continue
        path = os.path.join(root, f)
        for i, line in enumerate(open(path), 1):
            if '{%' in line and '%}' not in line.split('{%',1)[1]:
                print(f'{path}:{i}: {line.strip()[:80]}')
"
```

**Note:** Results inside `{# ... #}` comment blocks are false positives — ignore them. Only fix lines where `{%` appears as live code, not inside a comment.

**Known affected files (all fixed as of 2026-03-08):**
- `purchase_detail.html` — `document_header.html` include, `ledger_timeline.html` include, `document_actions.html` include
- `purchase_order_detail.html` — `document_actions.html` include
- `purchase_receipt_detail.html` — `document_actions.html` include

---

## 2. The State Machine Rule (DRAFT / SUBMITTED / CANCELLED)

**Document lifecycle:**
```
DRAFT ──submit()──► SUBMITTED ──cancel()──► CANCELLED
  │                                              │
  └──delete() (hard)                    (no way back)
```

**Rules:**
- `DRAFT` — mutable. Edit, delete, add payments. No stock or GL entries yet.
- `SUBMITTED` — **immutable**. No edits. GL entries + stock movements are posted. Cancel to amend.
- `CANCELLED` — read-only forever. All entries reversed atomically.

**Always check status before action:**
```python
if invoice.status != 'DRAFT':
    raise ValidationError("Only DRAFT invoices can be edited.")
```

**In templates**, gate every destructive or mutating UI element:
```html
{% if invoice.status == 'DRAFT' %}
    <!-- Edit / Delete buttons here -->
{% endif %}
```

**Never** add an edit form to a SUBMITTED document, even "just to fix a typo."

---

## 3. The Stock Integrity Rule

**Never mutate `batch.current_quantity` directly:**
```python
# ✗ WRONG — bypasses audit trail, breaks reconciliation
batch.current_quantity += qty
batch.save()

# ✓ CORRECT — goes through the stock ledger service
StockMovement.objects.create(
    batch=batch,
    quantity=qty,               # negative for OUT
    movement_type='IN',
    reference_document_type='PurchaseInvoice',
    reference_document_id=invoice.id,
    valuation_rate=rate_pre_tax,
    warehouse=default_warehouse,
)
# The StockMovement.save() signal updates batch.current_quantity atomically
```

**Why:** Direct mutation loses audit trail, breaks the reconciliation dashboard, and silently corrupts moving-average valuations.

**Corollary — stale Python objects:** After any `StockMovement.create()`, call `batch.refresh_from_db()` before reading `batch.current_quantity` — the signal updates the DB row but not the in-memory Python object.

---

## 4. The Master Data Search-Select Rule

**Symptom:** User picks a supplier/product from the dropdown; the red "Select from the list" error stays visible.

**Root cause:** The blur-before-click race condition. When the user clicks a dropdown item:
1. `mousedown` fires on the item → browser moves focus → input fires `@blur` → handler closes the dropdown.
2. The item's `click` never fires (element is gone).
3. Result: hidden `supplier_id` input stays empty → validation fails.

**Fix (Alpine.js):**
```html
<!-- Add @mousedown.prevent to the dropdown container -->
<div x-show="supplierOpen" @mousedown.prevent class="...">
    <template x-for="s in filteredSuppliers" :key="s.id">
        <div @click="selectSupplier(s)">{{ s.name }}</div>
    </template>
</div>

<!-- Update @blur to only clear text if nothing was selected -->
<input @blur="supplierTouched = true; if (!supplierId) { supplierSearch = ''; supplierOpen = false }">
```

**Verified state UI:** When an ID is confirmed, switch input to blue tint (`border-blue-300 bg-blue-50/30`) and show a checkmark icon instead of the search icon. Revert to red on de-selection.

---

## 5. The Atomic Transaction Rule

**Every multi-step write must be wrapped in `transaction.atomic()`:**
```python
# ✗ WRONG — partial failure leaves orphan records
invoice = PurchaseInvoice.objects.create(...)
for item in items:
    Batch.objects.get_or_create(...)
    PurchaseItem.objects.create(invoice=invoice, ...)

# ✓ CORRECT — all-or-nothing
with transaction.atomic():
    invoice = PurchaseInvoice.objects.create(...)
    for item in items:
        Batch.objects.get_or_create(...)
        PurchaseItem.objects.create(invoice=invoice, ...)
```

**Corollary — the cancel/reverse pattern:** `invoice.cancel()` must reverse *every* effect of `invoice.submit()` inside a single `atomic()` block — GL debits/credits, stock movements, AP balances. If cancel is not atomic, partial failures leave the ledger in an inconsistent state that is very hard to debug.

---

## 6. The Hard-Delete vs Cancel Rule

| Operation | When | Effect |
|-----------|------|--------|
| Hard delete (`invoice.delete()`) | DRAFT only | Row removed from DB. No reversals needed (nothing was posted). |
| Cancel (`invoice.cancel()`) | SUBMITTED only | Status → CANCELLED. GL entries reversed. Stock movements negated. AP balance updated. |

**Never** call `.delete()` on a SUBMITTED document. The ORM will remove the row but leave orphan GL entries, stock movements, and AP records pointing to a non-existent invoice.

**In views:**
```python
if invoice.status == 'DRAFT':
    invoice.delete()         # safe hard delete
elif invoice.status == 'SUBMITTED':
    invoice.cancel()         # atomic reversal
else:
    raise ValidationError("CANCELLED invoices cannot be deleted.")
```

---

## 7. The Context Variable Rule

**Every `{% include %}` receives only the variables you explicitly pass with `with`** (unless `{% include ... only %}` is omitted, in which case the parent context is also available — but don't rely on this for components).

Best practice — always pass explicitly:
```html
{% include 'components/ledger_timeline.html' with gl_entries=gl_entries stock_movements=stock_movements gl_total_debit=gl_total_debit gl_total_credit=gl_total_credit %}
```

If a component silently renders empty, the cause is almost always a missing context variable. Check the view's `return render(request, template, context)` dict first.

---

## 8. The Worktree Environment Rule

### 8.1 — Venv Isolation: Install in the Right Place

The worktree has its **own isolated venv** at `C:\agri_crm\.claude\worktrees\<name>\venv\`. Installing a package into the main project venv (`C:\agri_crm\venv\`) does **not** make it available inside a worktree.

**Symptom:**
```
ModuleNotFoundError: No module named 'django_htmx'
```
…even though `pip show django-htmx` succeeds — because you ran pip against the wrong venv.

**Fix:**
```bash
# ✗ WRONG — installs into the main venv or the system Python
pip install django-htmx

# ✓ CORRECT — installs into the worktree's own venv
./venv/Scripts/python -m pip install django-htmx
```

**Rule:** Any time you run `pip install` inside a worktree directory, always prefix with `./venv/Scripts/python -m pip install`.

### 8.5 — Always Start the Dev Server from the Main Branch

Worktrees are **temporary feature branches**. They may contain bugs that were already fixed on `main`. Always start the dev server from the main repo (`C:\agri_crm`), not from a worktree directory.

**Symptom:** A bug you already fixed appears to still be present. Server behaves differently from what the code review showed.

**Root cause:** The running server is serving an old worktree's code, not `main`.

**Fix:** Check which directory the server is running from:
```bash
# Check what's running
preview_list  # shows cwd of the running server

# Correct approach — always start from main
# launch.json cwd must be C:\agri_crm, not a worktree path
```

**Real example:** `create_sale` in the `mystifying-mestorf` worktree had `return redirect('dashboard')` (sends user to home page). The main branch had already fixed this to `return redirect('invoice_detail', pk=invoice.id)`. The bug "reappeared" only because the server was started from the old worktree.

**Rule:** When testing features for a user, always verify `preview_list` shows `cwd: C:\agri_crm` (main repo), not a worktree path.

---

### 8.2 — Always Use the Worktree Python for Validation Scripts

The worktree runs **Django 6.0** via its own venv. The system Python may have an older Django version (4.x or 5.x) with a different API surface. Running validation with the wrong Python produces misleading errors.

```bash
# ✗ WRONG — uses system Python / wrong Django version, misleading errors
python -c "import django; ..."

# ✓ CORRECT — uses the worktree venv's Python and Django 6.0
./venv/Scripts/python -c "import django; ..."
```

---

### 8.3 — Django 6.0: `CheckConstraint(check=)` → `CheckConstraint(condition=)`

Django 6.0 renamed the `check` parameter of `CheckConstraint` to `condition`. This is a **hard breaking change** — the server will refuse to start with a `TypeError`.

**Symptom:**
```
TypeError: CheckConstraint.__init__() got an unexpected keyword argument 'check'
```

**Fix — in `models.py`:**
```python
# ✗ WRONG (Django ≤ 5.x syntax)
models.CheckConstraint(check=models.Q(current_quantity__gte=0), name='...')

# ✓ CORRECT (Django 6.0+)
models.CheckConstraint(condition=models.Q(current_quantity__gte=0), name='...')
```

**Critical:** This must be fixed in **both places**:
1. The `class Meta: constraints = [...]` block in `models.py`
2. **Every migration file** that calls `migrations.AddConstraint(constraint=models.CheckConstraint(...))` — migration files are not auto-regenerated and retain the old syntax.

**Detection script:**
```bash
grep -r "CheckConstraint(check=" --include="*.py" .
```
Run this after any Django version upgrade. Zero results = clean.

---

## 8.4 — Django ORM Aggregation Functions Must Be Imported

When using aggregation functions like `Sum`, `Count`, `Avg`, `Max`, `Min` in models or views, they **MUST be imported explicitly** from `django.db.models`. They are not available by default.

**Symptom:**
```
NameError: name 'Sum' is not defined. Did you mean: 'sum'?
```

**Fix:**
```python
# ✗ WRONG — Sum is not imported, causes NameError at runtime
from django.db import models

class PurchaseReturn(models.Model):
    def _validate_return_quantities(self):
        total = self.items.aggregate(total=Sum('quantity'))['total']
        # NameError: name 'Sum' is not defined

# ✓ CORRECT — explicitly import Sum
from django.db import models
from django.db.models import Sum

class PurchaseReturn(models.Model):
    def _validate_return_quantities(self):
        total = self.items.aggregate(total=Sum('quantity'))['total']  # works!
```

**Common aggregations to import:**
```python
from django.db.models import Sum, Count, Avg, Max, Min, Q, F
```

**Why:** Django's ORM functions are in a separate namespace. They're not built-ins and must be explicitly imported.

---

## 9. Navigation & Document State Rules

### Rule 9.1 — Post-Submission Redirect to Detail View

After any document creation or state transition (create, submit, cancel), **always redirect to that document's Detail View**, not to the list or home page.

```python
# ✗ WRONG — user loses context, cannot see confirmation details
return redirect('returns_list')
return redirect('/')

# ✓ CORRECT — lands on the document just created/submitted
return redirect('purchase_return_detail', pk=purchase_return.pk)
return redirect('sales_return_detail', pk=sales_return.pk)
```

**Why:** The Detail View is the only place where the user can verify the document was created correctly, see the Impact Banner (DRAFT) or Ledger Timeline (SUBMITTED), and take the next action. Redirecting elsewhere discards their context.

**Real example — `create_sale` bug:** An older branch had `return redirect('dashboard')` after saving a new sales invoice. This sent the user to the home page, completely disconnecting them from the invoice they just created. Fixed in main to `return redirect('invoice_detail', pk=invoice.id)`.

**Detection:** Scan for accidental `dashboard` redirects after document creation:
```bash
grep -rn "redirect('dashboard')" transactions/ inventory/
# Zero results = clean. Any result = likely a bug.
```

**Receivables module — Rule 9.1 compliance (Phase 4, Fixed):**

| View | Old redirect | Correct redirect (Rule 9.1) |
|---|---|---|
| `record_receipt` (HTMX) | — | 204 + `HX-Redirect` → `customer_payment_detail` ✓ |
| `record_receipt` (non-HTMX) | `invoice_detail` | `customer_payment_detail` ✓ |
| `cancel_customer_payment` (success) | `invoice_detail` | `customer_payment_detail` ✓ |
| `cancel_customer_payment` (error) | `invoice_detail` / `customer_ledger` | unchanged (no document created) ✓ |
| `delete_customer_payment` | delegates to cancel | deprecated, logs warning, delegates to cancel ✓ |

See also Rule 13.6 (CustomerPayment Detail View Is Mandatory) and Rule 13.7 (Alpine fetch() redirect pattern).

---

### Rule 9.2 — Filter Active Documents Only in Lookups

Any endpoint that provides a list of invoices for linking (Returns, Payments, Credit Notes) **MUST filter strictly for `status='SUBMITTED'`**. Never rely on `payment_status` alone — a CANCELLED invoice can retain its last payment status.

```python
# ✗ WRONG — CANCELLED invoices can still match payment_status
invoices = SalesInvoice.objects.filter(
    customer_id=customer_id,
    payment_status__in=['PAID', 'PARTIAL', 'UNPAID'],
)

# ✗ WRONG — no status filter at all; all statuses appear
invoices = PurchaseInvoice.objects.filter(supplier_id=supplier_id)

# ✓ CORRECT — only active, submitted documents are eligible
invoices = SalesInvoice.objects.filter(customer_id=customer_id, status='SUBMITTED')
invoices = PurchaseInvoice.objects.filter(supplier_id=supplier_id, status='SUBMITTED')
```

**Why:** A CANCELLED invoice has already been reversed. Linking a return to it would double-reverse revenue, AP, and stock — silently corrupting the ledger.

---

## 10. The Generic Refactor Framework

**Extracted from Purchase Module success patterns (Sprint 9–16).** These four patterns are reusable for Sales, Inventory, and Master Data modules.

### 10.1 Triple-Entry State Machine

Every transactional document must enforce:
```
DRAFT ──submit()──► SUBMITTED ──cancel()──► CANCELLED
```

**Rules:**
- DRAFT: mutable, no GL/stock posted
- SUBMITTED: immutable, GL + stock posted atomically
- CANCELLED: read-only, all effects reversed atomically
- Always wrap submit()/cancel() in `transaction.atomic()`
- Guard UI elements behind status checks: `{% if doc.status == 'DRAFT' %}`

See **AgriCRM_Generic_Refactor_Framework.md § Pattern 1** for full implementation.

### 10.2 Ledger Announcement Pattern

Financial documents (Invoice, SalesInvoice) must announce their effects to multiple systems atomically:

```
Invoice.submit()
    ├─► Fulfillment.submit() [stock movements]
    ├─► post_*_invoice_gl() [AP/AR/Revenue/Tax]
    └─► OrderItem.update() [procurement/sales tracking]
    All in transaction.atomic()
```

**Rules:**
- Never post GL without posting stock
- Never post stock without posting GL
- Never update tracking without GL + stock
- Reverse **all** effects when cancelling

See **AgriCRM_Generic_Refactor_Framework.md § Pattern 2** for full implementation.

### 10.3 Tax-Exclusive Valuation

GST must be separated from cost basis:

```
basic_rate = ₹100 (cost, pre-tax)
tax = ₹18 (5–28% GST)
total = ₹118 (cost + tax)

GL posts:  Dr SRNB ₹100, Cr AP ₹118
           Dr CGST ₹9, Dr SGST ₹9
```

**Rules:**
- Store `basic_rate` pre-tax in Batch and Item models
- Calculate tax separately: `tax = basic_rate × (tax_rate / 100)`
- GL debit gets `base_amount` (no tax), credit gets total
- Display clearly: "₹X (ex-tax)" in templates

See **AgriCRM_Generic_Refactor_Framework.md § Pattern 3** for full implementation.

### 10.4 Jony Ive UX Validation

Real-time, context-aware validation without bulk error banners:

**Rules:**
- Per-field touch tracking: `fieldTouched`, only show error after blur
- Inline errors only: no bulk error banner
- Verified state UI: blue tint + checkmark when selection confirmed
- Focus flow: move cursor to next field after valid selection
- Blur guard: `@mousedown.prevent` on dropdown to prevent blur-before-click race
- Backend safety net: validate at view + model level

See **AgriCRM_Generic_Refactor_Framework.md § Pattern 4** for full implementation.

---

## 11. The Narrow Except Trap (Unhandled InsufficientStockError)

**[FIXED 2026-03-08 — `transactions/views.py:purchase_delete`]**

**Symptom:** `500 Internal Server Error` at `/purchases/<pk>/delete/` when cancelling a submitted purchase invoice whose stock has already been partially or fully consumed.

**Full traceback:**
```
MySQLdb.OperationalError: (3819, "Check constraint 'stockbin_non_negative_qty' is violated.")
→ IntegrityError (3819, ...)
→ InsufficientStockError: Insufficient stock in Batch 28 (warehouse 1). Attempted change: -10.
→ Unhandled exception → 500 page
```

**Root cause:**
1. Cancelling a submitted invoice calls `invoice.cancel()` → `PurchaseReceipt.cancel()` → `process_stock_movement()` with `-qty`.
2. MySQL's `CHECK CONSTRAINT 'stockbin_non_negative_qty'` fires (stock can't go negative).
3. The service converts the `IntegrityError` to an `InsufficientStockError`.
4. The view's `except ValidationError` clause does **not** catch `InsufficientStockError` (plain `Exception` subclass).
5. Django gets an unhandled exception → 500.

**Broken code:**
```python
def purchase_delete(request, pk):
    ...
    try:
        invoice.cancel()
    except ValidationError as e:     # ← misses InsufficientStockError
        messages.error(request, str(e))
        return redirect('purchase_detail', pk=pk)
```

**Fix (applied):** Add `InsufficientStockError` to the except clause with a user-friendly message:
```python
    except InsufficientStockError:
        messages.error(
            request,
            "Cannot cancel this purchase — some stock has already been consumed "
            "(sold, returned, or reconciled). Reverse those transactions first."
        )
        return redirect('purchase_detail', pk=pk)
```

**Generic Rule:** When a view calls a service that raises a custom exception (`InsufficientStockError`, any non-Django exception), **always catch the service exception explicitly** alongside `ValidationError`. A catch-all `except Exception as e` is acceptable as a final fallback but never as the primary safety net.

**Pattern to follow:**
```python
try:
    invoice.cancel()
except ValidationError as e:
    messages.error(request, str(e))
    return redirect(...)
except InsufficientStockError:
    messages.error(request, "User-friendly message explaining WHY and WHAT TO DO next.")
    return redirect(...)
```

---

## 12. The Payment State Machine Rule

**[IMPLEMENTED 2026-03-08 — Payables Module Refactor]**

### 12.1 — SupplierPayment Lifecycle

Every `SupplierPayment` follows the two-state lifecycle:
```
SUBMITTED ──cancel()──► CANCELLED
```

- **SUBMITTED** (default): GL entries exist (`Dr AP / Cr Cash`). Invoice balance reduced.
- **CANCELLED**: GL entries deleted. Invoice balance restored by signal.

**No DRAFT state** for quick-pay modal payments — they are created and submitted atomically in one step.

### 12.2 — Cancellation Reverses GL Atomically

`payment.cancel()` must:
1. Check `status == 'SUBMITTED'` (raise `ValidationError` otherwise)
2. Inside `transaction.atomic()`:
   - Delete `GLEntry` rows with `reference_type='SupplierPayment'`, `reference_id=payment.id`
   - Set `status = 'CANCELLED'`
   - Call `save(update_fields=['status'])` — this triggers the post_save signal
3. The signal recalculates invoice balance, **filtering only `status='SUBMITTED'` payments**

**Orphaned GL entries are the #1 payables ledger corruption bug.** Hard-deleting a payment without reversing its GL entries leaves the AP account permanently incorrect. Always go through `cancel()`.

### 12.3 — Signal Must Filter by Status

The `update_invoice_payment_status` signal must **only count SUBMITTED payments**:

```python
# ✗ WRONG — CANCELLED payments inflate the total
total_paid = invoice.payments.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

# ✓ CORRECT — excludes cancelled payments
total_paid = invoice.payments.filter(status='SUBMITTED').aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
```

### 12.4 — HTMX Payment Submit: HX-Redirect, not window.location.reload()

When a modal form submits a payment via HTMX and the server needs to redirect to the Payment Detail View, return an `HX-Redirect` header (204 response), **not** `window.location.reload()`:

```python
# ✓ CORRECT — full-page navigation to Payment Detail View
response = HttpResponse(status=204)
response['HX-Redirect'] = reverse('supplier_payment_detail', kwargs={'pk': payment.pk})
return response
```

In the template, the HTMX `@htmx:after-request` handler should handle failures (show error) but success is handled by `HX-Redirect` — HTMX navigates before the event fires.

```html
<!-- ✓ CORRECT: handle errors, let HX-Redirect handle success -->
<form hx-post="..." hx-swap="none"
    @htmx:after-request="if (!event.detail.successful) { payError = JSON.parse(event.detail.xhr.responseText).error }">
```

**Never** use `window.location.reload()` as the success handler — it reloads the current page, discarding the user's context.

### 12.5 — Test Invoices Must Be SUBMITTED for Payment Tests

Tests that record payments against invoices MUST set `status='SUBMITTED'` on the invoice. A DRAFT invoice is not eligible for payment (backend guard in `record_payment`):

```python
# ✗ WRONG — invoice defaults to DRAFT, record_payment returns 400
self.invoice = PurchaseInvoice.objects.create(total_amount=1000, ...)

# ✓ CORRECT — SUBMITTED invoices are eligible for payment
self.invoice = PurchaseInvoice.objects.create(total_amount=1000, ..., status='SUBMITTED')
```

And assert `status_code == 204` (not 200) since `record_payment` returns 204 + HX-Redirect on success.

---


## 13. The Receivables (Customer Payment) Rules

**[AUDITED 2026-03-08 — Receivables Module Audit]**

### 13.1 — CustomerPayment Must Have a Status Field

`CustomerPayment` MUST have `status = CharField(choices=[('SUBMITTED','Submitted'),('CANCELLED','Cancelled')], default='SUBMITTED')`. Without it:
- Hard-delete is the only way to "undo" a payment, which orphans GL entries.
- The invoice-balance signal cannot filter CANCELLED payments, causing overcounting.

```python
# ✓ CORRECT pattern (mirrors SupplierPayment)
class CustomerPayment(models.Model):
    STATUS_CHOICES = [('SUBMITTED', 'Submitted'), ('CANCELLED', 'Cancelled')]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='SUBMITTED')

    def cancel(self):
        if self.status != 'SUBMITTED':
            raise ValidationError("Only SUBMITTED payments can be cancelled.")
        with transaction.atomic():
            GLEntry.objects.filter(reference_type='CustomerPayment', reference_id=self.id).delete()
            self.status = 'CANCELLED'
            self.save(update_fields=['status'])
```

### 13.2 — GL ORPHAN: Never Hard-Delete a CustomerPayment Without Reversing GL First

`delete_customer_payment` that calls `payment.delete()` without first deleting `GLEntry` rows **permanently corrupts the Cash/Bank and Accounts Receivable ledger accounts**.

```python
# ✗ WRONG — orphans GL entries, permanently corrupts AR/Cash
payment.delete()

# ✓ CORRECT — reverse GL first (for legacy hard-delete), or use cancel()
GLEntry.objects.filter(reference_type='CustomerPayment', reference_id=payment.id).delete()
payment.delete()

# ✓ BEST — use the state machine cancel() method (preserves audit trail)
payment.cancel()  # atomically deletes GL + sets status=CANCELLED
```

### 13.3 — record_receipt Must Guard invoice.status == 'SUBMITTED'

Any view that creates a `CustomerPayment` MUST first verify the linked `SalesInvoice` is SUBMITTED. A DRAFT or CANCELLED invoice can silently accept payments otherwise.

```python
# ✓ Required guard at the top of record_receipt
if invoice.status != 'SUBMITTED':
    return JsonResponse({'success': False, 'error': 'Receipts can only be recorded against a submitted invoice.'}, status=400)
```

### 13.4 — CustomerPayment Signal Must Filter by Status

The `update_sales_invoice_payment_status` signal MUST filter `status='SUBMITTED'` when summing payments. See Rule 12.3 (SupplierPayment) for the identical pattern.

```python
# ✗ WRONG — includes CANCELLED payments
total_received = invoice.payments.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

# ✓ CORRECT
total_received = invoice.payments.filter(status='SUBMITTED').aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
```

### 13.5 — customer_ledger total_due Must Filter by invoice status='SUBMITTED'

The `total_due` annotation in `customer_ledger` must include `salesinvoice__status='SUBMITTED'` alongside `payment_status`. A CANCELLED invoice retains its last `payment_status` value and will silently inflate displayed receivables if status is not checked.

```python
# ✓ CORRECT
Sum('salesinvoice__balance_due', filter=Q(
    salesinvoice__payment_status__in=['UNPAID', 'PARTIAL'],
    salesinvoice__status='SUBMITTED',
))
```

### 13.6 — CustomerPayment Detail View Is Mandatory

Per Rule 9.1, after recording a customer receipt, the system MUST redirect to the `customer_payment_detail` view (not to `invoice_detail` or `customer_ledger`). This view must expose the `ledger_timeline.html` component showing `Dr Cash/Bank → Cr AR` entries, a cancel button, and a link back to the parent invoice.

### 13.7 — Quick Receipt Modal: Alpine fetch() Pattern (Modal-to-Detail-Redirect)

**Do NOT use `:hx-post` + `htmx.process()` for modals with dynamic POST URLs.** The bug: `htmx.process($el)` fires at page-load when `receiptActionUrl=''`, so HTMX registers the form with `hx-post=""`. The submit button click triggers HTMX with the wrong empty URL — no POST is ever sent to the real endpoint.

**Correct pattern:** Use Alpine `@submit.prevent` + `fetch()`. Alpine reads `receiptActionUrl` from its reactive scope at submit time — no DOM attribute binding race condition:

```html
<form @submit.prevent="
        receiptError = '';
        const fd = new FormData($el);
        fetch(receiptActionUrl, {
            method: 'POST',
            headers: {
                'X-CSRFToken': fd.get('csrfmiddlewaretoken'),
                'HX-Request': 'true'
            },
            body: fd
        }).then(async r => {
            if (r.status === 204) {
                const redirect = r.headers.get('HX-Redirect');
                if (redirect) window.location.href = redirect;
            } else {
                try { receiptError = (await r.json()).error || 'An error occurred.'; }
                catch(e) { receiptError = 'An unexpected error occurred.'; }
            }
        }).catch(() => { receiptError = 'Network error. Please try again.'; })">
```

**Why Alpine fetch() is correct for dynamic-URL modals:**
- URL is read from the Alpine variable at submit time (reactive), never from a DOM attribute
- `ERR_ABORTED` on the fetch after `window.location.href` is set is normal and expected
- Server: return `HttpResponse(status=204)` with `response['HX-Redirect'] = reverse(...)` on success
- Server: return `JsonResponse({'error': '...'}, status=400)` on validation failure
- `HX-Request: true` header tells `record_receipt` to return JSON errors instead of Django messages

**GL Impact Preview Banner:** Show a live `Dr / Cr` preview inside the modal using `Math.min(parseFloat(amount), balanceDue)` as the effective posted amount. Overpayment excess displays as `+ Wallet Credit`. Use `bg-blue-50`, `font-mono`, `text-blue-800`.

**Collected This Month / Recent Receipts stats** MUST filter `status='SUBMITTED'` — cancelled payments must never inflate these figures (Rule 13.4).

### 13.8 — Every Financial Document Detail View Must Include the Ledger Timeline

**Rule:** Every detail view for a financial document (CustomerPayment, SupplierPayment, SalesInvoice, PurchaseInvoice, SalesReturn, PurchaseReturn) **must** include `components/ledger_timeline.html` so the double-entry GL impact is always visible and verifiable.

**Why:** Without the timeline, a developer has no in-UI confirmation that double-entry integrity is maintained. The timeline serves as both a UX transparency feature and a live audit trail.

---

## 18. ERPNext Parity Rules

**[ADDED 2026-03-11 — ERPNext Architectural Audit Results]**

### 18.1 — Chronological Moving Average Calculation

**Problem:** Backdated entries can corrupt moving average calculations if processed out of chronological order.

**ERPNext Pattern:** `repost_item_valuation` processes entries sequentially by timestamp, recalculating all future valuations to maintain consistency.

**AgriCRM Rule:** When recalculating moving averages, always consider the chronological order of entries, not just the current state. Backdated entries must trigger repost of all future valuations.

```python
# ✗ WRONG — uses current state, ignores chronology
old_total_qty = Batch.objects.filter(product=product).aggregate(total=Sum('current_quantity'))['total']

# ✓ CORRECT — considers chronological order
old_total_qty = (
    StockMovement.objects
    .filter(batch__product=product, created_at__lte=entry_timestamp)
    .aggregate(total=Sum('quantity'))['total']
) or 0
```

### 18.2 — Valuation Method Flexibility

**Problem:** Hardcoding to Moving Average only limits compliance with different accounting standards.

**ERPNext Pattern:** `Item.valuation_method` field supports FIFO, Moving Average, and other methods.

**AgriCRM Rule:** Support multiple valuation methods at the product level. Never hardcode valuation logic to a single method.

```python
# Add to Product model
class Product(models.Model):
    VALUATION_METHOD_CHOICES = [
        ('MOVING_AVERAGE', 'Moving Average'),
        ('FIFO', 'First In First Out'),
    ]
    valuation_method = models.CharField(
        max_length=20, 
        choices=VALUATION_METHOD_CHOICES, 
        default='MOVING_AVERAGE'
    )
```

### 18.3 — Historical Correction Protocol

**Problem:** Corrections to historical data (stock reconciliation, price adjustment) can create permanent valuation drift if future entries aren't recalculated.

**ERPNext Pattern:** `Repost Item Valuation` doctype with background job processing for historical corrections.

**AgriCRM Rule:** Any correction to historical data must trigger automatic repost of all affected future entries via background job processing.

```python
# Required after any historical correction
def trigger_repost_valuation(product_id, from_date):
    """Queue background job to recalculate all future valuations."""
    RepostItemValuation.objects.create(
        product_id=product_id,
        from_date=from_date,
        status='QUEUED'
    )
```

### 18.4 — Payment Allocation Atomicity

**Problem:** Single-payment-per-invoice limitation prevents efficient cash management.

**ERPNext Pattern:** `Payment Entry` with allocation table distributing amount across multiple invoices.

**AgriCRM Rule:** When implementing multi-invoice payment allocation, ensure the total allocated amount never exceeds the payment amount, and all allocations are atomic within a single transaction.

```python
# Required validation in payment allocation
total_allocated = sum(allocation.amount for allocation in allocations)
if total_allocated > payment.amount:
    raise ValidationError("Total allocation cannot exceed payment amount.")
```

### 18.5 — Landed Cost Distribution

**Problem:** Additional costs (freight, customs, handling) not distributed to item valuation understates inventory value.

**ERPNext Pattern:** `Landed Cost Voucher` distributes additional costs proportionally across purchase items.

**AgriCRM Rule:** Additional costs must be distributed proportionally across all items in a purchase receipt and added to their valuation rates.

```python
# Required for proper inventory valuation
def distribute_landed_costs(purchase_receipt, additional_costs):
    """Distribute additional costs proportionally across all items."""
    total_value = sum(item.amount for item in purchase_receipt.items.all())
    for item in purchase_receipt.items.all():
        proportion = item.amount / total_value
        additional_cost = additional_costs * proportion
        item.batch.purchase_price += additional_cost / item.quantity
        item.batch.save()
```

### 18.6 — Immutable Ledger Compliance

**Problem:** Deleting GL entries on cancellation violates accounting audit requirements.

**ERPNext Pattern:** Cancellation creates reversing GL entries (mirror entries with swapped debit/credit) instead of deletion.

**AgriCRM Rule:** Never delete GL entries. Always create reversing entries to maintain complete audit trail.

```python
# ✗ WRONG — deletes audit trail
GLEntry.objects.filter(reference_type='Invoice', reference_id=invoice.id).delete()

# ✓ CORRECT — preserves audit trail
reverse_document_gl('Invoice', invoice.id)  # Creates mirror entries
```

### 18.7 — Concurrent Valuation Safety

**Problem:** Multiple simultaneous stock movements can corrupt moving average calculations.

**ERPNext Pattern:** Product-level locking during valuation recalculation.

**AgriCRM Rule:** Always use `select_for_update()` on the product when recalculating moving averages to prevent race conditions.

```python
# ✓ REQUIRED — prevents concurrent MA corruption
product_locked = Product.objects.select_for_update().get(pk=product.pk)
new_avg = _recalculate_moving_average(product_locked, quantity, price)
```

**Implementation checklist:**
1. View fetches `GLEntry` rows filtered by `reference_type` + `reference_id` for the document:
   ```python
   gl_entries = list(GLEntry.objects.filter(
       reference_type='CustomerPayment', reference_id=payment.id
   ).select_related('account').order_by('created_at'))
   gl_total_debit  = sum(e.debit  for e in gl_entries)
   gl_total_credit = sum(e.credit for e in gl_entries)
   ```
2. Template passes all four variables to the include on **one line** (Rule 1):
   ```html
   {% include 'components/ledger_timeline.html' with gl_entries=gl_entries stock_movements=None gl_total_debit=gl_total_debit gl_total_credit=gl_total_credit %}
   ```
3. The impact banner above the timeline must describe the exact Dr/Cr pair in human-readable form so the user can cross-reference the timeline rows.
4. For CANCELLED documents, show the reversal entries in the timeline (they are posted automatically by `payment.cancel()`); the banner must switch to the red "Cancelled" variant.

**Anti-pattern:** Returning the detail view without `gl_entries` in context causes the timeline component to silently render empty. Always assert `len(gl_entries) > 0` in tests for SUBMITTED documents.

---

## Quick Diagnostic Checklist

### Bug appears fixed in code but still happens in browser:
1. **Wrong server cwd?** → Run `preview_list` and verify `cwd` is `C:\agri_crm`, not a worktree. Old worktrees can have already-fixed bugs. (Rule 8.5)
2. **Right cwd but wrong code?** → Did you start the server before pulling latest main? Restart after `git pull`. (Rule 8.5)

### Server won't start or runtime NameError on specific view:
1. **ModuleNotFoundError?** → Did you install the package in the worktree venv? Run `./venv/Scripts/python -m pip install <pkg>`. (Rule 8.1)
2. **`CheckConstraint.__init__() got unexpected keyword argument 'check'`?** → Django 6.0 renamed `check=` to `condition=`. Fix in both `models.py` AND all migration files. Run `grep -r "CheckConstraint(check=" --include="*.py" .` to find all occurrences. (Rule 8.3)
3. **Misleading errors from validation scripts?** → Are you using system Python instead of `./venv/Scripts/python`? (Rule 8.2)
4. **`NameError: name 'Sum'/'Count'/'Avg'/'Max'/'Min' is not defined`?** → Django ORM aggregation functions must be imported from `django.db.models`. Add `from django.db.models import Sum, Count, Avg, Max, Min`. (Rule 8.4)

### Detail page component isn't rendering:
1. **Literal tag?** → Is the `{% include %}` tag on ONE line? (Rule 1)
2. **Missing context?** → Does the view pass all variables the component needs? (Rule 7)
3. **Wrong template file?** → Is the dev server running from the correct worktree? Each worktree has its own template directory.
4. **Alpine not loaded?** → Components using `x-data` / `x-show` need Alpine.js on the page. Check `base.html`.
5. **Status guard blocking?** → Is the component wrapped in `{% if invoice.status == '...' %}`? (Rule 2)

---

---

## 14. The Return Cancel Double-Posting Bug

**[DISCOVERED 2026-03-09 — System-Wide GL Reconciliation Audit]**

### 14.1 — Root Cause

When `PurchaseReturn.cancel()` or `SalesReturn.cancel()` runs, it makes **two separate calls that both reverse the stock-level GL entries**, inflating the Stock In Hand account balance by the full return value.

**Broken sequence (PurchaseReturn.cancel):**
```
1. process_stock_movement('PurchaseReturnCancel', qty=+5)
       → post_stock_gl('PurchaseReturnCancel', ...) → Dr Stock In Hand 4,485  ✓

2. reverse_document_gl('PurchaseReturn', id)
       → sweeps ALL GL entries tagged reference_type='PurchaseReturn'
       → includes the stock GL entry (Cr Stock In Hand 4,485) from submit time
       → posts reversal: Dr Stock In Hand 4,485  ← DUPLICATE!
```

**Net result:** Stock In Hand is Dr'd Rs.8,970 when it should only be Rs.4,485.
The GL `Stock In Hand` balance is inflated by exactly the return value. The StockBin MAP value (ground truth) will be lower by the same amount.

**Evidence in DB (discovered audit 2026-03-09):**
- GL#107: `PurchaseReturnCancel/6`  Dr Stock In Hand 4,485 (correct — from process_stock_movement)
- GL#110: `PurchaseReturn/6` Dr Stock In Hand 4,485 (spurious — from reverse_document_gl sweeping stock entries)

### 14.2 — Fix Pattern

`reverse_document_gl()` must exclude stock-level GL accounts when the cancel path already handles stock reversal via `process_stock_movement()`. Add an `exclude_account_names` parameter:

```python
# accounting/services.py — add exclude_account_names parameter
def reverse_document_gl(reference_type, reference_id, exclude_account_names=None):
    originals = list(
        GLEntry.objects.filter(
            reference_type=reference_type,
            reference_id=reference_id,
        ).order_by('pk')
    )
    if exclude_account_names:
        originals = [e for e in originals if e.account.name not in exclude_account_names]
    # ... rest unchanged
```

```python
# transactions/models.py — PurchaseReturn.cancel() and SalesReturn.cancel()
STOCK_GL_ACCOUNTS = [
    'Stock In Hand',
    'Stock Received But Not Billed',
    'Stock Delivered But Not Billed',
    'Cost of Goods Sold',
]

# In cancel():
# 1. process_stock_movement handles stock GL reversal
# 2. reverse_document_gl handles ONLY the financial entries (AP/AR/Tax)
reverse_document_gl(
    'PurchaseReturn', self.id,
    exclude_account_names=STOCK_GL_ACCOUNTS,   # ← prevent double-posting
)
```

### 14.3 — Affected Documents

| Document | Cancel method | Double-posts | Status |
|---|---|---|---|
| `PurchaseReturn` | `cancel()` | Dr Stock In Hand | **BUG — FIX REQUIRED** |
| `SalesReturn` | `cancel()` | Cr Stock In Hand | **LATENT BUG** (no SUBMITTED SalesReturns in DB yet) |
| `PurchaseInvoice` | `cancel()` → delegates to `PurchaseReceipt.cancel()` | N/A | No issue — stock GL handled inside PurchaseReceipt |
| `SalesInvoice` | `cancel()` → delegates to `DeliveryNote.cancel()` | N/A | No issue — stock GL handled inside DeliveryNote |

### 14.4 — Detection Command

Run this after every Return cancel to detect the double-posting:

```bash
venv/Scripts/python -c "
import os, sys, django
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
sys.path.insert(0, '.')
django.setup()
from django.db.models import Sum
from accounting.models import GLEntry, Account
sih = Account.objects.get(name='Stock In Hand')

# Find all PurchaseReturn cancel events with duplicate Stock In Hand Dr entries
from itertools import groupby
entries = GLEntry.objects.filter(
    account=sih,
    reference_type__in=['PurchaseReturn', 'SalesReturn', 'PurchaseReturnCancel', 'SalesReturnCancel'],
).values('reference_type', 'reference_id').annotate(net=Sum('debit') - Sum('credit'))
for e in entries:
    print(e)
"
```

---

## 15. System-Wide GL Health Check Commands

**[Added 2026-03-09 — Run after every sprint merge to main]**

### Full reconciliation audit:
```bash
cd C:\agri_crm
venv/Scripts/python audit_gl_reconciliation.py
```
**Expected output:** `[PASS] CLEAN BILL OF HEALTH` across all 5 checks.
**Any `[CRITICAL ERROR]`:** Stop, investigate, fix before merging.

### Quick double-entry balance check:
```bash
venv/Scripts/python -c "
import os, sys, django
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
sys.path.insert(0, '.')
django.setup()
from django.db.models import Sum
from accounting.models import GLEntry
from decimal import Decimal
groups = GLEntry.objects.values('reference_type', 'reference_id').annotate(
    dr=Sum('debit'), cr=Sum('credit')
)
unbalanced = [g for g in groups if abs((g['dr'] or 0) - (g['cr'] or 0)) > Decimal('1')]
if unbalanced:
    print(f'CRITICAL: {len(unbalanced)} unbalanced GL group(s):')
    for g in unbalanced: print(g)
else:
    print(f'PASS: All {groups.count()} GL groups balanced.')
"
```

### Inventory valuation vs GL check:
```bash
venv/Scripts/python -c "
import os, sys, django
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
sys.path.insert(0, '.')
django.setup()
from django.db.models import Sum, F, DecimalField, ExpressionWrapper
from accounting.models import GLEntry, Account
from inventory.models import StockBin
from decimal import Decimal
map_val = StockBin.objects.filter(actual_qty__gt=0).annotate(
    bv=ExpressionWrapper(F('actual_qty') * F('batch__product__moving_average_price'),
    output_field=DecimalField(max_digits=15, decimal_places=2))
).aggregate(t=Sum('bv'))['t'] or Decimal('0')
sih = Account.objects.get(name='Stock In Hand')
gl = GLEntry.objects.filter(account=sih).aggregate(dr=Sum('debit'), cr=Sum('credit'))
gl_net = (gl['dr'] or 0) - (gl['cr'] or 0)
diff = abs(map_val - gl_net)
print(f'StockBin MAP value: {map_val:.2f}  |  GL Stock In Hand: {gl_net:.2f}  |  Delta: {diff:.2f}')
if diff > 1: print('WARN: Delta > Rs.1 — check for Return cancel double-posting (Rule 14)')
else: print('PASS: Inventory valuation balanced.')
"
```

### Payment status integrity check:
```bash
venv/Scripts/python -c "
import os, sys, django
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
sys.path.insert(0, '.')
django.setup()
from django.db.models import Sum
from transactions.models import SalesInvoice
from decimal import Decimal
errors = 0
for inv in SalesInvoice.objects.filter(status='SUBMITTED'):
    paid = inv.payments.filter(status='SUBMITTED').aggregate(t=Sum('amount'))['t'] or Decimal('0')
    expected = Decimal(str(inv.grand_total)) - paid
    if abs(expected - Decimal(str(inv.balance_due))) > Decimal('1'):
        print(f'CRITICAL: SI#{inv.id} balance_due={inv.balance_due} expected={expected}')
        errors += 1
print(f'Payment integrity: {errors} error(s).' if errors else 'PASS: All payment balances correct.')
"
```

---

## 16. Centralized Navigation Routing (resolve_source_document)

**[IMPLEMENTED 2026-03-09 — General Ledger UI Sprint 19]**

### 16.1 — The Problem: Hardcoded URL Coupling

Every `GLEntry` carries a `reference_type` string (e.g. `'SalesInvoice'`) and a `reference_id` integer.
Without a central router, every template that links back to the source document must hardcode its URL pattern:

```html
<!-- ✗ WRONG — N x M coupling; every template must know every document type's URL -->
{% if entry.reference_type == 'SalesInvoice' %}
<a href="{% url 'invoice_detail' pk=entry.reference_id %}">View</a>
{% elif entry.reference_type == 'PurchaseInvoice' %}
<a href="{% url 'purchase_detail' pk=entry.reference_id %}">View</a>
{% endif %}
```

Adding a new document type requires hunting down and updating every template. Renaming a URL name breaks every template silently.

### 16.2 — The Solution: One Router, One Link Pattern

`resolve_source_document(request, reference_type, reference_id)` in `accounting/views.py` is the **single source of truth** for all GL to source-document navigation.

**In every template — always one link, regardless of document type:**
```html
<!-- ✓ CORRECT — template is fully decoupled from URL structure -->
<a href="{% url 'resolve_source_document' entry.reference_type entry.reference_id %}">{{ entry.reference_type }} #{{ entry.reference_id }}</a>
```

**URL pattern:** `/accounting/gl/resolve/<str:reference_type>/<int:reference_id>/`

**Rule:** Never link directly to a document detail URL from any GL-adjacent component (Ledger Timeline, General Ledger table, etc.). Always route through `resolve_source_document`.

### 16.3 — The Registry (Canonical URL Name Table)

Maintained in `accounting/views.py` in `_DETAIL_ROUTE_MAP`. These are the **verified** URL names from `transactions/urls.py`:

| `reference_type` | URL name | URL path |
|---|---|---|
| `SalesInvoice` | `invoice_detail` | `/sales/<pk>/` |
| `PurchaseInvoice` | `purchase_detail` | `/purchases/<pk>/` |
| `SalesReturn` | `sales_return_detail` | `/returns/sales/<pk>/` |
| `PurchaseReturn` | `purchase_return_detail` | `/returns/purchase/<pk>/` |
| `CustomerPayment` | `customer_payment_detail` | `/receipts/<pk>/` |
| `SupplierPayment` | `supplier_payment_detail` | `/payments/<pk>/` |
| `DeliveryNote` | `delivery_note_detail` | `/delivery-notes/<pk>/` |
| `PurchaseReceipt` | `purchase_receipt_detail` | `/purchase-receipts/<pk>/` |
| `StockReconciliation` | *(DB lookup to `batch_detail`)* | `/inventory/<batch_id>/` |

**Cancel variants** are normalised to their base type (the document PK is unchanged across submit/cancel):

| Cancel `reference_type` | Normalised to |
|---|---|
| `DeliveryNoteCancel` | `DeliveryNote` |
| `PurchaseReceiptCancel` | `PurchaseReceipt` |
| `SalesReturnCancel` | `SalesReturn` |
| `PurchaseReturnCancel` | `PurchaseReturn` |

### 16.4 — Adding a New Module

When a new document type posts GL entries, extend both dicts in `accounting/views.py`:

```python
# Step 1 — add to the route map
_DETAIL_ROUTE_MAP = {
    ...
    'NewDocument': ('new_document_detail', 'pk'),   # add here
}

# Step 2 — if it has a Cancel variant that posts under its own reference_type
_CANCEL_TO_BASE = {
    ...
    'NewDocumentCancel': 'NewDocument',             # add here
}
```

**No template changes required.** The router handles the redirect automatically.

### 16.5 — Graceful Failure Modes

| Scenario | Behaviour |
|---|---|
| Unknown `reference_type` | Redirect to `/accounting/ledger/?voucher_type=X&ref_id=Y` (shows all GL for that voucher) |
| `StockReconciliation` with missing batch | 404 via `get_object_or_404` |
| `NoReverseMatch` (URL was renamed/removed) | Redirect to filtered GL (same as unknown type) |

**Why redirect to the GL instead of raising 404?** An unknown type means the router registry is out of date, not that the data is corrupt. Showing the raw GL entries lets the developer diagnose the issue without a blank error page.

### 16.6 — Template Integration (Ledger Timeline)

`ledger_timeline.html` uses the router for every GL entry reference link — a single line that covers all document types:

```html
<a href="{% url 'resolve_source_document' entry.reference_type entry.reference_id %}" class="text-[10px] text-blue-500 hover:text-blue-700 font-medium hover:underline transition-colors">{{ entry.reference_type }} #{{ entry.reference_id }}</a>
```

---

## 17. Ledger Transparency Standards

**[IMPLEMENTED 2026-03-11 — General Ledger UI Refactor Sprint 19.1]**

### 17.1 — The Problem: Raw Entry Tables Are Unreadable

A flat list of GL rows (one row per debit/credit line) provides zero context. An operator looking at the ledger cannot tell which rows belong to the same business event without cross-referencing Voucher Type + Ref ID manually. Tax lines (CGST, SGST) are visually indistinguishable from revenue or inventory lines. Broken double-entry vouchers are invisible.

### 17.2 — Voucher-First Display (Group Header Pattern)

**Every GL view must group entries by (reference_type, reference_id) — one visual "card" per business document.**

Group header must show:
- Colour-coded badge: voucher type (blue=sales, amber=purchase, rose=returns, emerald=customer payments, orange=supplier payments, violet=inventory, gray=cancels)
- Reference ID (`#7`) — uniquely identifies the source document
- Date and time of posting
- Line count (N lines)
- Group-level Dr total and Cr total
- Balanced indicator (green ✓ or red ✗) — immediate visual signal of double-entry integrity
- "View document →" deep link via `resolve_source_document` router

Entry rows within each group show:
- Account name + type label
- Debit or Credit amount (dash for zero)
- Running balance (cumulative across all filtered entries, computed before grouping)
- Remarks

### 17.3 — Contextual Account Tooltips (Pattern 4 applied to accounting)

Every account name in the GL must carry a `(?)` hover tooltip explaining its purpose in plain English — not accounting jargon.

**Implementation:** `window.ACCOUNT_TOOLTIPS` JS dictionary in the template, keyed by exact account name. Alpine.js `x-data` binds the lookup at hover time:

```html
<span x-data="{ showTip: false, tip: (window.ACCOUNT_TOOLTIPS || {})['{{ entry.account.name|escapejs }}'] || '' }"
      class="relative inline-flex items-center gap-1.5">
  <span class="text-sm font-bold text-gray-900">{{ entry.account.name }}</span>
  <button type="button" x-show="tip" @mouseenter="showTip = true" @mouseleave="showTip = false"
          class="w-4 h-4 rounded-full bg-gray-100 text-gray-400 text-[9px] font-bold flex items-center justify-center cursor-help hover:bg-blue-100 hover:text-blue-600 transition-colors">?</button>
  <div x-show="showTip" x-transition
       class="absolute left-0 bottom-full mb-2 z-50 w-60 p-3 bg-gray-900 text-white text-[11px] font-medium rounded-xl shadow-2xl pointer-events-none leading-relaxed"
       x-text="tip"></div>
</span>
```

The `(?)` button only renders when a tooltip exists (`x-show="tip"`). Accounts without a tooltip entry remain clean.

### 17.4 — Pagination by Voucher Groups (not individual lines)

Paginate at the **voucher group** level (default: 20 groups per page), not at the entry line level. This ensures a business document is never split across pages. Running balance is computed on ALL filtered entries before grouping and paginating — so the balance shown in the last row of each page is always correct in absolute terms.

### 17.5 — Python Grouping (not Django template `{% regroup %}`)

Use `itertools.groupby` in the view, not `{% regroup %}` in the template. Reasons:
1. `{% regroup %}` cannot compute per-group aggregates (Dr/Cr totals, balanced flag)
2. Grouping in Python is testable in isolation
3. Template stays declarative — iterates over pre-computed group dicts

```python
from itertools import groupby as _groupby

def _group_entries(entries_with_balance):
    groups = []
    for (ref_type, ref_id), group_iter in _groupby(
        entries_with_balance,
        key=lambda e: (e.reference_type, e.reference_id),
    ):
        entries = list(group_iter)
        total_dr = sum((e.debit  or Decimal('0.00') for e in entries), Decimal('0.00'))
        total_cr = sum((e.credit or Decimal('0.00') for e in entries), Decimal('0.00'))
        groups.append({ ... })  # see accounting/views.py for full dict
    return groups
```

**Prerequisite:** Input entries must already be sorted by `(created_at, pk)` ascending — guaranteed by `_build_gl_queryset()`.

### 17.6 — Voucher Badge Colour Map

| Document Type | Badge Colour |
|---|---|
| SalesInvoice, DeliveryNote | `bg-blue-50 text-blue-700` |
| PurchaseInvoice, PurchaseReceipt | `bg-amber-50 text-amber-700` |
| CustomerPayment | `bg-emerald-50 text-emerald-700` |
| SupplierPayment | `bg-orange-50 text-orange-700` |
| SalesReturn, PurchaseReturn | `bg-rose-50 text-rose-700` |
| StockReconciliation | `bg-violet-50 text-violet-700` |
| Any Cancel variant | `bg-gray-100 text-gray-500` |
| Unknown | `bg-gray-100 text-gray-600` |

---

## 18. Transaction Threading Standards

**[IMPLEMENTED 2026-03-11 — General Ledger UI Sprint 19.2]**

### 18.1 — The Problem: Disconnected Physical and Financial Events

In double-entry accounting, a single purchase cycle produces two GL vouchers:
1. **Purchase Receipt #7** (physical event): `Stock In Hand Dr / SRNB Cr`
2. **Purchase Invoice #24** (financial event): `SRNB Dr + CGST Dr + SGST Dr / Accounts Payable Cr`

Displaying these as separate, unrelated rows forces operators to mentally reconstruct the business transaction. These vouchers must be visually threaded into a single "Master Transaction Card".

### 18.2 — Threading Key: FK-Based, Never Remark-Based

**Always thread using domain model FKs. Never parse remarks text.**

Supported threads (as of Sprint 19.2):

| Financial Doc | Physical Doc | FK Field |
|---|---|---|
| `PurchaseInvoice` | `PurchaseReceipt` | `PurchaseInvoice.purchase_receipt` (nullable FK) |
| `SalesInvoice` | `DeliveryNote` | `SalesInvoice.delivery_note` (nullable FK) |

### 18.3 — Two-Pass Grouping Algorithm

Threading uses a **two-pass algorithm** to avoid ordering bugs. Voucher groups arrive in chronological order — Receipt (#7) always precedes Invoice (#24). A single-pass approach would emit Receipt as standalone before discovering Invoice wants to absorb it.

**Pass 1 (pre-computation):** Query `PurchaseInvoice` and `SalesInvoice` for all invoice IDs in `voucher_groups`. Build `absorbed_keys: set` containing `(ref_type, ref_id)` of every child document (receipts, delivery notes) that a parent invoice claims.

**Pass 2 (emit):** Iterate `voucher_groups` chronologically. Skip any group whose key is in `absorbed_keys`. For parent invoices, bundle `[child_group, parent_group]` into one audit-group dict. Physical doc always appears first.

### 18.4 — Audit Group Dict Structure

```python
{
    'master_type':    'PurchaseInvoice',      # for resolve_source_document
    'master_id':      24,
    'label':          'PINV-001',             # invoice_number or display fallback
    'party':          'Indofil Industries',   # supplier.name / customer.name
    'amount':         Decimal('14915.20'),    # total_amount or grand_total
    'date':           datetime,
    'badge_class':    'bg-amber-50 text-amber-700',
    'display_name':   'Purchase Invoice',
    'is_threaded':    True,
    'voucher_groups': [receipt_group, invoice_group],  # physical doc first
    'total_entries':  6,
    'doc_count':      2,
}
```

### 18.5 — UI Layout: Master Transaction Card

**Collapsed (default):** One row showing: badge·label · party · amount · date · doc/line count pill · chevron · "View →" (leads to financial/master document).

**Expanded (toggle):** One `<table>` spanning all sub-groups. Sub-group section header rows (colspan=5) carry: sub-badge | #id | date | Dr/Cr totals | ✓ balanced | **"View [sub-doc] →" deep link**. Entry rows have Alpine.js (?) tooltips. Each sub-group ends with a "Bal. after [sub-doc]" callout row.

### 18.6 — Deep Link Routing (Rule 16 Compliance)

- Card "View →" → financial/master document via `resolve_source_document`
- Sub-section "View Receipt →" / "View Delivery Note →" → that specific child document via `resolve_source_document`
- Both always use the Resolution Router. Never hardcode document URLs in GL templates.

### 18.7 — Pagination and Running Balance

Paginate at audit group (transaction card) level. Running balance is computed on ALL filtered entries before any grouping or threading — values are always absolute and page-independent.

### 18.8 — Summary Card Nomenclature

| Label | Value |
|---|---|
| Transactions | `len(all_audit_groups)` — master transaction cards |
| Docs (sub-label) | `len(all_groups)` — underlying voucher groups |
| Lines (sub-label) | `qs.count()` — individual GLEntry rows |

---

---

## Rule 19 — Django→Alpine JSON Bridge

**When:** A view pre-selects a related document (e.g., `?from_invoice=<pk>`) and the template needs Alpine.js to pre-populate reactive state from that selection.

**Pattern:**

1. **View** — serialize the FK data as JSON using `json.dumps(...)` and pass it to the template context:
   ```python
   from_invoice_json = json.dumps({
       'supplier_id': from_invoice.supplier.pk,
       'supplier_display': f"{from_invoice.supplier.name} ({from_invoice.supplier.phone or ''})",
       'invoice_id': from_invoice.pk,
   }) if from_invoice else 'null'
   return render(request, 'template.html', {'from_invoice': from_invoice, 'from_invoice_json': from_invoice_json})
   ```

2. **Template** — inject a `<script>` tag **before** the `x-data` div. Use `|safe` to bypass Django's HTML auto-escaping (without it, `"` becomes `&quot;` and the JSON is unparseable by JS):
   ```html
   <script>const FROM_INVOICE_DATA = {{ from_invoice_json|safe }};</script>
   <div x-data="myLogic()">
   ```

3. **Alpine `init()`** — read the constant and pre-populate state, then trigger the async fetch:
   ```javascript
   init() {
       if (FROM_INVOICE_DATA) {
           this.supplierId = FROM_INVOICE_DATA.supplier_id;
           this.supplierSearch = FROM_INVOICE_DATA.supplier_display;
           this.invoiceId = FROM_INVOICE_DATA.invoice_id;
           this.fetchInvoiceItems(FROM_INVOICE_DATA.invoice_id); // calls addRow() internally
       } else {
           this.addRow();
       }
   },
   ```

4. **Template — Verified State chip** — add a `{% if from_invoice %}` block in the supplier/invoice field sections to show a locked read-only blue chip (Pattern 5) instead of the search input:
   ```html
   {% if from_invoice %}
   <input type="hidden" name="supplier" :value="supplierId">
   <div class="flex items-center gap-3 h-14 px-5 bg-blue-50 border border-blue-200 rounded-2xl">
       ...supplier name chip...
   </div>
   {% else %}
   ...normal search input...
   {% endif %}
   ```

**Never** rely on hidden inputs alone for Alpine state initialization — Alpine's `init()` runs before the DOM is read, so `x-model` on hidden inputs won't pre-populate reactive state on page load.

---

## Rule 20 — `document_actions.html` Contract

The reusable `components/document_actions.html` component uses `{{ submit_url }}` and `{{ cancel_url }}` directly in `<form action="">`. This is **not** a `{% url %}` tag — it renders whatever string is passed verbatim.

**Correct usage:** Pass fully resolved URL paths from the view (not URL name strings):
```python
# views.py
from django.urls import reverse
return render(request, 'template.html', {
    'submit_url': reverse('submit_purchase_receipt', kwargs={'pk': pk}),
    'cancel_url': reverse('cancel_purchase_receipt', kwargs={'pk': pk}),
})
```
```html
{# template.html — use template variables, not string literals #}
{% include 'components/document_actions.html' with doc_status=receipt.status submit_url=submit_url cancel_url=cancel_url %}
```

**Broken pattern** (URL name string instead of resolved path):
```html
{# ✗ BROKEN — action="submit_purchase_receipt" is not a valid URL #}
{% include 'components/document_actions.html' with submit_url='submit_purchase_receipt' doc_id=receipt.pk %}
```

---

## Rule 21 — Auth Consistency in Views

`views_buying_pipeline.py` and `views_pipeline.py` must **not** use `@login_required` unless a proper `LOGIN_URL` is configured in `config/settings.py` and the auth flow exists. The main `views.py` has no `@login_required` — all view files must match this pattern. Mixing decorated and undecorated views causes links between pages to silently break (302 → 404 dead-end for unauthenticated users in dev).

---

## Rule 22 — Hybrid Single-Document Purchase Pattern (Sprint 23)

**Replaces:** Two-Stage Material-First Flow (Sprint 21). The standalone `PurchaseReceipt` UI is retired; the model remains in DB for legacy data only.

**Pattern:** One `PurchaseInvoice` covers both physical stock receipt and financial settlement.

### State Machine

```
DRAFT → [receive_stock()] is_received=True → [submit()] SUBMITTED → [cancel()] CANCELLED
```

- `receive_stock()` is idempotent (guarded by `is_received` flag)
- `submit()` requires `is_received=True` — no GL shortcut allowed
- `cancel()` reverses ALL phases that have been completed

### GL Double-Entry

| Event | Dr | Cr |
|---|---|---|
| `receive_stock()` | Stock In Hand | SRNB |
| `submit()` | SRNB | Accounts Payable |
| `cancel()` (if received, not submitted) | SRNB | Stock In Hand |
| `cancel()` (if submitted) | AP | SRNB → then SRNB | Stock In Hand |

Net after full cycle: Stock In Hand debited, AP credited. Net on full cancel: all accounts return to zero.

### Invariants
1. `submit()` requires `is_received=True` — enforced with `ValidationError`.
2. `receive_stock()` is idempotent: raises `ValidationError` if called twice.
3. `cancel()` reverses ALL completed phases (stock + financial).
4. Rule 14 holds: stock GL **only** in `receive_stock()`; AP GL **only** in `submit()`.
5. Legacy two-stage data: `cancel()` still cascades to linked `PurchaseReceipt` if present.

### UI Signals
- **"Receive Goods" button**: emerald, shown in right panel only when `status == 'DRAFT'` and `not is_received`
- **"Goods Received" card**: Pattern 5 blue-tint card shown at top of detail page when `is_received=True`
- **Stock status chip**: "Received" (emerald) or "Pending" (gray) shown in purchase list alongside payment status

### Troubleshooting: Orphaned SRNB

If an invoice is received (`is_received=True`) but the invoice record is deleted directly (bypassing `cancel()`), SRNB is debited but never credited.

**Detection:**
```python
from django.db.models import Sum
from accounting.models import GLEntry
GLEntry.objects.filter(account__name='SRNB').aggregate(
    net=Sum('debit') - Sum('credit')
)
# Should be 0. Non-zero = orphaned SRNB balance.
```

**Prevention:** The `delete()` guard requires status `DRAFT` — but `receive_stock()` doesn't change `status`. Always call `invoice.cancel()` before deleting a received-but-not-submitted invoice. The DRAFT status + `is_received=True` combination is the only risky state.

---

## Rule 23 — Rendering Integrity: The Literal String Guard

**Symptom:** Template variables appear as literal strings in the browser, OR the page throws a `TemplateSyntaxError`.

### Root Cause #1 — Missing `|default` argument (TemplateSyntaxError)

Django's `|default` filter requires **both** the filter name AND a fallback value after the colon:

```html
<!-- ✗ BROKEN — TemplateSyntaxError -->
<input value="{{ source_purchase_order_id|default: }}">

<!-- ✓ CORRECT -->
<input value="{{ source_purchase_order_id|default:'' }}">
<input value="{{ count|default:0 }}">
```

**Rule:** After any `|default`, the colon must be immediately followed by a quoted string or integer. An empty-value `|default:` is a syntax error.

### Root Cause #2 — Copy-paste scaffolding from another module

When duplicating a template from another module (e.g., building a Purchase Receipt list from the Sales Order list), silently-wrong artefacts survive:

| What to check | Common wrong value | Correct value |
|---|---|---|
| Section header | "Selling Pipeline" | "Buying Pipeline" |
| Document ID prefix | `SO-{{ o.pk }}` | `PR-{{ o.pk }}` |
| Progress bar property | `o.per_delivered` (Sales model) | must exist on the new model |
| Empty state text | "No sales receipts found." | "No Purchase Receipts yet." |

**Rule:** A missing model property does NOT raise an error in Django templates — it silently renders as an empty string. This makes the bug invisible until someone notices the 0% progress bars.

### Root Cause #3 — Iterating a queryset with a non-existent `@property`

If `{{ o.per_billed }}` is used in a list template but `per_billed` only exists on a different model class (e.g., `PurchaseOrder`, not `PurchaseReceipt`), the template renders the progress bar with `width: %` — visually a flat 0% line, no error, hard to spot.

**Fix:** Always verify that properties used in loop templates exist on the model actually being iterated. Cross-check with `models.py` before deploying.

### Guard Checklist (run before committing any new template)

1. `grep '\|default:'` — every match must have a non-empty value after the colon
2. `grep 'Pipeline\|SO-\|per_delivered\|per_billed'` — verify each is correct for the current module
3. `{{ o.<property> }}` — cross-check with the model class being iterated in the view
4. Test with a **DRAFT** object and a **SUBMITTED** object — verify chips/badges render correctly in both states

---

## 24. The Two-Stage Purchase Invariant (Sprint 24)

**State machine:** `DRAFT → RECEIVED → SUBMITTED → CANCELLED`

### Stage 1 — Physical (register_inward)
- Triggered by the **"Register Inward Goods"** button on the create form or the **"Register Inward Goods"** button on the DRAFT detail page.
- Posts `Dr Stock In Hand / Cr SRNB` via `process_stock_movement()`.
- Sets `is_received=True`, `status='RECEIVED'`.
- After this, the document is **immutable** — it cannot be deleted, only cancelled.

### Stage 2 — Financial (finalize_purchase_invoice / submit)
- Triggered by the **"Submit Invoice"** button inside the Stage 2 finalization form on the detail page.
- Updates `invoice_number`, per-item `basic_rate`, `tax_amount`, `total_amount`, `loading_charges`, `additional_discount`, `payment_status`.
- Then calls `invoice.submit()` which posts `Dr SRNB / Cr Accounts Payable`.
- Sets `status='SUBMITTED'`. SRNB account nets exactly `0.00` after this.

### Hard Rules
1. **DRAFT save = zero GL/stock impact.** The two-button form sends `register_inward_on_save=1` for Stage 1, or no flag for plain draft save.
2. **`is_received=True` → point of no return.** `delete()` raises `ValidationError` if `is_received=True` or `status != 'DRAFT'`.
3. **Cancel from RECEIVED:** validates `batch.current_quantity >= item.quantity` for every item BEFORE reversing stock. Blocks cancel if stock was partially sold.
4. **Cancel from SUBMITTED:** reverses both stock GL AND financial GL atomically. `billed_qty` is decremented on linked PO items.
5. **Perfect Reconcile:** after `SUBMITTED`, SRNB net = `0.00` exactly. Verify via audit script.
6. **`finalize_purchase_invoice` is the sole path** from `RECEIVED → SUBMITTED` with financial field updates. Direct `submit()` calls are blocked if `status != 'RECEIVED'`.
7. **`receive_stock()` is a deprecated alias** for `register_inward()`. Do not call `receive_stock()` in new code.

### Data Migration
`0027_purchaseinvoice_received_status.py` — promotes any legacy `is_received=True, status='DRAFT'` records to `status='RECEIVED'`.

### UI Conventions
- **DRAFT detail page:** amber "Register Inward Goods" button in right panel + DRAFT warning banner.
- **RECEIVED detail page:** amber "⚠️ Goods Received — Pending Financial Finalization" banner + inline finalization form in scrollable section + "Enter Financial Details" anchor + "Cancel Document" in footer actions.
- **SUBMITTED detail page:** green "Invoice Finalized" verified-state card.
- **Status badge:** `document_status_badge.html` has amber "Goods Received" badge for `RECEIVED`.
- **Dashboard:** amber `pending_finalization_count` widget (shown only when count > 0).
- **Purchase list:** amber "Received" chip in lifecycle column; "Needs Finalization" chip in receipt column.
- **Ledger timeline:** `PurchaseInvoice` GL entries display as "Purchase (Finalized)"; `PurchaseInvoiceCancel` as "Purchase (Cancelled — Stock Reversed)"; `PurchaseReceipt` (legacy) as "Purchase (Goods Received)".

---

## Rule 24 — The Two-Stage Purchase Invariant

**[IMPLEMENTED 2026-03-18 — Sprint 24]**

All PurchaseInvoice documents follow a mandatory two-stage lifecycle:

- **Stage 1 (Physical):** `register_inward()` → `DRAFT → RECEIVED`. Posts `Dr Stock In Hand / Cr SRNB`. Physical fields only (Product, Batch, Qty, Expiry). Invoice number may be deferred.
- **Stage 2 (Financial):** `finalize_purchase_invoice` view + `submit()` → `RECEIVED → SUBMITTED`. Posts `Dr SRNB / Cr AP`. Financial fields (rates, taxes, landed cost).

**Invariants:**
1. `status='RECEIVED'` means stock is on the shelf, SRNB has a debit balance, AP is not yet credited.
2. `is_received=True` → point of no return. `delete()` raises `ValidationError` if `is_received=True` or `status != 'DRAFT'`.
3. **Cancel from RECEIVED:** validates `batch.current_quantity >= item.quantity` for every item BEFORE reversing stock. Blocks cancel if stock was partially sold.
4. **Cancel from SUBMITTED:** reverses both stock GL AND financial GL atomically. `billed_qty` is decremented on linked PO items.
5. **Perfect Reconcile:** after `SUBMITTED`, SRNB net = `0.00` exactly. Verify via audit script.
6. **`finalize_purchase_invoice` is the sole path** from `RECEIVED → SUBMITTED` with financial field updates. Direct `submit()` calls are blocked if `status != 'RECEIVED'`.
7. **`receive_stock()` is a deprecated alias** for `register_inward()`. Do not call `receive_stock()` in new code.

### Data Migration
`0027_purchaseinvoice_received_status.py` — promotes any legacy `is_received=True, status='DRAFT'` records to `status='RECEIVED'`.

### UI Conventions
- **DRAFT detail page:** amber "Register Inward Goods" button in right panel + DRAFT warning banner.
- **RECEIVED detail page:** amber "⚠️ Goods Received — Pending Financial Finalization" banner + inline finalization form in scrollable section + "Enter Financial Details" anchor + "Cancel Document" in footer actions.
- **SUBMITTED detail page:** green "Invoice Finalized" verified-state card.
- **Status badge:** `document_status_badge.html` has amber "Goods Received" badge for `RECEIVED`.
- **Dashboard:** amber `pending_finalization_count` widget (shown only when count > 0).
- **Purchase list:** amber "Received" chip in lifecycle column; "Needs Finalization" chip in receipt column.
- **Ledger timeline:** `PurchaseInvoice` GL entries display as "Purchase (Finalized)"; `PurchaseInvoiceCancel` as "Purchase (Cancelled — Stock Reversed)"; `PurchaseReceipt` (legacy) as "Purchase (Goods Received)".

---

## Rule 25 — The Linear Narrative UI Invariant

**[IMPLEMENTED 2026-03-18 — Sprint 25]**

Purchase entry forms use a **Physical-First, Progressive Disclosure** pattern. Never force financial noise on warehouse workers. Never bury critical accounting in a sidebar.

### The Two Modes

| Mode | Who uses it | Visible fields | Hidden fields |
|---|---|---|---|
| **Physical (default)** | Warehouse staff | Product, Batch, Size/Unit, Mfg Date, Exp Date, MRP, Qty | Basic Rate, Tax%, Margin%, Sell Price, Payment Summary |
| **Financial (expanded)** | Accountant | Everything | Nothing |

### Implementation Rules

1. **Zone 3 is gated.** Every per-item financial row (Basic Rate, Tax%, Margin%, Sell Price, Total) is wrapped in `x-show="showFinancials"` with a CSS transition. It is `false` by default.
2. **`showFinancials` is a per-form Alpine.js boolean.** A "Show Pricing & Margins" toggle button between Zone 2 and Zone 3 flips it.
3. **Validation is gated too.** `rowErr()` financial flags (`mrpEmpty`, `rateEmpty`, `sellEmpty`, etc.) evaluate `this.showFinancials &&` before their condition. `hasErrors` skips invoice number and financial field checks when `!showFinancials`.
4. **Invoice Number is optional in physical mode.** If omitted, `create_purchase` auto-generates a `DRAFT-{timestamp}` reference. The real invoice number is entered during Stage 2 finalization via `finalize_purchase_invoice`.
5. **Right sidebar adapts.** When `!showFinancials`, the sidebar shows a Physical Receipt Mode placeholder with item count + total qty. The Grand Total display shows `—` with gray text.
6. **Landed Cost Distribution.** `finalize_purchase_invoice` proportionally distributes `loading_charges` across line items by `item.total_amount / grand_total`. Each `batch.purchase_price` is updated to the landed rate. MAP is then recalculated from scratch via `recalculate_product_map_from_batches()` — this corrects the MAP that was initially posted with rate=0 at Stage 1.
7. **Conditional UniqueConstraint.** `invoice_number` uniqueness is scoped to `status='SUBMITTED'` only via `UniqueConstraint(condition=Q(status='SUBMITTED'))`. CANCELLED invoice numbers can be freely reused. For MySQL (which does not support partial indexes), enforcement is at the Django application layer via `validate_unique()`.

### Anti-Patterns (Never Do)
- **Never** show financial columns to a warehouse worker by default.
- **Never** put loading/hamali/discount in a sidebar. They belong in the Financial section.
- **Never** block a Stage 1 save because invoice number or rate is missing.
- **Never** recalculate MAP in the create step with a 0 rate — skip it and correct at finalization.

---

## Rule 26 — The Data-Aware Prefill Invariant

**[IMPLEMENTED 2026-03-19 — Sprint 26]**

Purchase entry forms **auto-populate financial fields from purchase history** using a prioritised fallback chain. This eliminates re-keying and signals when data comes from history vs. user input.

### The Intelligence Engine

**Endpoint:** `GET /purchases/fetch-pricing/?product_id=&batch_number=&size=`

**Priority chain (highest to lowest):**
1. Most-recent `PurchaseItem` for same `product_id + batch_number` — exact SKU match
2. Most-recent `PurchaseItem` for same `product_id + size` — same product variant
3. Most-recent `PurchaseItem` for same `product_id` — any variant of this product

**Response fields:** `{found, source, basic_rate, tax_percentage, margin, selling_price, mrp}`

### Trigger Points

| Event | Action |
|---|---|
| User selects a product from the autocomplete | `fetchPricing(row)` fired in `selectProduct()` |
| User changes batch number field (`@change`) | `fetchPricing(row)` re-fired |
| User changes size field (`@change`) | `fetchPricing(row)` re-fired with new size |

### Prefill Rules

1. **Never overwrite user-entered values.** Prefill only fires if the field is currently empty (`!row.rate`, `!row.mrp`, etc.).
2. **Blue Glow = "Validation Required."** Prefilled fields get `ring-2 ring-blue-400`. The glow clears on the first `@input` event from the user.
3. **Tax rate is always live.** `product_tax_rate` is taken from the product's category (server-side) and is NOT stored in `row.prefilled` — it can't be overridden by history.
4. **Silent failure.** If the endpoint is unavailable or returns `{found: false}`, the form behaves exactly as before — no errors shown.

### Center Stage Financial Form (Page B — Detail)

The `finalize_purchase_invoice` form lives in the **main content area**, not the sidebar, when `status == 'RECEIVED'`. Layout:

| Column | Field |
|---|---|
| Product | Name + Batch |
| Qty | Read-only |
| Basic Rate | Editable `<input>` |
| Tax % | Read-only (from category) |
| Hamali/Unit | Computed from Total Loading ÷ Total Qty |
| Margin % | Editable, computes Sell Price |
| Sell Price | Editable, computes Margin % — turns **RED** if < net cost |

### Margin Guard

Alpine.js `isNegativeMargin` computed: `sell > 0 && sell < netCost`.
When true: sell price input gets `ring-2 ring-red-400 border-red-300` + "⚠ Margin negative" warning.
`netCost = rate × (1 + tax/100) + hamali_per_unit`

### Triad Match Consultation Pattern (Sprint 27 addition)

When `source != 'batch'` (i.e. pricing came from product/size history, not the exact batch), the user is presenting a **new batch for a known product**. In this case:
- Do **not** silently prefill — instead open the **Consultation Modal**.
- The modal shows "Last Recorded Financials" with the 4 key fields (Rate, MRP, Margin, Sell Price).
- Two buttons: **[ Use Previous Rates ]** (calls `useConsultPricing()`) and **[ Enter New Rates ]** (calls `dismissConsult()`, leaves fields blank).
- `useConsultPricing()` applies the same prefill logic as a silent match (only empty fields, blue glow).
- If `source == 'batch'` (exact batch history found): always silent prefill, no modal.

**Future modules (Sales Returns, Quotations) must use this same consultation pattern** whenever historical data exists but the current document is a new variant.

### Anti-Patterns
- **Never** pre-fill if the field already has a user value.
- **Never** show a red validation error when pricing history isn't found — just leave blank.
- **Never** hard-code tax rates in JS — always read from the product's category via the server.
- **Never** put the finalization form in a sidebar for RECEIVED invoices — it belongs on center stage.
- **Never** silently overwrite rates for a new batch — always ask via the consultation modal.

---

## Rule 27: The Atomic Clear Invariant

**Context:** When a user selects a new batch for a known product, the Consultation Modal shows last-recorded financials. If the user clicks **[ Enter New Rates ]**, ALL pre-filled or stale fields must be wiped atomically — zero residue.

### State Machine

```
Triad complete (Product + Batch + Size)
    │
    ├─ source == 'batch' (exact match found)
    │       → Silent Prefill (blue glow ring-blue-400)
    │       → Fill: mfg_date, expiry_date, mrp, rate, margin, sell_price
    │
    └─ source != 'batch' (new batch for known product)
            → Open Consultation Modal
                │
                ├─ [ Use Previous Rates ] → useConsultPricing()
                │       → Fill: mrp, rate, margin, sell_price (amber glow ring-amber-400)
                │       → Leave mfg_date / expiry_date BLANK (unique to new batch)
                │
                └─ [ Enter New Rates ] → dismissConsult()  ← THE ATOMIC CLEAR
                        → Wipe: mfg_date, expiry_date, mrp, rate, margin, sell_price
                        → Reset: row.prefilled = {}, row.consultFilled = {}
                        → User starts from a 100% clean slate
```

### Implementation Rules
- `row.prefilled.FIELD = true` → blue glow (`ring-2 ring-blue-400`) — exact batch history
- `row.consultFilled.FIELD = true` → amber glow (`ring-2 ring-amber-400`) — consulted from previous batch
- Glow clears on `@input` — clear BOTH `row.prefilled.FIELD` AND `row.consultFilled.FIELD`
- `mfg_date` / `expiry_date` are NEVER filled by the consultation path — they are batch-unique
- Backend sends `mfg_date` + `expiry_date` in `_build_response` for exact batch matches only

### Anti-Patterns
- **Never** leave stale financial data when the user clicks "Enter New" — atomic clear means everything goes
- **Never** pre-fill mfg_date/expiry_date from a different batch's history — dates are batch-unique
- **Never** use the same `prefilled` tracker for both silent prefill and consultation prefill — they need separate glows

---

## Rule 28: Selling Price Sovereignty

**Invariant:** `batch.base_selling_price` is a **user-defined business decision**. It must NEVER be silently overwritten by MRP at any stage of the document lifecycle.

### The Bug Pattern (Never Repeat)
```python
# ❌ WRONG — silently overwrites user decision with MRP when form field is empty
sell_price = float(selling_prices[i]) if selling_prices[i] else mrp
batch.base_selling_price = sell_price or batch.base_selling_price
```

### The Fix Pattern
```python
# ✅ CORRECT — default to 0, only update if user entered a real value
sell_price = float(selling_prices[i]) if selling_prices[i] else 0
if sell_price:
    batch.base_selling_price = sell_price
# If sell_price == 0: leave batch.base_selling_price untouched
```

### The Three Code Paths to Guard
| View | Location | Guard Applied |
|------|----------|---------------|
| `create_purchase` (standard form) | `views.py` ~line 1066 | `else 0` not `else mrp` |
| `create_purchase` (buying pipeline) | `views.py` ~line 1290 | `else 0` not `else mrp` |
| `finalize_purchase_invoice` (Stage 2) | `views.py` ~line 2520 | reads `selling_price_{id}`, MRP ceiling check, then sets batch |

### finalize_purchase_invoice Sovereignty Block
When processing Stage 2 (RECEIVED → SUBMITTED):
1. Read `selling_price_{item.id}` and `margin_{item.id}` from POST
2. If `sell_price > 0`: validate `sell_price <= batch.mrp`, then save to `item.selling_price`, `item.profit_margin`, `batch.base_selling_price`
3. If `sell_price == 0`: **do nothing** — leave existing value untouched

### MRP vs Selling Price Distinction
| Field | Location | Meaning |
|-------|----------|---------|
| `Batch.mrp` | inventory/models.py | Maximum Retail Price — the ceiling, never the actual price |
| `Batch.base_selling_price` | inventory/models.py | Actual price decision — set by user, not by system |
| `PurchaseItem.selling_price` | transactions/models.py | Item-level price on this specific invoice |

### Validation Invariant
- `selling_price ≤ MRP` — enforced at `finalize_purchase_invoice` (ValidationError if violated)
- `selling_price ≥ basic_rate` — enforced in buying pipeline safety net (Path 2 line ~1306)

---

## References

- **Generic Refactor Framework** — See `.agent/AgriCRM_Generic_Refactor_Framework.md` for reusable patterns (Sales, Inventory, Master Data modules)
- **Audit Script** — `C:\agri_crm\audit_gl_reconciliation.py` (read-only; run after every sprint)
- **Last Updated** — 2026-03-22 (Sprint 29: Dashboard Intelligence Hub + Rule 29)

---

## Rule 29: Dashboard Data Consistency

All numbers on the dashboard must reconcile perfectly with the detailed ledger. A discrepancy is a bug, not an approximation.

### Authoritative Sources (Never Deviate)

| Metric | Source | Query |
|--------|--------|-------|
| Revenue | `SalesInvoice.grand_total` | `filter(status='ACTIVE', date=today)` |
| COGS / Profit | `SalesItem.quantity × Batch.purchase_price` | `batch__purchase_price` = landed cost post-hamali (Sprint 45) |
| SRNB Balance | `GLEntry` | `filter(account__name='Stock Received But Not Billed')` — cr minus dr |
| Pending count | `PurchaseInvoice` | `filter(status='RECEIVED').count()` |
| Low Stock | `Batch` | `current_quantity__lt=10, is_active=True` (no min_stock_level field) |
| Dead Stock | `Batch` excluding `StockMovement` | outward movements (`quantity__lt=0`) in last 60 days |

### Critical Invariants
- **SRNB balance must be queried from GLEntry**, not from `PurchaseInvoice.total_amount`. Un-finalized physical-first invoices have `total_amount=0` — the GL is always authoritative.
- **SalesInvoice status is `'ACTIVE'`**, not `'SUBMITTED'`. Using wrong status = silent zero.
- **`Batch.purchase_price` = landed cost** (updated by `finalize_purchase_invoice` with hamali distribution). Never use a fixed purchase price for profit calculation.
- **Profit = Revenue − COGS**, where COGS = `SUM(qty × batch.purchase_price)` per SalesItem. Tax is included in `total_amount` (revenue) but NOT in `purchase_price` (cost) — this is correct because tax is a pass-through.

### Chart.js Isolation
Load Chart.js **only in the dashboard template**, never in `base.html`. Keeps all other pages free of the 60KB library.
