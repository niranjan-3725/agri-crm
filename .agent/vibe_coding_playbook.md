# AgriCRM — Vibe Coding Playbook

> Permanent memory for AI agents. Read this before touching templates, views, or models.
> Last updated: 2026-03-05

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

**Detection script:**
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

## Quick Diagnostic Checklist

When a detail page component isn't rendering:

1. **Literal tag?** → Is the `{% include %}` tag on ONE line?
2. **Missing context?** → Does the view pass all variables the component needs?
3. **Wrong template file?** → Is the dev server running from the worktree (`peaceful-borg`) not from the main repo? They have separate template directories.
4. **Alpine not loaded?** → Components using `x-data` / `x-show` need Alpine.js on the page. Check `base.html`.
5. **Status guard blocking?** → Is the component wrapped in `{% if invoice.status == '...' %}`?
