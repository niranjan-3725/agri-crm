"""
accounting.services
~~~~~~~~~~~~~~~~~~~~

Sprint 9: GL Posting Engine.

Provides ``make_gl_entries()`` — the only sanctioned way to create
GLEntry records.  It enforces strict double-entry balance validation
(total debits == total credits) before committing.

Also provides ``post_stock_gl()`` — the higher-level function called
by ``inventory.services.process_stock_movement()`` to auto-generate
the correct debit/credit pair for a given doc_type and value.
"""

from decimal import Decimal
from .models import Account, GLEntry


class UnbalancedEntryError(Exception):
    """Raised when GL entries do not balance (debits != credits)."""
    pass


def make_gl_entries(
    reference_type: str,
    reference_id: int,
    entries: list[dict],
    remarks: str = '',
) -> list[GLEntry]:
    """Create a balanced set of GL entries.

    Parameters
    ----------
    reference_type : str
        Source document type (e.g. 'PurchaseInvoice').
    reference_id : int
        PK of the source document.
    entries : list[dict]
        Each dict must have: {'account_name': str, 'debit': Decimal, 'credit': Decimal}.
    remarks : str
        Optional description.

    Returns
    -------
    list[GLEntry]
        The created GL entries.

    Raises
    ------
    UnbalancedEntryError
        If total debits != total credits.
    """
    total_debit = sum(e.get('debit', Decimal('0.00')) for e in entries)
    total_credit = sum(e.get('credit', Decimal('0.00')) for e in entries)

    if total_debit != total_credit:
        raise UnbalancedEntryError(
            f"GL entries are unbalanced: "
            f"Total Debit={total_debit}, Total Credit={total_credit}. "
            f"Ref: {reference_type} #{reference_id}"
        )

    created = []
    for entry in entries:
        account = Account.objects.get(name=entry['account_name'])
        gl = GLEntry.objects.create(
            account=account,
            debit=entry.get('debit', Decimal('0.00')),
            credit=entry.get('credit', Decimal('0.00')),
            reference_type=reference_type,
            reference_id=reference_id,
            remarks=remarks,
        )
        created.append(gl)

    return created


# ── GL Routing Map ──
# Maps each StockMovement doc_type to (debit_account_name, credit_account_name).
# StockReconciliation is handled dynamically based on the sign of the quantity.

GL_ROUTING = {
    # Sprint 13: Fulfillment documents handle stock GL
    'PurchaseReceipt':       ('Stock In Hand',                  'Stock Received But Not Billed'),
    'PurchaseReceiptCancel': ('Stock Received But Not Billed',  'Stock In Hand'),
    # DeliveryNote parks in SDNB (temp asset); COGS is only recognised when
    # SalesInvoice.submit() calls post_sdnb_clearance_gl() to clear it.
    'DeliveryNote':          ('Stock Delivered But Not Billed', 'Stock In Hand'),
    'DeliveryNoteCancel':    ('Stock In Hand',                  'Stock Delivered But Not Billed'),

    # Legacy: kept for backward compatibility with existing StockMovement records
    'PurchaseInvoice':       ('Stock In Hand', 'Stock Received But Not Billed'),
    'PurchaseInvoiceCancel': ('Stock Received But Not Billed', 'Stock In Hand'),
    'SalesInvoice':          ('Cost of Goods Sold', 'Stock In Hand'),

    # Sales Returns (stock IN — reverses COGS)
    'SalesReturn':           ('Stock In Hand', 'Cost of Goods Sold'),
    'SalesReturnCancel':     ('Cost of Goods Sold', 'Stock In Hand'),

    # Purchase Returns (stock OUT — reverses purchase)
    'PurchaseReturn':        ('Stock Received But Not Billed', 'Stock In Hand'),
    'PurchaseReturnCancel':  ('Stock In Hand', 'Stock Received But Not Billed'),
}


def post_stock_gl(
    doc_type: str,
    doc_id: int,
    quantity: int,
    purchase_price: Decimal,
) -> list[GLEntry]:
    """Generate balanced GL entries for a stock movement.

    Called inside the atomic block of ``process_stock_movement()``.

    Parameters
    ----------
    doc_type : str
        The reference_document_type from the StockMovement.
    doc_id : int
        The reference_document_id.
    quantity : int
        The signed quantity (+inward, -outward).
    purchase_price : Decimal
        The batch's purchase_price (cost basis).

    Returns
    -------
    list[GLEntry]
        The two created GL entries (debit + credit).
    """
    value = abs(quantity) * purchase_price

    if value == 0:
        return []

    if doc_type == 'StockReconciliation':
        # Dynamic routing based on sign
        if quantity > 0:
            debit_acct = 'Stock In Hand'
            credit_acct = 'Inventory Adjustment'
        else:
            debit_acct = 'Inventory Adjustment'
            credit_acct = 'Stock In Hand'
    elif doc_type in GL_ROUTING:
        debit_acct, credit_acct = GL_ROUTING[doc_type]
    else:
        # Unknown doc_type — default to generic adjustment
        if quantity > 0:
            debit_acct = 'Stock In Hand'
            credit_acct = 'Inventory Adjustment'
        else:
            debit_acct = 'Inventory Adjustment'
            credit_acct = 'Stock In Hand'

    entries = [
        {'account_name': debit_acct, 'debit': value, 'credit': Decimal('0.00')},
        {'account_name': credit_acct, 'debit': Decimal('0.00'), 'credit': value},
    ]

    return make_gl_entries(
        reference_type=doc_type,
        reference_id=doc_id,
        entries=entries,
        remarks=f"{doc_type} #{doc_id}: {quantity} units @ {purchase_price}",
    )


# ── Sprint 12: AR/AP/Revenue/Tax GL Functions ──────────────────────────


def post_sales_invoice_gl(invoice) -> list[GLEntry]:
    """Post AR / Revenue / Tax GL entries when a Sales Invoice is submitted.

    Dr  Accounts Receivable   grand_total
    Cr  Sales Revenue          total_taxable
    Cr  CGST Payable           total_cgst
    Cr  SGST Payable           total_sgst

    Ensures: grand_total == total_taxable + total_cgst + total_sgst.
    """
    grand_total = Decimal(str(invoice.grand_total))
    total_taxable = Decimal(str(invoice.total_taxable))
    total_cgst = Decimal(str(invoice.total_cgst))
    total_sgst = Decimal(str(invoice.total_sgst))

    # Guard: ensure perfect balance
    tax_plus_revenue = total_taxable + total_cgst + total_sgst
    if grand_total != tax_plus_revenue:
        # Fix rounding by adjusting revenue (the largest component)
        total_taxable = grand_total - total_cgst - total_sgst

    if grand_total == 0:
        return []

    entries = [
        {'account_name': 'Accounts Receivable', 'debit': grand_total, 'credit': Decimal('0.00')},
        {'account_name': 'Sales Revenue', 'debit': Decimal('0.00'), 'credit': total_taxable},
        {'account_name': 'CGST Payable', 'debit': Decimal('0.00'), 'credit': total_cgst},
        {'account_name': 'SGST Payable', 'debit': Decimal('0.00'), 'credit': total_sgst},
    ]

    # Remove zero-value tax lines (e.g. zero-rated goods)
    entries = [e for e in entries if e['debit'] != 0 or e['credit'] != 0]

    return make_gl_entries(
        reference_type='SalesInvoice',
        reference_id=invoice.id,
        entries=entries,
        remarks=f"Sales Invoice #{invoice.invoice_number}: AR {grand_total}",
    )


def post_sdnb_clearance_gl(delivery_note, sales_invoice_id: int) -> list[GLEntry]:
    """Clear the SDNB account when a DeliveryNote is billed via a SalesInvoice.

    Called inside SalesInvoice.submit() *after* the DeliveryNote has been
    submitted.  The COGS value is derived from the StockMovement valuation
    snapshots so it matches exactly what was posted to SDNB at delivery time.

    Dr  Cost of Goods Sold                cogs_value
    Cr  Stock Delivered But Not Billed    cogs_value

    Both legs are tagged to the SalesInvoice so reverse_document_gl() picks
    them up automatically on cancel.
    """
    from inventory.models import StockMovement

    movements = StockMovement.objects.filter(
        reference_document_type='DeliveryNote',
        reference_document_id=delivery_note.id,
    )

    cogs_value = sum(
        abs(m.quantity) * m.valuation_rate
        for m in movements
    )
    cogs_value = Decimal(str(cogs_value)).quantize(Decimal('0.01'))

    if cogs_value == 0:
        return []

    return make_gl_entries(
        reference_type='SalesInvoice',
        reference_id=sales_invoice_id,
        entries=[
            {'account_name': 'Cost of Goods Sold',               'debit': cogs_value,       'credit': Decimal('0.00')},
            {'account_name': 'Stock Delivered But Not Billed',   'debit': Decimal('0.00'),  'credit': cogs_value},
        ],
        remarks=f"SDNB clearance: DN#{delivery_note.id} → SI#{sales_invoice_id}",
    )


def reverse_document_gl(
    reference_type: str,
    reference_id: int,
    exclude_account_names: list[str] | None = None,
) -> None:
    """Post reversing GL entries for a cancelled document.

    Creates a mirror entry (debit/credit swapped) for every original GL row
    on this document.  The originals are **not deleted** — the complete ledger
    history is preserved for audit and regulatory compliance.  The net balance
    for every account touched by this document becomes zero.

    Used when cancelling an invoice to reverse its AR/AP/Tax GL postings.
    The stock-level GL reversal is handled separately by ``post_stock_gl()``.

    Parameters
    ----------
    exclude_account_names : list[str] | None
        Account names to skip when building reversal entries.  Use this when
        the cancel path already reverses certain accounts via
        ``process_stock_movement()`` (e.g. 'Stock In Hand') to prevent
        double-posting.  See Playbook Rule 14.
    """
    originals = list(
        GLEntry.objects.filter(
            reference_type=reference_type,
            reference_id=reference_id,
        ).select_related('account').order_by('pk')  # select_related avoids N+1 on account.name
    )
    if not originals:
        return

    if exclude_account_names:
        originals = [e for e in originals if e.account.name not in exclude_account_names]
        if not originals:
            return

    reversing = [
        GLEntry(
            account=entry.account,
            debit=entry.credit,   # Swap: original credit becomes the reversing debit
            credit=entry.debit,   # Swap: original debit  becomes the reversing credit
            reference_type=reference_type,
            reference_id=reference_id,
            remarks=f"Reversal of GL entry #{entry.pk}",
        )
        for entry in originals
    ]
    GLEntry.objects.bulk_create(reversing)


def post_purchase_invoice_gl(invoice) -> list[GLEntry]:
    """Post AP / Inventory / Tax GL entries when a Purchase Invoice is submitted.

    Dr  Stock Received But Not Billed   base_amount
    Dr  CGST Receivable                 total_cgst
    Dr  SGST Receivable                 total_sgst
    Cr  Accounts Payable                total_amount

    base_amount = total_amount - total_tax.
    total_tax is split 50/50 between CGST and SGST (Indian GST).
    """
    total_amount = Decimal(str(invoice.total_amount))

    if total_amount == 0:
        return []

    # Compute total tax from items
    total_tax = Decimal('0.00')
    for item in invoice.items.all():
        total_tax += Decimal(str(item.tax_amount))

    # Split tax 50/50 for CGST/SGST
    total_cgst = (total_tax / 2).quantize(Decimal('0.01'))
    total_sgst = total_tax - total_cgst  # Prevents rounding loss

    base_amount = total_amount - total_tax

    entries = [
        {'account_name': 'Stock Received But Not Billed', 'debit': base_amount, 'credit': Decimal('0.00')},
        {'account_name': 'CGST Receivable', 'debit': total_cgst, 'credit': Decimal('0.00')},
        {'account_name': 'SGST Receivable', 'debit': total_sgst, 'credit': Decimal('0.00')},
        {'account_name': 'Accounts Payable', 'debit': Decimal('0.00'), 'credit': total_amount},
    ]

    # Remove zero-value lines
    entries = [e for e in entries if e['debit'] != 0 or e['credit'] != 0]

    return make_gl_entries(
        reference_type='PurchaseInvoice',
        reference_id=invoice.id,
        entries=entries,
        remarks=f"Purchase Invoice #{invoice.invoice_number}: AP {total_amount}",
    )


def post_customer_payment_gl(payment) -> list[GLEntry]:
    """Post Cash ↔ AR GL entries when a Customer Payment is recorded.

    Normal payment (amount > 0):
        Dr  Cash / Bank           amount
        Cr  Accounts Receivable   amount

    Reversal (amount < 0):
        Dr  Accounts Receivable   |amount|
        Cr  Cash / Bank           |amount|
    """
    amount = Decimal(str(payment.amount))
    if amount == 0:
        return []

    abs_amount = abs(amount)

    if amount > 0:
        entries = [
            {'account_name': 'Cash / Bank', 'debit': abs_amount, 'credit': Decimal('0.00')},
            {'account_name': 'Accounts Receivable', 'debit': Decimal('0.00'), 'credit': abs_amount},
        ]
    else:
        entries = [
            {'account_name': 'Accounts Receivable', 'debit': abs_amount, 'credit': Decimal('0.00')},
            {'account_name': 'Cash / Bank', 'debit': Decimal('0.00'), 'credit': abs_amount},
        ]

    return make_gl_entries(
        reference_type='CustomerPayment',
        reference_id=payment.id,
        entries=entries,
        remarks=f"Customer Payment #{payment.id}: {payment.payment_mode} {amount}",
    )


def post_supplier_payment_gl(payment) -> list[GLEntry]:
    """Post AP ↔ Cash GL entries when a Supplier Payment is recorded.

    Normal payment (amount > 0):
        Dr  Accounts Payable      amount
        Cr  Cash / Bank           amount

    Reversal / Debit Note (amount < 0):
        Dr  Cash / Bank           |amount|
        Cr  Accounts Payable      |amount|

    Note: DEBIT_NOTE mode payments are intentionally skipped here.
    Their full GL (Dr AP | Cr Purchase Returns | Cr GST Input Recoverable)
    is posted by ``post_purchase_return_gl()`` inside PurchaseReturn.submit().
    """
    # DEBIT_NOTE settlements are handled by post_purchase_return_gl() — skip.
    if payment.payment_mode == 'DEBIT_NOTE':
        return []

    amount = Decimal(str(payment.amount))
    if amount == 0:
        return []

    abs_amount = abs(amount)

    if amount > 0:
        entries = [
            {'account_name': 'Accounts Payable', 'debit': abs_amount, 'credit': Decimal('0.00')},
            {'account_name': 'Cash / Bank', 'debit': Decimal('0.00'), 'credit': abs_amount},
        ]
    else:
        entries = [
            {'account_name': 'Cash / Bank', 'debit': abs_amount, 'credit': Decimal('0.00')},
            {'account_name': 'Accounts Payable', 'debit': Decimal('0.00'), 'credit': abs_amount},
        ]

    return make_gl_entries(
        reference_type='SupplierPayment',
        reference_id=payment.id,
        entries=entries,
        remarks=f"Supplier Payment #{payment.id}: {payment.payment_mode} {amount}",
    )


# ── Returns Module: Credit Note & Debit Note GL ────────────────────────


def post_sales_return_gl(sales_return) -> list[GLEntry]:
    """Post the full Credit Note GL when a Sales Return is submitted.

    Reverses the income-statement and AR impact of the original sale for
    the specific items being returned:

        Dr  Sales Returns (contra-revenue)   total_net
        Dr  CGST Payable                     total_cgst   (tax liability reduced)
        Dr  SGST Payable                     total_sgst
        Cr  Accounts Receivable              total_gross  (AR balance reduced)

    Tax rates are sourced from the original SalesItem on the linked invoice.
    If the return is freeform (no original_sale), tax reversal is skipped
    and only the net amount is posted against AR.

    The inventory-side GL (Dr Stock In Hand | Cr COGS) is handled
    separately by post_stock_gl() called from process_stock_movement().
    """
    from transactions.models import SalesItem

    total_net = Decimal('0.00')
    total_cgst = Decimal('0.00')
    total_sgst = Decimal('0.00')

    for return_item in sales_return.items.select_related('batch').all():
        # Determine per-unit net price and tax rate for this item.
        per_unit_net = Decimal('0.00')
        tax_rate = Decimal('0.00')

        if sales_return.original_sale_id:
            invoice_item = (
                SalesItem.objects
                .filter(
                    invoice_id=sales_return.original_sale_id,
                    batch=return_item.batch,
                )
                .first()
            )
            if invoice_item:
                per_unit_net = Decimal(str(invoice_item.unit_price))
                tax_rate = Decimal(str(invoice_item.tax_rate))

        # Fall back to stored unit_price_at_invoice if available.
        if per_unit_net == Decimal('0.00') and return_item.unit_price_at_invoice:
            per_unit_net = Decimal(str(return_item.unit_price_at_invoice))

        qty = Decimal(str(return_item.quantity))
        item_net = per_unit_net * qty
        item_tax = (item_net * tax_rate / 100).quantize(Decimal('0.01'))
        item_cgst = (item_tax / 2).quantize(Decimal('0.01'))
        item_sgst = item_tax - item_cgst

        total_net += item_net
        total_cgst += item_cgst
        total_sgst += item_sgst

    total_gross = total_net + total_cgst + total_sgst

    if total_gross == Decimal('0.00'):
        return []

    entries = [
        {'account_name': 'Sales Returns',      'debit': total_net,   'credit': Decimal('0.00')},
        {'account_name': 'CGST Payable',        'debit': total_cgst,  'credit': Decimal('0.00')},
        {'account_name': 'SGST Payable',        'debit': total_sgst,  'credit': Decimal('0.00')},
        {'account_name': 'Accounts Receivable', 'debit': Decimal('0.00'), 'credit': total_gross},
    ]
    # Remove zero-value tax lines (e.g. zero-rated goods or freeform returns)
    entries = [e for e in entries if e['debit'] != 0 or e['credit'] != 0]

    inv_ref = (
        f"Inv #{sales_return.original_sale.invoice_number}"
        if sales_return.original_sale_id
        else "Freeform"
    )
    return make_gl_entries(
        reference_type='SalesReturn',
        reference_id=sales_return.id,
        entries=entries,
        remarks=f"Credit Note — SalesReturn #{sales_return.id} ({inv_ref})",
    )


def post_purchase_return_gl(purchase_return) -> list[GLEntry]:
    """Post the full Debit Note GL when a Purchase Return is submitted.

    Reverses the AP and purchase-expense impact of the original purchase
    for the specific items being returned to the supplier:

        Dr  Accounts Payable              total_gross  (AP balance reduced)
        Cr  Purchase Returns (contra-exp) total_net
        Cr  CGST Input Recoverable        total_cgst   (input tax reclaimed)
        Cr  SGST Input Recoverable        total_sgst

    Tax rates are derived from the original PurchaseItem on the linked
    invoice (tax_amount / (basic_rate * quantity) × 100).  If the return
    is freeform (no original_invoice), tax recovery is skipped.

    The inventory-side GL (Dr SRNB | Cr Stock In Hand) is handled
    separately by post_stock_gl() called from process_stock_movement().
    """
    from transactions.models import PurchaseItem

    total_net = Decimal('0.00')
    total_cgst = Decimal('0.00')
    total_sgst = Decimal('0.00')

    for return_item in purchase_return.items.select_related('batch').all():
        per_unit_net = Decimal(str(return_item.refund_price))
        tax_rate = Decimal('0.00')

        if purchase_return.original_invoice_id:
            invoice_item = (
                PurchaseItem.objects
                .filter(
                    invoice_id=purchase_return.original_invoice_id,
                    batch=return_item.batch,
                )
                .first()
            )
            if invoice_item and invoice_item.basic_rate and invoice_item.quantity:
                invoice_base = Decimal(str(invoice_item.basic_rate)) * invoice_item.quantity
                if invoice_base > 0:
                    tax_rate = (
                        Decimal(str(invoice_item.tax_amount)) / invoice_base * 100
                    ).quantize(Decimal('0.01'))

        qty = Decimal(str(return_item.quantity))
        item_net = per_unit_net * qty
        item_tax = (item_net * tax_rate / 100).quantize(Decimal('0.01'))
        item_cgst = (item_tax / 2).quantize(Decimal('0.01'))
        item_sgst = item_tax - item_cgst

        total_net += item_net
        total_cgst += item_cgst
        total_sgst += item_sgst

    total_gross = total_net + total_cgst + total_sgst

    if total_gross == Decimal('0.00'):
        return []

    entries = [
        {'account_name': 'Accounts Payable',                'debit': total_gross, 'credit': Decimal('0.00')},
        {'account_name': 'Stock Received But Not Billed',   'debit': Decimal('0.00'), 'credit': total_net},
        {'account_name': 'CGST Receivable',                 'debit': Decimal('0.00'), 'credit': total_cgst},
        {'account_name': 'SGST Receivable',                 'debit': Decimal('0.00'), 'credit': total_sgst},
    ]
    entries = [e for e in entries if e['debit'] != 0 or e['credit'] != 0]

    inv_ref = (
        f"Inv #{purchase_return.original_invoice.invoice_number}"
        if purchase_return.original_invoice_id
        else "Freeform"
    )
    # Tag as 'PurchaseReturnDebitNote' (not 'PurchaseReturn') so that
    # PurchaseReturn.cancel() can independently reverse only the financial
    # (AP/Tax) entries via reverse_document_gl('PurchaseReturnDebitNote', ...)
    # without conflicting with the stock-GL reversal that runs via
    # process_stock_movement(doc_type='PurchaseReturnCancel').
    # This prevents the SRBNB double-credit bug on cancel (see Playbook Rule 15).
    return make_gl_entries(
        reference_type='PurchaseReturnDebitNote',
        reference_id=purchase_return.id,
        entries=entries,
        remarks=f"Debit Note — PurchaseReturn #{purchase_return.id} ({inv_ref})",
    )

