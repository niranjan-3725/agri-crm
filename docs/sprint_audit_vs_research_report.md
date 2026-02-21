# 🔍 Sprint 1–4 Audit vs. Inventory Flow Research Report
## Cross-Reference: What Was Fixed, What Remains

**Date:** 21-Feb-2026  
**Reference Document:** `docs/inventory_flow_report.md` (dated 20-Feb-2026)  
**Sprints Completed:** Sprint 1, Sprint 2, Sprint 2.5, Sprint 3, Sprint 4

---

## ✅ RESOLVED — Issues Fully Addressed

### 🟢 Bug #1: Sales Do NOT Deduct Stock (CRITICAL) — **FIXED in Sprint 2**

| Report Section | Status |
|----------------|--------|
| §2.3 — `create_sale()` doesn't deduct stock | ✅ **FIXED** |
| §5 — Bug #1 detailed analysis | ✅ **FIXED** |
| §6 — Priority 1: Fix Stock Deduction | ✅ **FIXED** |
| §4 — Sales Flow: "❌ MISSING" stock deduction | ✅ **FIXED** |
| Line 639 — `create_sale()` marked ❌ MISSING | ✅ **FIXED** |
| Line 643 — `edit_sale (redo)` marked ❌ MISSING | ✅ **FIXED** (Sprint 4 uses new invoice via amend) |

**How:** Sprint 2 introduced `process_stock_movement()` calls in `create_sale()`. Each sold item now calls:
```python
process_stock_movement(batch_id=batch.id, quantity=-qty, doc_type='SalesInvoice', doc_id=invoice.id)
```
Verified by `OutwardFlowLedgerTests.test_sale_deduction_bug_1_fix` ✅

---

### 🟢 Bug #2: Purchase Delete Can Create Negative Stock — **FIXED in Sprint 1**

| Report Section | Status |
|----------------|--------|
| §5 — Bug #2: Purchase Delete creates negative stock | ✅ **FIXED** |
| §6 — Priority 3: Negative Stock Prevention | ✅ **FIXED** |
| Line 644 — `purchase_delete()` marked ⚠️ No negative check | ✅ **FIXED** |

**How:** Sprint 1 added the DB-level `CheckConstraint`:
```python
models.CheckConstraint(
    check=models.Q(current_quantity__gte=0),
    name='batch_non_negative_stock'
)
```
And `process_stock_movement()` validates before deducting. Verified by `StockServiceTests.test_over_deduct_raises_insufficient` ✅

---

### 🟢 Bug #3: Race Condition on Stock Updates — **FIXED in Sprint 1**

| Report Section | Status |
|----------------|--------|
| §5 — Bug #3: Race Condition | ✅ **FIXED** |
| §6 — Priority 4: Atomic Stock Updates | ✅ **FIXED** |

**How:** Sprint 1 created `inventory/services.py` with `process_stock_movement()` that uses:
```python
Batch.objects.filter(pk=batch_id).update(
    current_quantity=F('current_quantity') + quantity
)
```
All views now go through this service — no more `batch.current_quantity += qty; batch.save()`.
Verified by `StockServiceTests.test_f_expression_atomic_update` ✅

---

### 🟢 No Audit Trail — **FIXED in Sprint 1**

| Report Section | Status |
|----------------|--------|
| §1 — Audit Trail: ❌ None | ✅ **FIXED** |
| §4 — History: Lost — overwritten each time | ✅ **FIXED** |
| §4 — Can Reconstruct: ❌ No | ✅ **FIXED** |
| §6 — Priority 2: Stock Movement Ledger | ✅ **FIXED** |

**How:** Sprint 1 created the `StockMovement` model (`inventory/models.py`):
```python
class StockMovement(models.Model):
    batch = FK(Batch)
    quantity = IntegerField  # +ve inward, -ve outward
    reference_document_type = CharField  # 'PurchaseInvoice', 'SalesInvoice', etc.
    reference_document_id = IntegerField
    balance_after_movement = IntegerField
    created_at = DateTimeField(auto_now_add=True)
```
Every stock change now creates an immutable `StockMovement` row. Full history is available.

---

### 🟢 Document Lifecycle: No states — **FIXED in Sprint 3**

| Report Section | Status |
|----------------|--------|
| §1 — Document Lifecycle: No draft/submit/cancel states | ✅ **FIXED** |
| §4 — Audit Trail: ❌ Nothing remains after delete | ✅ **FIXED** |

**How:** Sprint 3 added `status` field (`ACTIVE`/`CANCELLED`) to both `SalesInvoice` and `PurchaseInvoice`. The `.delete()` method is overridden to raise `ValidationError` — invoices can only be soft-cancelled via `.cancel()`. Cancelled invoices persist in the database with full audit trail.

---

### 🟢 Edit: Destructive "Delete-and-Recreate" — **FIXED in Sprint 4**

| Report Section | Status |
|----------------|--------|
| §2.6 — Edit: "Delete-and-Recreate" pattern | ✅ **FIXED** |
| §4 — Edit: "destroys old items" | ✅ **FIXED** |
| §4 — ERPNext comparison: "Cancel + Amend creates new linked doc" | ✅ **ADOPTED** |

**How:** Sprint 4 replaced both `edit_sale` and `purchase_edit` with the ERPNext-style Amend lifecycle:
1. `original_invoice.cancel()` — reverses stock via ledger, marks CANCELLED
2. Rename original's `invoice_number` to `{number}-C`
3. Create NEW invoice with `amended_from=original_invoice`
4. Save new items + ledger entries to the new invoice

The `amended_from` FK provides a full amendment chain.

---

### 🟢 Delete Operations: Hard Delete — **FIXED in Sprint 3**

| Report Section | Status |
|----------------|--------|
| §2.7 — Delete: `invoice.delete()` hard-deletes records | ✅ **FIXED** |
| Line 644-645 — Delete operations with various issues | ✅ **FIXED** |

**How:** Sprint 3 replaced hard-delete views with soft-cancellation:
- `delete_invoice` → calls `invoice.cancel()` (stock reversed, wallet refunded, status=CANCELLED)
- `purchase_delete` → calls `invoice.cancel()` (stock reversed, status=CANCELLED)
- All list views and aggregate queries filter by `status='ACTIVE'`

---

## ⚠️ REMAINING — Issues Not Yet Addressed

The following items from the report have **NOT** been addressed in Sprints 1–4. These are candidates for future sprints.

---

### 🔴 Remaining Issue #1: Returns Still Use Direct Mutation (No Ledger)

| Report Section | Current State | Risk |
|----------------|--------------|------|
| §2.4 — `create_sales_return()` uses `batch.qty += qty` | ⚠️ Still using direct mutation | Medium |
| §2.5 — `create_purchase_return()` uses `batch.qty -= qty` | ⚠️ Still using direct mutation | Medium |
| §2.4 — `delete_sales_return()` uses `batch.qty -= qty` | ⚠️ Still using direct mutation | Medium |
| §2.5 — `delete_purchase_return()` uses `batch.qty += qty` | ⚠️ Still using direct mutation | Medium |

**The Problem:** While Purchases and Sales now use the `process_stock_movement()` ledger service, the **Returns** flows still do raw `batch.current_quantity += qty` / `batch.save()`. This means:
- Returns do NOT create `StockMovement` ledger entries (no audit trail for returned stock)
- Returns bypass the `F()` expression atomic update (race condition risk)
- Returns bypass the negative stock constraint check in the service

**Recommended Sprint:**
> **Sprint 5: Migrate Returns to Ledger Service**
> - Update `create_sales_return()` to use `process_stock_movement(qty=+qty, doc_type='SalesReturn')`
> - Update `create_purchase_return()` to use `process_stock_movement(qty=-qty, doc_type='PurchaseReturn')`
> - Update `delete_sales_return()` to use `process_stock_movement(qty=-qty, doc_type='SalesReturnCancel')`
> - Update `delete_purchase_return()` to use `process_stock_movement(qty=+qty, doc_type='PurchaseReturnCancel')`
> - Write tests to verify

---

### 🔴 Remaining Issue #2: Returns Still Use Hard Deletes

| Report Section | Current State | Risk |
|----------------|--------------|------|
| §2.4 — `delete_sales_return()` hard-deletes the return record | ⚠️ Data loss | Medium |
| §2.5 — `delete_purchase_return()` hard-deletes the return record | ⚠️ Data loss | Medium |

**The Problem:** While Invoices are now immutable (Sprint 3), the `SalesReturn` and `PurchaseReturn` models still allow hard deletion. Deleting a return destroys the audit trail.

**Recommended Sprint:**
> **Sprint 6: Immutable Returns**
> - Add `status` field to `SalesReturn` and `PurchaseReturn`
> - Override `.delete()` to raise `ValidationError`
> - Add `.cancel()` method that reverses ledger entries and marks CANCELLED
> - Update `delete_sales_return` and `delete_purchase_return` views

---

### 🟡 Remaining Issue #3: No Warehouse Support

| Report Section | Current State | Risk |
|----------------|--------------|------|
| §1 — Warehouse Support: ❌ Single implicit warehouse | ⚠️ N/A for now | Low |
| §3 — ERPNext multi-warehouse architecture | Not relevant yet | Low |

**The Problem:** AgriCRM assumes a single implicit warehouse. The `StockMovement` model doesn't record warehouse location. This is fine for a single-location business but limits scalability.

**Recommended Sprint (Future):**
> **Sprint N: Multi-Warehouse Support**
> - Add `Warehouse` model
> - Add `warehouse` FK to `Batch` and `StockMovement`
> - Update views to select warehouse on purchase/sale

**Priority:** Low — only if the business expands to multiple locations.

---

### 🟡 Remaining Issue #4: No GL/Accounting Integration

| Report Section | Current State | Risk |
|----------------|--------------|------|
| §1 — GL Integration: ❌ No accounting entries | ⚠️ Not implemented | Low |
| §3.3 — ERPNext creates GL entries on submit | Not relevant yet | Low |

**The Problem:** ERPNext creates General Ledger entries for every stock movement (perpetual inventory accounting). AgriCRM has no GL — financial tracking is done via payment records only.

**Recommended Sprint (Future):**
> **Sprint N+1: General Ledger Entries**
> - Create `GLEntry` model
> - Create entries on stock movements (Debit Stock Asset / Credit Payable, etc.)

**Priority:** Low — only if the business needs formal accounting integration.

---

### 🟡 Remaining Issue #5: No Stock Valuation Method

| Report Section | Current State | Risk |
|----------------|--------------|------|
| §1 — Valuation Method: Flat purchase_price | ⚠️ Simplified | Low |
| §3.7 — ERPNext supports FIFO/Moving Average/LIFO | Not implemented | Low |

**The Problem:** AgriCRM uses a flat `purchase_price` per batch. ERPNext computes valuation dynamically using FIFO or Moving Average. This affects COGS accuracy when the same item is purchased at different prices.

**Priority:** Low — the batch-level `purchase_price` is sufficient for most agricultural businesses.

---

### 🟡 Remaining Issue #6: No Stock Reconciliation Tool

| Report Section | Current State | Risk |
|----------------|--------------|------|
| §3.6 — ERPNext Stock Reconciliation | Not implemented | Medium |

**The Problem:** There's no way to adjust stock levels after a physical count (damaged goods, theft, counting errors). Currently, the only way to fix a mismatch is to create a fake purchase/return.

**Recommended Sprint (Future):**
> **Sprint N+2: Stock Reconciliation**
> - Create a `StockAdjustment` view that calls `process_stock_movement(doc_type='StockAdjustment')`
> - Allow admin to set stock to a target value with a reason/note

---

### 🟡 Remaining Issue #7: Batch Identity Uniqueness

| Report Section | Current State | Risk |
|----------------|--------------|------|
| §2.2 — "get_or_create uses (product, batch_number, mrp)" | ⚠️ Potentially fragile | Low |

**The Problem:** The report noted that `get_or_create` uses `(product, batch_number)` as the unique key (MRP was removed from the unique constraint in a later sprint). If a batch is re-purchased at a different MRP, it updates the existing batch instead of creating a new one.

**Priority:** Low — this is by design for the current use case.

---

### 🟠 Remaining Issue #8: Pre-Existing Test Failure

| Test | Current State | Risk |
|------|--------------|------|
| `PurchaseCreateViewTest.test_valid_submission` | ⚠️ Assertion mismatch | None (test-only) |

**The Problem:** Test sends `loading_charges=10` but asserts `50`. This is a test data mismatch and does NOT indicate a bug in the application code.

**See:** `Pre_Existing_Error_Report.md` for detailed fix options.

---

## 📊 Summary Scorecard

| Research Report Item | Section | Sprint | Status |
|---------------------|---------|--------|--------|
| Bug #1: Sales don't deduct stock | §5 | Sprint 2 | ✅ FIXED |
| Bug #2: Purchase delete → negative stock | §5 | Sprint 1 | ✅ FIXED |
| Bug #3: Race condition on stock updates | §5 | Sprint 1 | ✅ FIXED |
| Priority 1: Fix stock deduction | §6 | Sprint 2 | ✅ FIXED |
| Priority 2: Stock Movement Ledger | §6 | Sprint 1 | ✅ FIXED |
| Priority 3: Negative stock prevention | §6 | Sprint 1 | ✅ FIXED |
| Priority 4: Atomic stock updates (F()) | §6 | Sprint 1 | ✅ FIXED |
| No audit trail | §1, §4 | Sprint 1 | ✅ FIXED |
| No document lifecycle states | §1, §4 | Sprint 3 | ✅ FIXED |
| Hard-delete invoices | §2.7, §4 | Sprint 3 | ✅ FIXED |
| Destructive Edit pattern | §2.6, §4 | Sprint 4 | ✅ FIXED |
| Returns use direct mutation (no ledger) | §2.4, §2.5 | — | 🔴 **OPEN** |
| Returns use hard deletes | §2.4, §2.5 | — | 🔴 **OPEN** |
| No warehouse support | §1 | — | 🟡 Future |
| No GL integration | §1 | — | 🟡 Future |
| No stock valuation method | §1 | — | 🟡 Future |
| No stock reconciliation | §3.6 | — | 🟡 Future |

### Bottom Line

**11 of 17 items have been fully resolved.** The two highest-priority remaining items are:
1. **Returns not using the ledger service** (Sprint 5 candidate)
2. **Returns still allow hard deletes** (Sprint 6 candidate)

The remaining 4 items are future architectural enhancements (warehouse, GL, valuation, reconciliation) that are low priority for the current business scale.

---

*Generated by Sprint 1–4 audit against `docs/inventory_flow_report.md`*
