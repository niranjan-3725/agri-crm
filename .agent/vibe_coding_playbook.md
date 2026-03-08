# AgriCRM — Vibe Coding Playbook

> Permanent memory for AI agents. Read this before touching templates, views, or models.
> Last updated: 2026-03-08

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

## References

- **Generic Refactor Framework** — See `.agent/AgriCRM_Generic_Refactor_Framework.md` for reusable patterns (Sales, Inventory, Master Data modules)
- **Last Updated** — 2026-03-08 (Payables Refactor — Rule 12 added)
