# AgriCRM Generic Refactor Framework

> A reusable blueprint for standardizing ERP modules (Sales, Inventory, Master Data).
> Extracted from the successful Purchase Module refactoring (Sprint 9–16).
> Last updated: 2026-03-05

---

## Overview

This framework documents four critical architectural patterns discovered during the Purchase Module refactoring:

1. **Triple-Entry State Machine** — Immutable document lifecycle with atomic ledger effects
2. **Ledger Announcement Pattern** — How financial documents trigger GL + stock simultaneously
3. **Tax-Exclusive Valuation** — Cost basis stored separately from GST for compliance and accuracy
4. **Jony Ive UX Validation** — Real-time, context-aware field validation without bulk error banners

Each pattern is battle-tested in the Purchase Module and ready for reuse in Sales, Inventory, and Master Data modules.

---

## Pattern 1: Triple-Entry State Machine

### Problem

Documents must track three effects simultaneously:
1. **GL Effects** — Accounts Payable / Accounts Receivable, tax liabilities, revenue
2. **Stock Effects** — Inventory movements, batch quantity tracking
3. **Workflow Effects** — Status transitions, auditability

Without coordination, partial failures leave the ledger in an inconsistent state that is nearly impossible to debug.

### Solution

Enforce a strict three-state lifecycle with atomic transition methods:

```
DRAFT ──submit()──► SUBMITTED ──cancel()──► CANCELLED
  │                                              │
  └──delete() (hard)                    (no way back)
```

**State Definitions:**

| State | Mutable? | GL Posted? | Stock Posted? | Reversible? |
|-------|----------|-----------|--------------|------------|
| DRAFT | ✓ Yes | ✗ No | ✗ No | ✗ Hard delete only |
| SUBMITTED | ✗ No | ✓ Yes | ✓ Yes | ✓ Via cancel() |
| CANCELLED | ✗ No | ✗ Reversed | ✗ Reversed | ✗ Read-only |

### Implementation

**Model Definition:**
```python
from django.db import models, transaction
from django.core.exceptions import ValidationError

DOCUMENT_STATUS_CHOICES = [
    ('DRAFT', 'Draft'),
    ('SUBMITTED', 'Submitted'),
    ('CANCELLED', 'Cancelled'),
]

class TransactionDocument(models.Model):  # Base class for invoices
    status = models.CharField(
        max_length=20,
        choices=DOCUMENT_STATUS_CHOICES,
        default='DRAFT'
    )

    def submit(self):
        """Transition DRAFT → SUBMITTED with all side effects atomic."""
        if self.status != 'DRAFT':
            raise ValidationError("Only DRAFT documents can be submitted.")

        with transaction.atomic():
            # Step 1: Create/submit fulfillment document (stock effects)
            # Example: PurchaseReceipt.submit() calls process_stock_movement()

            # Step 2: Post GL entries (AP/AR/Revenue/Tax)
            # Example: post_purchase_invoice_gl() creates Dr SRNB / Cr AP

            # Step 3: Update tracking fields
            # Example: PurchaseOrderItem.billed_qty tracking

            # Step 4: Atomic status transition
            self.status = 'SUBMITTED'
            self.save()

    def cancel(self):
        """Transition SUBMITTED → CANCELLED by reversing all effects."""
        if self.status != 'SUBMITTED':
            raise ValidationError("Only SUBMITTED documents can be cancelled.")

        with transaction.atomic():
            # Step 1: Reverse fulfillment document (stock effects)
            # Example: Cancel linked PurchaseReceipt with negative quantities

            # Step 2: Reverse GL entries
            # Example: reverse_document_gl() deletes all GL entries for this doc

            # Step 3: Reverse tracking fields
            # Example: Undo PurchaseOrderItem.billed_qty updates

            # Step 4: Atomic status transition
            self.status = 'CANCELLED'
            self.save()

    def delete(self, *args, **kwargs):
        """Only allow hard delete if DRAFT (no effects to reverse)."""
        if self.status != 'DRAFT':
            raise ValidationError(
                "Only DRAFT documents can be deleted. "
                "Use .cancel() instead to reverse a SUBMITTED document."
            )
        models.Model.delete(self, *args, **kwargs)
```

**Template Guards (in detail/edit views):**
```html
{# Only show Edit button for DRAFT documents #}
{% if document.status == 'DRAFT' %}
    <a href="{% url 'edit_url' document.id %}">Edit Draft</a>
{% endif %}

{# Only show Submit button for DRAFT documents #}
{% if document.status == 'DRAFT' %}
    <form method="POST" action="{% url 'submit_url' document.id %}">
        {% csrf_token %}
        <button type="submit">Submit</button>
    </form>
{% endif %}

{# Only show Cancel button for SUBMITTED documents #}
{% if document.status == 'SUBMITTED' %}
    <form method="POST" action="{% url 'cancel_url' document.id %}">
        {% csrf_token %}
        <button type="submit">Cancel Document</button>
    </form>
{% endif %}
```

### Key Rules

1. **Never** mutate a SUBMITTED document, even to "fix a typo."
2. **Always** wrap multi-step transitions in `transaction.atomic()`.
3. **Reverse all effects** when cancelling — GL, stock, tracking fields.
4. **Guard edit/delete UI** behind status checks.

---

## Pattern 2: Ledger Announcement Pattern

### Problem

When a document is submitted, multiple systems need to be notified:
- **Stock System** → Update batch quantities, create StockMovement records
- **GL System** → Create AP/AR/Revenue/Tax entries
- **Fulfillment System** → Link PurchaseReceipt or DeliveryNote

Without explicit announcement, changes are hidden and impossible to audit.

### Solution

**The Dual-Document Architecture:**

Financial invoices (PurchaseInvoice, SalesInvoice) **announce** their effects to two separate documents:

1. **Fulfillment Document** (PurchaseReceipt, DeliveryNote) — handles stock movements
2. **GL Service** (post_purchase_invoice_gl, post_sales_invoice_gl) — posts AP/AR/Revenue/Tax

Both are triggered atomically from the invoice's `submit()` method.

**Diagram:**
```
                    ┌─────────────────────┐
                    │  PurchaseInvoice    │
                    │  .submit()          │
                    └──────────┬──────────┘
                               │
                ┌──────────────┼──────────────┐
                ▼              ▼              ▼
        ┌────────────────┐  ┌─────────────┐  ┌──────────────────┐
        │ PurchaseReceipt│  │   GL Entry  │  │ PO Item Tracking │
        │ .submit()      │  │ (SRNB, AP)  │  │ (billed_qty)     │
        │ [Stock]        │  │ [Ledger]    │  │ [Procurement]    │
        └────────────────┘  └─────────────┘  └──────────────────┘

        All wrapped in transaction.atomic()
```

### Implementation

**Purchase Module Example:**
```python
# transactions/models.py
class PurchaseInvoice(models.Model):
    def submit(self):
        """Atomically announce to Stock + GL + Procurement."""
        if self.status != 'DRAFT':
            raise ValidationError("Only DRAFT invoices can be submitted.")

        with transaction.atomic():
            # Announcement 1: Create and submit fulfillment document (stock)
            receipt, created = PurchaseReceipt.objects.get_or_create(
                invoice=self,
                defaults={
                    'supplier': self.supplier,
                    'date': self.date,
                }
            )
            if created:
                # Copy items from invoice to receipt
                for item in self.items.all():
                    PurchaseReceiptItem.objects.create(
                        receipt=receipt,
                        batch=item.batch,
                        quantity=item.quantity,
                        purchase_order_item=item.purchase_order_item,
                    )

            # Submit the fulfillment document (triggers stock movements)
            receipt.submit()

            # Announcement 2: Post GL entries (AP + tax + SRNB)
            from accounting.services import post_purchase_invoice_gl
            post_purchase_invoice_gl(self)

            # Announcement 3: Update procurement tracking
            for item in self.items.all():
                if item.purchase_order_item:
                    item.purchase_order_item.billed_qty += item.quantity
                    item.purchase_order_item.save(update_fields=['billed_qty'])

            # Atomic status transition
            self.status = 'SUBMITTED'
            self.save()

    def cancel(self):
        """Atomically reverse all announcements."""
        from accounting.services import reverse_document_gl
        if self.status != 'SUBMITTED':
            raise ValidationError("Only SUBMITTED documents can be cancelled.")

        with transaction.atomic():
            # Reversal 1: Cancel fulfillment document (stock reversal)
            receipt = self.purchase_receipt
            if receipt and receipt.status == 'SUBMITTED':
                receipt.cancel()

            # Reversal 2: Delete GL entries
            reverse_document_gl('PurchaseInvoice', self.id)

            # Reversal 3: Undo procurement tracking
            for item in self.items.all():
                if item.purchase_order_item:
                    item.purchase_order_item.billed_qty -= item.quantity
                    item.purchase_order_item.save(update_fields=['billed_qty'])

            # Atomic status transition
            self.status = 'CANCELLED'
            self.save()
```

**Fulfillment Document Example:**
```python
# transactions/models.py
class PurchaseReceipt(models.Model):
    """Handles stock movements when submitted."""
    def submit(self):
        if self.status != 'DRAFT':
            raise ValidationError("Only DRAFT documents can be submitted.")

        with transaction.atomic():
            # Create stock movements (which auto-trigger GL via post_stock_gl)
            from inventory.services import process_stock_movement

            for item in self.items.all():
                process_stock_movement(
                    batch_id=item.batch.id,
                    quantity=item.quantity,
                    doc_type='PurchaseReceipt',  # Triggers Dr SIH / Cr SRNB GL
                    doc_id=self.id,
                )

            self.status = 'SUBMITTED'
            self.save()

    def cancel(self):
        """Reverse by posting negative stock movements."""
        if self.status != 'SUBMITTED':
            raise ValidationError("Only SUBMITTED documents can be cancelled.")

        with transaction.atomic():
            from inventory.services import process_stock_movement

            for item in self.items.all():
                process_stock_movement(
                    batch_id=item.batch.id,
                    quantity=-item.quantity,  # Negative = reversal
                    doc_type='PurchaseReceiptCancel',
                    doc_id=self.id,
                )

            self.status = 'CANCELLED'
            self.save()
```

**GL Service Example:**
```python
# accounting/services.py
from decimal import Decimal
from .models import GLEntry, Account

def make_gl_entries(reference_type: str, reference_id: int, entries: list[dict]) -> list[GLEntry]:
    """Create balanced GL entries (debits == credits)."""
    total_debit = sum(e.get('debit', Decimal('0')) for e in entries)
    total_credit = sum(e.get('credit', Decimal('0')) for e in entries)

    if total_debit != total_credit:
        raise ValueError(f"Unbalanced: {total_debit} != {total_credit}")

    created = []
    for entry in entries:
        gl = GLEntry.objects.create(
            account=Account.objects.get(name=entry['account_name']),
            debit=entry.get('debit', Decimal('0')),
            credit=entry.get('credit', Decimal('0')),
            reference_type=reference_type,
            reference_id=reference_id,
        )
        created.append(gl)

    return created

def post_purchase_invoice_gl(invoice) -> list[GLEntry]:
    """Post AP / Tax / SRNB GL entries when invoice is submitted.

    Dr  Stock Received But Not Billed   base_amount
    Dr  CGST Receivable                 total_cgst
    Dr  SGST Receivable                 total_sgst
    Cr  Accounts Payable                total_amount

    This entry stays until the invoice is cancelled or the purchase receipt is billed.
    """
    total_amount = Decimal(str(invoice.total_amount))

    # Calculate taxes from items
    total_tax = sum(Decimal(str(item.tax_amount)) for item in invoice.items.all())

    # Split GST 50/50 (Indian GST law)
    total_cgst = (total_tax / 2).quantize(Decimal('0.01'))
    total_sgst = total_tax - total_cgst

    base_amount = total_amount - total_tax

    entries = [
        {'account_name': 'Stock Received But Not Billed', 'debit': base_amount, 'credit': Decimal('0')},
        {'account_name': 'CGST Receivable', 'debit': total_cgst, 'credit': Decimal('0')},
        {'account_name': 'SGST Receivable', 'debit': total_sgst, 'credit': Decimal('0')},
        {'account_name': 'Accounts Payable', 'debit': Decimal('0'), 'credit': total_amount},
    ]

    # Remove zero-value lines
    entries = [e for e in entries if e['debit'] != 0 or e['credit'] != 0]

    return make_gl_entries('PurchaseInvoice', invoice.id, entries)

def reverse_document_gl(reference_type: str, reference_id: int) -> None:
    """Delete all GL entries for a document (used during cancel)."""
    GLEntry.objects.filter(
        reference_type=reference_type,
        reference_id=reference_id,
    ).delete()
```

### Stock GL Routing

When `PurchaseReceipt.submit()` calls `process_stock_movement()`, the stock service automatically posts GL entries using this routing:

```python
GL_ROUTING = {
    'PurchaseReceipt': ('Stock In Hand', 'Stock Received But Not Billed'),
    'DeliveryNote': ('Cost of Goods Sold', 'Stock In Hand'),
    'SalesReturn': ('Stock In Hand', 'Cost of Goods Sold'),
}
```

This creates the classic inventory GL pattern:
```
Dr Stock In Hand (asset)
Cr Stock Received But Not Billed (liability, cleared on invoice)
```

### Key Rules

1. **Announce to all systems** — Stock, GL, and Procurement simultaneously
2. **Wrap in atomic()** — All-or-nothing semantics
3. **Reverse all announcements** — When cancelling, undo stock, GL, and tracking
4. **No partial posting** — Either all effects post or none do

---

## Pattern 3: Tax-Exclusive Valuation

### Problem

In India (and most jurisdictions), GST is legally separate from the cost basis:
- **Cost basis** (what you paid the vendor) = basic rate, pre-tax
- **Taxes** = CGST + SGST (5–28% depending on item category)
- **Invoice total** = cost + taxes

For inventory accuracy and GST compliance, these must be tracked separately in:
- Purchase Item records
- Stock Batch valuations
- GL entries (SRNB gets cost, tax goes to receivable accounts)

### Solution

**Store basic_rate pre-tax. Calculate tax separately.**

```python
# View (transactions/views.py)
rate_pre_tax = float(purchase_rates[i])  # What you paid
product = Product.objects.get(name=p_name)
tax_rate = float(product.category.total_tax)  # 5%, 18%, etc.

tax_amount_per_unit = rate_pre_tax * (tax_rate / 100)
total_tax_amount = tax_amount_per_unit * qty
net_cost_per_unit = rate_pre_tax + tax_amount_per_unit
total_line_amount = net_cost_per_unit * qty

# Save pre-tax cost to batch
batch.purchase_price = rate_pre_tax  # Cost basis, no tax

# Save pre-tax cost + separate tax to item
PurchaseItem.objects.create(
    invoice=invoice,
    batch=batch,
    quantity=qty,
    basic_rate=rate_pre_tax,          # Cost, pre-tax
    tax_amount=total_tax_amount,       # Tax only
    total_amount=total_line_amount,    # Cost + tax
)
```

**GL Posting:**
```python
# GL debit gets base_amount (pre-tax), not total
base_amount = total_amount - total_tax

entries = [
    {'account_name': 'Stock Received But Not Billed', 'debit': base_amount, 'credit': Decimal('0')},
    {'account_name': 'CGST Receivable', 'debit': total_cgst, 'credit': Decimal('0')},  # Tax to separate account
    {'account_name': 'SGST Receivable', 'debit': total_sgst, 'credit': Decimal('0')},
    {'account_name': 'Accounts Payable', 'debit': Decimal('0'), 'credit': total_amount},  # AP gets total
]
```

**Display in Detail Page:**
```html
{# Cost basis (pre-tax) #}
<p class="text-xs font-bold text-blue-600">Base Rate <span class="normal-case">(ex-tax)</span></p>
<p class="text-lg font-bold">₹{{ item.basic_rate|floatformat:2 }}</p>

{# Separate tax display #}
<p class="text-xs font-bold text-orange-600">Tax Amount</p>
<p class="text-lg font-bold">₹{{ item.tax_amount|floatformat:2 }}</p>

{# Total (cost + tax) #}
<p class="text-xs font-bold text-gray-600">Total</p>
<p class="text-lg font-bold">₹{{ item.total_amount|floatformat:2 }}</p>
```

### Why This Matters

1. **GST Compliance** — Indian GST law requires separate tracking of tax amounts
2. **Stock Valuation** — Batch.purchase_price (cost basis) is used for moving-average cost, not inflated by tax
3. **Ledger Clarity** — GL shows exactly what went to inventory (base) vs. what's a tax receivable
4. **Audit Trail** — Clear separation prevents accidental tax inflation in cost of goods sold

### Key Rules

1. **Store basic_rate pre-tax** — Always
2. **Calculate tax separately** — per_unit_tax = basic_rate × (tax_rate / 100)
3. **GL gets base_amount** — SRNB/inventory GL gets cost only, not total
4. **Display both clearly** — Show "₹X (ex-tax)" to be explicit

---

## Pattern 4: Jony Ive UX Validation

### Problem

Traditional forms show all errors at once (bulk error banner) or on submit. This forces users to mentally parse multiple failures and re-submit multiple times.

Instead, **context-aware real-time validation** reduces friction:
- Per-field `touched` tracking (error shows only after blur)
- Inline error messages (not banners)
- **Verified state UI** (blue tint + checkmark when selection confirmed)
- **Focus flow** (move cursor to next field after valid selection)

### Solution

**HTML Structure (Alpine.js v3):**
```html
<div x-data="purchaseForm()" @submit.prevent="validateSubmit">
    {# Per-field touch tracking #}
    <input
        name="supplier_name"
        x-model="supplierSearch"
        @blur="supplierTouched = true"
        @focus="supplierOpen = true"
        :class="supplierId
            ? 'border-blue-300 bg-blue-50/30'        {# Verified state (blue) #}
            : (supplierTouched || submitAttempted) && !supplierId
                ? 'border-red-400 bg-red-50/50'      {# Error state (red) #}
                : 'border-gray-100'"
    />

    {# Inline error message (shows only if touched AND no ID) #}
    {% if supplierTouched or submitAttempted %}
        {% if not supplierId %}
            <p class="field-error-msg">Select from the list</p>
        {% endif %}
    {% endif %}

    {# Dropdown with @mousedown.prevent to prevent blur-before-click #}
    <div x-show="supplierOpen" @mousedown.prevent>
        <template x-for="s in filteredSuppliers" :key="s.id">
            <div @click="selectSupplier(s)">{{ s.name }}</div>
        </template>
    </div>

    {# Hidden ID input (stores the actual value) #}
    <input type="hidden" name="supplier_id" x-model="supplierId" />
</div>
```

**JavaScript (Alpine.js):**
```javascript
function purchaseForm() {
    return {
        // ── Header Fields ──
        supplierId: '',
        supplierSearch: '',
        supplierOpen: false,
        supplierTouched: false,
        filteredSuppliers: [],

        invoiceDate: new Date().toISOString().split('T')[0],
        invoiceDateTouched: false,

        invoiceNumber: '',
        invoiceNumberTouched: false,

        // ── Line Items ──
        rows: [
            { product_id: '', product_name: '', product_tax_rate: 0, batch_number: '',
              mfg_date: '', expiry_date: '', mrp: 0, basic_rate: 0, selling_price: 0,
              qty: 0, touched: { product: false, mfgDate: false, expDate: false, qty: false } }
        ],

        // ── Form State ──
        submitAttempted: false,

        // ── Date Validation ──
        get today() {
            return new Date().toISOString().split('T')[0];
        },

        // ── Header Errors ──
        get headerErr() {
            return {
                supplier: (this.supplierTouched || this.submitAttempted) && !this.supplierId,
                date: (this.invoiceDateTouched || this.submitAttempted) && !this.invoiceDate,
                number: (this.invoiceNumberTouched || this.submitAttempted) && !this.invoiceNumber,
            };
        },

        // ── Row Errors (per-row validation) ──
        rowErr(row) {
            const mrp = parseFloat(row.mrp) || 0;
            const rate = parseFloat(row.basic_rate) || 0;
            const sell = parseFloat(row.selling_price) || 0;
            const today = this.today;

            return {
                product: row.touched.product && !row.product_id,
                mfgDate: row.touched.mfgDate && row.mfg_date && row.mfg_date > today,  # Future date
                expDate: row.touched.expDate && row.expiry_date && row.expiry_date <= row.mfg_date,  # Before mfg
                mrpVsRate: mrp > 0 && rate > 0 && rate > mrp,                          # Rate > MRP (invalid)
                sellVsMrp: mrp > 0 && sell > 0 && sell > mrp,                          # Sell > MRP (invalid)
                sellVsRate: rate > 0 && sell > 0 && sell < rate,                       # Sell < Rate (invalid)
                qty: row.touched.qty && row.qty <= 0,
            };
        },

        // ── Selection Logic ──
        selectSupplier(s) {
            this.supplierId = s.id;
            this.supplierSearch = s.name;
            this.supplierOpen = false;
            this.supplierTouched = true;

            // Focus flow: move to next field
            this.$nextTick(() => {
                document.querySelector('[name="invoice_number"]').focus();
            });
        },

        selectProduct(row, item, rowIndex) {
            row.product_id = item.id;
            row.product_name = item.name;
            row.product_tax_rate = item.tax_rate;
            row.touched.product = true;
            row.showDropdown = false;

            // Focus flow: move to batch field
            this.$nextTick(() => {
                const batchInputs = document.querySelectorAll('[name="batch_number[]"]');
                if (batchInputs[rowIndex]) batchInputs[rowIndex].focus();
            });
        },

        // ── Submit Handler ──
        validateSubmit(e) {
            // Mark all fields as touched
            this.supplierTouched = true;
            this.invoiceDateTouched = true;
            this.invoiceNumberTouched = true;
            this.rows.forEach(row => {
                row.touched = { product: true, mfgDate: true, expDate: true, qty: true };
            });
            this.submitAttempted = true;

            // Check if any errors exist
            if (this.hasErrors) {
                e.preventDefault();

                // Scroll to first error
                this.$nextTick(() => {
                    const firstError = document.querySelector('.field-error-msg');
                    if (firstError) {
                        firstError.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    }
                });
            }
        },

        get hasErrors() {
            // Header errors
            if (this.headerErr.supplier || this.headerErr.date || this.headerErr.number) return true;

            // Row errors
            return this.rows.some(row => {
                const err = this.rowErr(row);
                return Object.values(err).some(v => v);
            });
        }
    };
}
```

**CSS for Verified State:**
```css
/* Verified (selection confirmed): blue tint + checkmark icon */
input.verified {
    @apply border-blue-300 bg-blue-50/30 focus:border-blue-400/40 focus:shadow-lg focus:shadow-blue-500/5;
}

input.verified::after {
    content: '✓';  /* Checkmark icon */
    color: #059669;  /* emerald-600 */
}

/* Error state: red tint */
input.error {
    @apply border-red-400 bg-red-50/50 focus:border-red-400;
}

/* Inline error message */
.field-error-msg {
    @apply text-xs font-bold text-red-600 mt-1 block;
}
```

**Backend Validation (Safety Net):**
```python
# transactions/views.py
from django.core.exceptions import ValidationError

# In create_purchase view, loop through items:
for i in range(len(product_names)):
    p_name = product_names[i]
    if not p_name: continue

    product = Product.objects.get(name=p_name)
    rate_pre_tax = float(purchase_rates[i]) if purchase_rates[i] else 0
    sell_price = float(selling_prices[i]) if selling_prices[i] else 0
    mrp = float(mrps[i]) if mrps[i] else 0
    qty = int(quantities[i]) if quantities[i] else 0

    # Backend price hierarchy validation
    row_label = f"Item {i+1} ({p_name})"
    if mrp > 0 and rate_pre_tax > mrp:
        raise ValidationError(
            f"{row_label}: Basic Rate cannot exceed MRP."
        )
    if mrp > 0 and sell_price > mrp:
        raise ValidationError(
            f"{row_label}: Sell Price cannot exceed MRP."
        )
    if rate_pre_tax > 0 and sell_price > 0 and sell_price < rate_pre_tax:
        raise ValidationError(
            f"{row_label}: Sell Price cannot be less than Basic Rate."
        )

    # Guard: reject blank product submissions
    if not any(n.strip() for n in product_names):
        raise ValidationError("At least one product item is required.")
```

**Model Clean Method (Additional Safety):**
```python
# transactions/models.py
class PurchaseItem(models.Model):
    def clean(self):
        """Validate price hierarchy at model level."""
        errors = {}

        if self.selling_price < self.basic_rate:
            errors['selling_price'] = "Sell Price cannot be less than Basic Rate."

        if self.basic_rate > self.batch.mrp:
            errors['basic_rate'] = "Basic Rate cannot exceed MRP."

        if self.selling_price > self.batch.mrp:
            errors['selling_price'] = "Sell Price cannot exceed MRP."

        if errors:
            raise ValidationError(errors)
```

### Key Rules

1. **Per-field touch tracking** — Error shows only after blur
2. **Inline errors only** — No bulk error banners
3. **Verified state UI** — Blue tint + checkmark when selection confirmed
4. **Focus flow** — Move cursor to next field after valid selection
5. **Blur guard** — `@mousedown.prevent` on dropdown to prevent blur-before-click race
6. **Backend safety net** — Validate at view + model level, never trust frontend

---

## Applying the Framework to a New Module

### Checklist for Sales Module Refactoring

- [ ] **State Machine** — Define DRAFT/SUBMITTED/CANCELLED states with submit()/cancel() methods wrapped in `transaction.atomic()`
- [ ] **Ledger Announcement** — Create SalesInvoice.submit() to announce to: DeliveryNote (stock), GL (AR/Revenue/Tax), SalesOrderItem tracking
- [ ] **Tax-Exclusive Valuation** — Store basic_rate pre-tax; calculate tax separately; post GL with base_amount only
- [ ] **Jony Ive UX** — Implement per-field touch tracking, inline errors, verified state UI, focus flow, blur guards
- [ ] **Component Rendering** — Ensure all {% include %} tags are single-line; pass context variables explicitly
- [ ] **Tests** — Write tests for price validation, selection validation, GL balance, and atomic failures

---

## References

- **Vibe Coding Playbook** — See `.agent/vibe_coding_playbook.md` for 7 common pitfalls
- **Stock Integrity Rule** — Never mutate batch.current_quantity directly; always use StockMovement service
- **Atomic Transaction Rule** — Every multi-step write must be wrapped in transaction.atomic()
- **Hard-Delete vs Cancel** — Delete only for DRAFT; cancel for SUBMITTED
