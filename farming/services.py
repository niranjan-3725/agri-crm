"""
Recommendation Engine — pure functions, no side effects, no HTTP context.
"""
import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from inventory.models import Batch
from .models import CultivationRecord, CropProductNorm


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
