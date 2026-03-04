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
    'PurchaseReceipt':       ('Stock In Hand', 'Stock Received But Not Billed'),
    'PurchaseReceiptCancel': ('Stock Received But Not Billed', 'Stock In Hand'),
    'DeliveryNote':          ('Cost of Goods Sold', 'Stock In Hand'),
    'DeliveryNoteCancel':    ('Stock In Hand', 'Cost of Goods Sold'),

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


def reverse_document_gl(reference_type: str, reference_id: int) -> None:
    """Post reversing GL entries for a cancelled document.

    Creates a mirror entry (debit/credit swapped) for every original GL row
    on this document.  The originals are **not deleted** — the complete ledger
    history is preserved for audit and regulatory compliance.  The net balance
    for every account touched by this document becomes zero.

    Used when cancelling an invoice to reverse its AR/AP/Tax GL postings.
    The stock-level GL reversal is handled separately by ``post_stock_gl()``.
    """
    originals = list(
        GLEntry.objects.filter(
            reference_type=reference_type,
            reference_id=reference_id,
        ).order_by('pk')  # Deterministic order so reversals mirror originals 1-for-1
    )
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
    """
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

