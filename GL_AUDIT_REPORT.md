# AgriCRM General Ledger — Full Lifecycle Audit Report
**Date**: 2026-03-12
**Auditor**: Claude (automated GL verification)
**Scope**: Purchase Invoice → Purchase Return → Cancel Return → Sales Invoice → Cancel Sales Invoice → Cancel Purchase Invoice
**Product**: Avtar (MAP ₹632.00) | **Supplier**: Indofil Industries Limited | **Customer**: Niranjan Kumar M

---

## 1. Discrepancy Found & Fixed

### Root Cause
A structural bug existed in `PurchaseReturn.cancel()` that left a **dangling Cr ₹3,160 in Stock Received But Not Billed (SRBNB)** after each cancellation cycle.

### Why It Happened
The `PurchaseReturn.submit()` flow uses two passes:
- **Pass 1 (Stock GL)**: `process_stock_movement(PurchaseReturn)` → `Dr SRBNB | Cr Stock In Hand`
- **Pass 2 (Debit Note GL)**: `post_purchase_return_gl()` → `Dr AP | Cr SRBNB | Cr CGST | Cr SGST`

SRBNB acts as a bridge and nets to zero within the return — correct.

The `PurchaseReturn.cancel()` flow was:
- **Cancel Pass 1**: `process_stock_movement(PurchaseReturnCancel)` → `Dr Stock In Hand | Cr SRBNB`
- **Cancel Pass 2**: `reverse_document_gl('PurchaseReturn', id, exclude=['SRBNB', 'Stock In Hand', ...])`

Because SRBNB was excluded from `reverse_document_gl`, the Debit Note's `Cr SRBNB` entry (Pass 2) was never reversed.
Result: **Cr SRBNB ₹3,160 left unreversed** after every purchase return cancellation.

### Fix Applied

**File**: `accounting/services.py` — `post_purchase_return_gl()`
Changed `reference_type='PurchaseReturn'` → `reference_type='PurchaseReturnDebitNote'`

**File**: `transactions/models.py` — `PurchaseReturn.cancel()`
- Removed the `_STOCK_GL_ACCOUNTS` exclusion list
- Changed `reverse_document_gl('PurchaseReturn', self.id, exclude_account_names=_STOCK_GL_ACCOUNTS)`
  → `reverse_document_gl('PurchaseReturnDebitNote', self.id)` (no exclusions)

**File**: `transactions/models.py` — `PurchaseReturn.submit()` comment
Fixed stale comment that said `"Cr Purchase Returns"` when code actually posts `"Cr SRBNB"`.

### Why the Fix Works
- `PurchaseReturnCancel` stock GL (Dr Stock In Hand | Cr SRBNB) now directly pairs with the `PurchaseReturnDebitNote` reversal's Dr SRBNB.
- Net SRBNB across return + cancel = **zero** (verified below).

---

## 2. Full GL Audit — Step by Step

### STEP 1: Purchase Invoice PINV-TEST-001 (20 units × ₹632, GST 18%)

| GL# | Reference Type     | Account                          |      Debit |     Credit |
|-----|--------------------|----------------------------------|-----------:|-----------:|
| 166 | PurchaseReceipt    | Stock In Hand                    | 12,640.00  |       —    |
| 167 | PurchaseReceipt    | Stock Received But Not Billed    |       —    | 12,640.00  |
| 168 | PurchaseInvoice    | Stock Received But Not Billed    | 12,640.00  |       —    |
| 169 | PurchaseInvoice    | CGST Receivable                  |  1,137.60  |       —    |
| 170 | PurchaseInvoice    | SGST Receivable                  |  1,137.60  |       —    |
| 171 | PurchaseInvoice    | Accounts Payable                 |       —    | 14,915.20  |

**Balance check**: PurchaseReceipt ✅ BALANCED (12,640 = 12,640) | PurchaseInvoice ✅ BALANCED (14,915.20 = 14,915.20)
**Open positions (correct)**: Stock In Hand +₹12,640 | AP -₹14,915.20 | CGST/SGST Rcv +₹2,275.20
**SRBNB net**: Dr 12,640 (receipt) − Cr 12,640 (invoice) = **₹0.00** ✅

---

### STEP 2: Purchase Return — 5 units @ ₹632

| GL# | Reference Type             | Account                          |     Debit |    Credit |
|-----|----------------------------|----------------------------------|-----------:|----------:|
| 172 | PurchaseReturn             | Stock Received But Not Billed    |  3,160.00  |      —    |
| 173 | PurchaseReturn             | Stock In Hand                    |      —     | 3,160.00  |
| 174 | PurchaseReturnDebitNote    | Accounts Payable                 |  3,728.80  |      —    |
| 175 | PurchaseReturnDebitNote    | Stock Received But Not Billed    |      —     | 3,160.00  |
| 176 | PurchaseReturnDebitNote    | CGST Receivable                  |      —     |   284.40  |
| 177 | PurchaseReturnDebitNote    | SGST Receivable                  |      —     |   284.40  |

**Balance check**: PurchaseReturn ✅ BALANCED | PurchaseReturnDebitNote ✅ BALANCED
**SRBNB net within return**: Dr 3,160 (stock) − Cr 3,160 (debit note) = **₹0.00** ✅
**Net economic effect**: AP reduced ₹3,728.80 | Stock reduced ₹3,160 | CGST/SGST reduced ₹568.80

---

### STEP 3: Cancel Purchase Return

| GL# | Reference Type             | Account                          |     Debit |    Credit |
|-----|----------------------------|----------------------------------|-----------:|----------:|
| 178 | PurchaseReturnCancel       | Stock In Hand                    |  3,160.00  |      —    |
| 179 | PurchaseReturnCancel       | Stock Received But Not Billed    |      —     | 3,160.00  |
| 180 | PurchaseReturnDebitNote    | Accounts Payable                 |      —     | 3,728.80  |
| 181 | PurchaseReturnDebitNote    | Stock Received But Not Billed    |  3,160.00  |      —    |
| 182 | PurchaseReturnDebitNote    | CGST Receivable                  |    284.40  |      —    |
| 183 | PurchaseReturnDebitNote    | SGST Receivable                  |    284.40  |      —    |

**SRBNB net (Steps 2+3 combined)**:
- Dr 3,160 (stock#172) − Cr 3,160 (debitNote#175) + Dr 3,160 (cancel reversal#181) − Cr 3,160 (cancel stock#179) = **₹0.00** ✅
**Net across Steps 2+3**: ALL ACCOUNTS ZERO ✅ — Return lifecycle fully self-contained.

---

### STEP 4: Sales Invoice (10 units × ₹750, GST 18%)

| GL# | Reference Type   | Account                          |     Debit |    Credit |
|-----|------------------|----------------------------------|-----------:|----------:|
| 184 | DeliveryNote     | Stock Delivered But Not Billed   |  6,320.00  |      —    |
| 185 | DeliveryNote     | Stock In Hand                    |      —     | 6,320.00  |
| 186 | SalesInvoice     | Cost of Goods Sold               |  6,320.00  |      —    |
| 187 | SalesInvoice     | Stock Delivered But Not Billed   |      —     | 6,320.00  |
| 188 | SalesInvoice     | Accounts Receivable              |  8,850.00  |      —    |
| 189 | SalesInvoice     | Sales Revenue                    |      —     | 7,500.00  |
| 190 | SalesInvoice     | CGST Payable                     |      —     |   675.00  |
| 191 | SalesInvoice     | SGST Payable                     |      —     |   675.00  |

**Balance check**: DeliveryNote ✅ BALANCED | SalesInvoice ✅ BALANCED
**SDNB net**: Dr 6,320 (DN) − Cr 6,320 (SDNB clearance) = **₹0.00** ✅
**COGS = 10 × MAP ₹632 = ₹6,320** (correct MAP-based valuation) ✅

---

### STEP 5: Cancel Sales Invoice

| GL# | Reference Type     | Account                          |     Debit |    Credit |
|-----|--------------------|----------------------------------|-----------:|----------:|
| 192 | DeliveryNoteCancel | Stock In Hand                    |  6,320.00  |      —    |
| 193 | DeliveryNoteCancel | Stock Delivered But Not Billed   |      —     | 6,320.00  |
| 194 | SalesInvoice       | Cost of Goods Sold               |      —     | 6,320.00  |
| 195 | SalesInvoice       | Stock Delivered But Not Billed   |  6,320.00  |      —    |
| 196 | SalesInvoice       | Accounts Receivable              |      —     | 8,850.00  |
| 197 | SalesInvoice       | Sales Revenue                    |  7,500.00  |      —    |
| 198 | SalesInvoice       | CGST Payable                     |    675.00  |      —    |
| 199 | SalesInvoice       | SGST Payable                     |    675.00  |      —    |

**Net across Steps 4+5**: ALL ACCOUNTS ZERO ✅ — Sales lifecycle fully self-contained.

---

### STEP 6: Cancel Purchase Invoice

| GL# | Reference Type         | Account                          |      Debit |     Credit |
|-----|------------------------|----------------------------------|-----------:|-----------:|
| 200 | PurchaseReceiptCancel  | Stock Received But Not Billed    | 12,640.00  |       —    |
| 201 | PurchaseReceiptCancel  | Stock In Hand                    |       —    | 12,640.00  |
| 202 | PurchaseInvoice        | Stock Received But Not Billed    |       —    | 12,640.00  |
| 203 | PurchaseInvoice        | CGST Receivable                  |       —    |  1,137.60  |
| 204 | PurchaseInvoice        | SGST Receivable                  |       —    |  1,137.60  |
| 205 | PurchaseInvoice        | Accounts Payable                 | 14,915.20  |       —    |

**SRBNB net (Steps 1+6 combined)**:
Receipt Dr − Receipt Cr + Invoice Dr − Invoice Cr + ReceiptCancel Dr − InvoiceCancel Cr
= Dr 12,640 − Cr 12,640 + Dr 12,640 − Cr 12,640 + Dr 12,640 − Cr 12,640 = **₹0.00** ✅
**Net across Steps 1+6**: ALL ACCOUNTS ZERO ✅ — Purchase lifecycle fully self-contained.

---

## 3. Final Trial Balance (All 6 Steps Combined)

| Account                          | Total Dr       | Total Cr       | Net            | Status |
|----------------------------------|---------------:|---------------:|---------------:|--------|
| Accounts Payable                 |    18,644.00   |    18,644.00   |        0.00    | ✅ ZERO |
| Accounts Receivable              |     8,850.00   |     8,850.00   |        0.00    | ✅ ZERO |
| CGST Payable                     |       675.00   |       675.00   |        0.00    | ✅ ZERO |
| CGST Receivable                  |     1,422.00   |     1,422.00   |        0.00    | ✅ ZERO |
| Cost of Goods Sold               |     6,320.00   |     6,320.00   |        0.00    | ✅ ZERO |
| Sales Revenue                    |     7,500.00   |     7,500.00   |        0.00    | ✅ ZERO |
| SGST Payable                     |       675.00   |       675.00   |        0.00    | ✅ ZERO |
| SGST Receivable                  |     1,422.00   |     1,422.00   |        0.00    | ✅ ZERO |
| Stock Delivered But Not Billed   |    12,640.00   |    12,640.00   |        0.00    | ✅ ZERO |
| Stock In Hand                    |    22,120.00   |    22,120.00   |        0.00    | ✅ ZERO |
| Stock Received But Not Billed    |    31,600.00   |    31,600.00   |        0.00    | ✅ ZERO |

**All 11 accounts net to ₹0.00. No dangling balances. Trial balance is clean.** ✅

---

## 4. Accounting Logic Verification

| # | Assertion | Result |
|---|-----------|--------|
| 1 | COGS uses MAP (₹632), not purchase_price | ✅ Correct — 10 × ₹632 = ₹6,320 |
| 2 | SRBNB nets to zero after full purchase cycle | ✅ Confirmed |
| 3 | SRBNB nets to zero within purchase return + cancel | ✅ Confirmed (bug fixed) |
| 4 | SDNB nets to zero within sales invoice + cancel | ✅ Confirmed |
| 5 | GST input (CGST/SGST Rcv) restored on PINV cancel | ✅ Confirmed |
| 6 | GST output (CGST/SGST Payable) restored on SINV cancel | ✅ Confirmed |
| 7 | AP restored after PINV cancel | ✅ Confirmed |
| 8 | AR restored after SINV cancel | ✅ Confirmed |
| 9 | Stock quantity = 0 after all cancellations | ✅ Confirmed |
| 10 | Every GL posting is individually balanced (Dr=Cr) | ✅ All 40 entries confirmed |

---

## 5. Codes Changed

| File | Change | Reason |
|------|--------|--------|
| `accounting/services.py` | `post_purchase_return_gl()`: `reference_type='PurchaseReturnDebitNote'` | Isolate debit note GL from stock GL for clean cancel reversal |
| `transactions/models.py` | `PurchaseReturn.cancel()`: use `reverse_document_gl('PurchaseReturnDebitNote', ...)` without exclusions | Fix dangling Cr SRBNB bug on cancel |
| `transactions/models.py` | `PurchaseReturn.submit()` comment: updated to reflect `Cr SRBNB` | Remove misleading `Cr Purchase Returns` stale comment |

---

## 6. Note on "Non-Zero Mid-Lifecycle" Balances

The three "FAIL" flags in the automated checker (after Step 1 alone, Step 2 alone, and Step 4 alone) are **expected and correct**. An open purchase invoice leaves AP and Stock In Hand with outstanding balances — these represent real business positions. They only resolve to zero when the document is cancelled, which is the correct accounting behaviour. A zero balance for an open invoice would itself be a bug.
