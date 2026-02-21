# 🚀 AgriCRM vs ERPNext: Gap Analysis & Future Roadmap
**Date:** 21-Feb-2026
**Status:** Post-Sprint 10 (Ledger, Valuation & Multi-Warehouse complete)

---

## 1. Executive Summary: Where We Stand Today
In Sprints 1 through 10, we successfully closed the most critical architectural gaps in AgriCRM's inventory engine compared to ERPNext. 

### What AgriCRM has successfully adopted from ERPNext:
✅ **Stock Ledger Entries (SLE):** Replaced direct/unsafe data mutation with an immutable append-only `StockMovement` ledger.
✅ **Atomic Operations & DB Constraints:** Prevented negative stock using `CheckConstraint` and `select_for_update()`.
✅ **Multi-Warehouse Architecture:** Introduced `Warehouse` and `StockBin` to track stock per location.
✅ **Perpetual Inventory Accounting:** Automated `GLEntry` generation (Debits/Credits) for physical stock movements.
✅ **Moving Average Valuation:** Dynamic recalculation of `Product.moving_average_price` and COGS ledger values.

AgriCRM's foundational inventory layer is now robust and ERP-grade. 

---

## 2. ERPNext Module Benchmark & The Missing Links
If we look at the Frappe/ERPNext ecosystem, business functions are cleanly separated into domain-specific "Apps" or modules. Here is what we need to focus on next, split application-by-application:

### 💼 A. Financial Accounting Module
*ERPNext equivalent: Accounts*
Currently, AgriCRM relies on `balance_due` fields on invoices and a `CustomerPayment`/`SupplierPayment` model, plus a basic wallet.
**Gaps to Research & Implement:**
1. **Accounts Receivable (AR) & Accounts Payable (AP) Ledgers:** Move away from just looking at invoice `balance_due`. Payments should generate GL entries against Debtors (AR) and Creditors (AP) accounts.
2. **Tax Accounting (GST):** Tax amounts currently sit statically on invoices. They should generate GL entries reflecting CGST/SGST Tax Payable and Tax Receivable.
3. **Journal Entries (JV):** Ability to pass manual accounting entries.

### 🛒 B. Buying (Procurement) Module
*ERPNext equivalent: Buying*
Currently, AgriCRM uses a single step: `Create Purchase` immediately inwarding stock and creating financial liability.
**Gaps to Research & Implement:**
1. **Procurement Pipeline:** Purchase Order (PO) ➔ Purchase Receipt (PR) ➔ Purchase Invoice (billing). 
2. **Stock vs Billing Separation:** Allowing stock to arrive before the bill, or billing before stock arrives.

### 🛍️ C. Selling (Fulfillment) Module
*ERPNext equivalent: Selling*
Currently, AgriCRM uses a single step: `Create Sale` which immediately deducts stock and bills the customer.
**Gaps to Research & Implement:**
1. **Fulfillment Pipeline:** Quotation ➔ Sales Order (SO) ➔ Delivery Note (DN) ➔ Sales Invoice.
2. **Delivery Notes:** Deducting stock on dispatch (Delivery Note) vs creating revenue (Sales Invoice).

### 📦 D. Advanced Stock Module
*ERPNext equivalent: Stock*
We have the ledger and bins, but lack advanced workflows.
**Gaps to Research & Implement:**
1. **Inter-Warehouse Material Transfers:** Specific documents to move stock from 'Main Warehouse' to 'Shop Floor' (Debit one Bin, Credit another).
2. **Stock Expiry & Batch Management:** Better workflows for automatically quarantining or restricting sale of expired batches.
3. **Landed Cost Vouchers:** Adding shipping and customs duties to the moving average cost of imported stock.

### 🔒 E. Core Framework (Document Lifecycle)
*ERPNext equivalent: Frappe Framework*
ERPNext documents use an immutable state machine (Draft ➔ Submit ➔ Cancel). AgriCRM still allows destructive "Edits" that delete row items.
**Gaps to Research & Implement:**
1. **Immutable Document State Machine:** Prevent editing submitted sales/purchases. Introduce a native "Cancel and Amend" workflow identical to ERPNext.

---

## 3. Recommended Approach: App-by-App Research Phase
To avoid system instability, we will tackle these gaps module by module. 

We will create detailed research documents for each phase:

**Phase 1: The Core Framework Hardening**
* **Goal:** Adopt the ERPNext "Draft ➔ Submit ➔ Cancel ➔ Amend" document lifecycle. Stop destructive delete operations.

**Phase 2: The Advanced Accounting App**
* **Goal:** AR/AP Ledgers, Tax Ledgers, and Payment/Journal Entries. Tie payments to GL entries exactly like stock movements.

**Phase 3: The Stock Operations App**
* **Goal:** Material Transfers, Delivery Notes, and Purchase Receipts. Separate physical movement from financial billing.

**Phase 4: Procurement & Sales Pipeline**
* **Goal:** Sales Orders, Purchase Orders, and Quotations. Order tracking and fulfillment status.

---
*Ready for Phase 1. Awaiting approval.*
