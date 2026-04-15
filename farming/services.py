"""
Farming services — pure functions, no side effects, no HTTP context.
"""
import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from django.utils import timezone

from inventory.models import Batch
from .models import CultivationRecord, CropProductNorm


# ── Document number generators ────────────────────────────────────────────────

def generate_visit_number() -> str:
    """Thread-safe sequential visit number: FV-YYYYMMDD-NNNN."""
    from .models import FieldVisit
    today_str = timezone.now().strftime('%Y%m%d')
    prefix = f'FV-{today_str}-'
    last = (
        FieldVisit.objects
        .filter(visit_number__startswith=prefix)
        .order_by('-visit_number')
        .first()
    )
    seq = (int(last.visit_number.split('-')[-1]) + 1) if last else 1
    return f'{prefix}{seq:04d}'


def generate_consultation_number() -> str:
    """Thread-safe sequential consultation number: FC-YYYYMMDD-NNNN."""
    from .models import FieldConsultation
    today_str = timezone.now().strftime('%Y%m%d')
    prefix = f'FC-{today_str}-'
    last = (
        FieldConsultation.objects
        .filter(consultation_number__startswith=prefix)
        .order_by('-consultation_number')
        .first()
    )
    seq = (int(last.consultation_number.split('-')[-1]) + 1) if last else 1
    return f'{prefix}{seq:04d}'


def norm_suggest(crop_id, product_id, severity: str = '') -> dict | None:
    """
    Return the adjusted dosage rate for a (crop, product) pair.

    severity_adjustments is a JSON dict on CropProductNorm e.g.
    {"LOW": 0.8, "MEDIUM": 1.0, "HIGH": 1.3, "CRITICAL": 1.6}.
    If severity is absent or not in the dict, the base rate is returned.
    Returns None when no norm exists.
    """
    norm = CropProductNorm.objects.filter(
        crop_id=crop_id,
        product_id=product_id,
    ).first()
    if not norm:
        return None

    rate = norm.application_rate
    if severity and norm.severity_adjustments:
        multiplier = norm.severity_adjustments.get(severity.upper())
        if multiplier:
            rate = rate * Decimal(str(multiplier))

    return {
        'application_rate': rate,
        'unit':             norm.unit,
        'severity_used':    severity.upper() if severity else '',
    }


def _recompute_invoice_totals(invoice) -> None:
    """Recompute SalesInvoice summary fields (taxable, CGST, SGST, grand total) from its items."""
    from decimal import ROUND_HALF_UP
    from transactions.models import SalesItem as TxSalesItem

    items = list(TxSalesItem.objects.filter(invoice=invoice))
    total_taxable = Decimal('0')
    total_tax    = Decimal('0')
    grand_total  = Decimal('0')

    for item in items:
        taxable = (item.unit_price * Decimal(str(item.quantity))).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )
        total_taxable += taxable
        total_tax     += item.tax_amount
        grand_total   += item.total_amount

    half = (total_tax / 2).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    invoice.total_taxable = total_taxable
    invoice.total_cgst    = half
    invoice.total_sgst    = half
    invoice.grand_total   = grand_total
    invoice.balance_due   = grand_total - invoice.amount_received
    invoice.save(update_fields=[
        'total_taxable', 'total_cgst', 'total_sgst', 'grand_total', 'balance_due',
    ])


def dispense_prescription_line(rx_line, batch, pack_qty: int):
    """
    Atomically dispense one PrescriptionLine:

      1. Find or create a DRAFT SalesInvoice for the consultation's customer.
         (All lines of the same consultation are collected onto the same invoice.)
      2. Create a SalesItem (unit_price from batch.base_selling_price; tax from category).
      3. Recompute invoice totals.
      4. Mark PrescriptionLine DISPENSED (chosen_batch, pack_quantity, sales_item, status).
      5. If every non-cancelled line is now DISPENSED → set consultation.status = DISPENSED.

    Returns the SalesInvoice.
    """
    import math
    from decimal import ROUND_HALF_UP
    from django.db import transaction as db_tx
    from django.utils import timezone as tz
    from transactions.models import SalesInvoice, SalesItem as TxSalesItem
    from .models import PrescriptionLine, FieldConsultation

    with db_tx.atomic():
        consultation = rx_line.consultation
        customer     = consultation.customer

        # Re-use the existing DRAFT invoice for this consultation if one was created already
        existing = (
            PrescriptionLine.objects
            .filter(
                consultation=consultation,
                sales_item__isnull=False,
                sales_item__invoice__status='DRAFT',
            )
            .select_related('sales_item__invoice')
            .exclude(pk=rx_line.pk)
            .first()
        )
        if existing:
            invoice = existing.sales_item.invoice
        else:
            invoice = SalesInvoice.objects.create(
                customer=customer,
                date=tz.now().date(),
                total_taxable=Decimal('0'),
                total_cgst=Decimal('0'),
                total_sgst=Decimal('0'),
                grand_total=Decimal('0'),
            )

        # Pricing
        unit_price = batch.base_selling_price
        product    = batch.product
        tax_rate   = (
            Decimal(str(product.category.total_tax))
            if product.category and hasattr(product.category, 'total_tax')
            else Decimal('0')
        )
        qty_d      = Decimal(str(pack_qty))
        subtotal   = (unit_price * qty_d).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        tax_amount = (subtotal * tax_rate / Decimal('100')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        sales_item = TxSalesItem.objects.create(
            invoice=invoice,
            batch=batch,
            quantity=pack_qty,
            unit_price=unit_price,
            tax_rate=tax_rate,
            tax_amount=tax_amount,
            total_amount=subtotal + tax_amount,
        )

        _recompute_invoice_totals(invoice)

        # Stamp the prescription line
        rx_line.chosen_batch  = batch
        rx_line.pack_quantity = pack_qty
        rx_line.sales_item    = sales_item
        rx_line.status        = PrescriptionLine.Status.DISPENSED
        rx_line.save(update_fields=['chosen_batch', 'pack_quantity', 'sales_item', 'status'])

        # Escalate consultation status when all active lines are dispensed
        undispensed = (
            consultation.prescription_lines
            .exclude(status__in=[
                PrescriptionLine.Status.DISPENSED,
                PrescriptionLine.Status.CANCELLED,
            ])
            .exists()
        )
        if not undispensed:
            consultation.status = FieldConsultation.Status.DISPENSED
            consultation.save(update_fields=['status'])

        return invoice


def calculate_total_quantity(dosage_per_acre, area_acres) -> Decimal:
    """dosage_per_acre × area_acres, rounded to 3 decimal places."""
    from decimal import ROUND_HALF_UP
    result = Decimal(str(dosage_per_acre)) * Decimal(str(area_acres))
    return result.quantize(Decimal('0.001'), rounding=ROUND_HALF_UP)


def get_active_cultivations(customer):
    """Return ACTIVE CultivationRecords for a customer, ordered by crop name."""
    return (
        CultivationRecord.objects
        .filter(customer=customer, status='ACTIVE')
        .select_related('crop')
        .order_by('crop__name')
    )


@dataclass
class RecommendationLine:
    crop_name: str
    product_id: int
    product_name: str
    batch_id: Optional[int]
    batch_number: Optional[str]
    batch_size: Optional[Decimal]     # package size (e.g. 50 for a 50kg bag)
    batch_unit: Optional[str]         # package unit (e.g. 'kg')
    packages_needed: int              # ceil(total_need / batch.size)
    total_qty_covered: Decimal        # packages_needed × batch.size
    norm_unit: str                    # unit from the crop norm (e.g. 'Kg')
    total_need: Decimal               # raw need = acreage × application_rate
    in_stock: bool


def get_recommendations(customer_id: int) -> list:
    """
    Returns one RecommendationLine per
    (active cultivation record × crop norm × available batch).

    Algorithm:
      1. Get all ACTIVE CultivationRecords for customer_id.
      2. For each record, get all CropProductNorms for that crop.
      3. total_need = acreage × application_rate
      4. Find Batches with current_quantity > 0, ordered soonest-expiry-first.
      5. packages_needed = ceil(total_need / batch.size)  if batch.size > 0
                          else ceil(total_need)
      6. If no stock exists: return one line with in_stock=False.
    """
    lines: list[RecommendationLine] = []

    records = (
        CultivationRecord.objects
        .filter(customer_id=customer_id, status='ACTIVE')
        .select_related('crop')
    )

    for record in records:
        norms = (
            CropProductNorm.objects
            .filter(crop=record.crop)
            .select_related('product')
        )
        for norm in norms:
            total_need = record.acreage * norm.application_rate

            batches = (
                Batch.objects
                .filter(product=norm.product, current_quantity__gt=0, is_active=True)
                .order_by('expiry_date', 'mrp')   # soonest-expiry first
            )

            if batches.exists():
                for batch in batches:
                    if batch.size and batch.size > 0:
                        packages_needed = math.ceil(float(total_need) / float(batch.size))
                        total_qty_covered = Decimal(packages_needed) * batch.size
                    else:
                        packages_needed = math.ceil(float(total_need))
                        total_qty_covered = total_need

                    lines.append(RecommendationLine(
                        crop_name=record.crop.name,
                        product_id=norm.product.id,
                        product_name=norm.product.name,
                        batch_id=batch.id,
                        batch_number=batch.batch_number,
                        batch_size=batch.size,
                        batch_unit=batch.unit,
                        packages_needed=packages_needed,
                        total_qty_covered=total_qty_covered,
                        norm_unit=norm.unit,
                        total_need=total_need,
                        in_stock=True,
                    ))
            else:
                # No stock available — still surface so owner knows what to order
                lines.append(RecommendationLine(
                    crop_name=record.crop.name,
                    product_id=norm.product.id,
                    product_name=norm.product.name,
                    batch_id=None,
                    batch_number=None,
                    batch_size=None,
                    batch_unit=None,
                    packages_needed=math.ceil(float(total_need)),
                    total_qty_covered=total_need,
                    norm_unit=norm.unit,
                    total_need=total_need,
                    in_stock=False,
                ))

    return lines
