from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.db import transaction
from django.contrib import messages
from django.utils import timezone
from django.core.exceptions import ValidationError
import json

from .models import (
    Supplier, Batch, PurchaseOrder, PurchaseOrderItem, PurchaseReceipt, PurchaseReceiptItem
)

# --- PURCHASE ORDER VIEWS ---

def purchase_order_list(request):
    orders = PurchaseOrder.objects.all().order_by('-date', '-id')
    return render(request, 'transactions/purchase_order_list.html', {'orders': orders})


def purchase_order_detail(request, pk):
    po = get_object_or_404(PurchaseOrder, pk=pk)
    return render(request, 'transactions/purchase_order_detail.html', {'po': po})


def create_purchase_order(request):
    suppliers = Supplier.objects.all()
    if request.method == 'POST':
        with transaction.atomic():
            supplier_id = request.POST.get('supplier')
            date = request.POST.get('date') or timezone.now().date()
            supplier = Supplier.objects.get(id=supplier_id) if supplier_id else None
            
            order = PurchaseOrder.objects.create(
                supplier=supplier, date=date, grand_total=0
            )
            
            product_names = request.POST.getlist('product_name[]')
            batch_numbers = request.POST.getlist('batch_number[]')
            purchase_rates = request.POST.getlist('purchase_rate[]')
            quantities = request.POST.getlist('qty[]')
            
            grand_total = 0
            for i in range(len(product_names)):
                p_name = product_names[i]
                if not p_name or not quantities[i]: continue
                
                # Fetch product
                from master_data.models import Product
                product = Product.objects.filter(name=p_name).first()
                if not product:
                    continue
                
                qty = int(quantities[i])
                rate = float(purchase_rates[i]) if purchase_rates[i] else 0
                amount = qty * rate
                
                # Create a batch
                batch_number = batch_numbers[i] if batch_numbers[i] else f"PO-{timezone.now().timestamp()}"
                batch, _ = Batch.objects.get_or_create(
                    product=product,
                    batch_number=batch_number,
                    defaults={'mrp': 0, 'purchase_price': rate, 'base_selling_price': 0, 'current_quantity': 0}
                )
                
                PurchaseOrderItem.objects.create(
                    purchase_order=order, batch=batch, quantity=qty,
                    unit_price=rate, amount=amount
                )
                grand_total += amount
                
            order.grand_total = grand_total
            order.save()
            messages.success(request, f'Purchase Order {order.pk} created.')
            return redirect('purchase_order_detail', pk=order.pk)
    
    return render(request, 'transactions/purchase_order_form.html', {
        'suppliers': suppliers,
        'existing_items_json': '[]'
    })


def submit_purchase_order(request, pk):
    po = get_object_or_404(PurchaseOrder, pk=pk)
    po.submit()
    return redirect('purchase_order_detail', pk=pk)


def cancel_purchase_order(request, pk):
    po = get_object_or_404(PurchaseOrder, pk=pk)
    po.cancel()
    return redirect('purchase_order_detail', pk=pk)


# --- PURCHASE RECEIPT VIEWS ---

def purchase_receipt_list(request):
    receipts = PurchaseReceipt.objects.all().order_by('-date', '-id')
    return render(request, 'transactions/purchase_receipt_list.html', {'receipts': receipts})


def purchase_receipt_detail(request, pk):
    from .models import PurchaseInvoice
    receipt = get_object_or_404(PurchaseReceipt, pk=pk)
    ghost_invoice = receipt.invoices.filter(status='DRAFT').first()
    return render(request, 'transactions/purchase_receipt_detail.html', {
        'receipt': receipt,
        'ghost_invoice': ghost_invoice,
        'submit_url': reverse('submit_purchase_receipt', kwargs={'pk': pk}),
        'cancel_url': reverse('cancel_purchase_receipt', kwargs={'pk': pk}),
    })


def create_purchase_receipt(request):
    suppliers = Supplier.objects.all()
    purchase_order_id = request.GET.get('purchase_order_id')
    existing_items = []
    supplier = None
    
    if purchase_order_id:
        po = get_object_or_404(PurchaseOrder, pk=purchase_order_id)
        supplier = po.supplier
        for item in po.items.all():
            pending = item.quantity - item.received_qty
            if pending > 0:
                existing_items.append({
                    'id': str(item.id),
                    'product_id': item.batch.product.id,
                    'product_name': str(item.batch.product.name),
                    'batch_number': str(item.batch.batch_number),
                    'qty': pending,
                    'rate': float(item.unit_price),
                    'product_tax_rate': float(item.batch.product.category.total_tax) if item.batch.product.category else 0,
                    'mrp': float(item.batch.mrp),
                    'selling_price': float(item.batch.base_selling_price),
                })
    
    if request.method == 'POST':
        with transaction.atomic():
            supplier_id = request.POST.get('supplier')
            date = request.POST.get('date') or timezone.now().date()
            po_id = request.POST.get('source_purchase_order_id')
            
            sup = Supplier.objects.get(id=supplier_id) if supplier_id else None
            
            receipt = PurchaseReceipt.objects.create(
                supplier=sup, date=date, purchase_order_id=po_id if po_id else None
            )
            
            product_names = request.POST.getlist('product_name[]')
            batch_numbers = request.POST.getlist('batch_number[]')
            quantities = request.POST.getlist('qty[]')
            purchase_rates = request.POST.getlist('purchase_rate[]')
            
            for i in range(len(product_names)):
                p_name = product_names[i]
                if not p_name or not quantities[i]: continue
                qty = int(quantities[i])
                rate = float(purchase_rates[i]) if purchase_rates[i] else 0
                
                from master_data.models import Product
                product = Product.objects.filter(name=p_name).first()
                if not product: continue
                batch_number = batch_numbers[i] if batch_numbers[i] else f"PR-{timezone.now().timestamp()}"
                batch, _ = Batch.objects.get_or_create(
                    product=product, batch_number=batch_number,
                    defaults={'mrp': 0, 'purchase_price': rate, 'base_selling_price': 0, 'current_quantity': 0}
                )
                
                poi_id = None
                if po_id:
                    poi = PurchaseOrderItem.objects.filter(purchase_order_id=po_id, batch=batch).first()
                    if poi: poi_id = poi.id
                
                PurchaseReceiptItem.objects.create(
                    receipt=receipt, batch=batch, quantity=qty, purchase_order_item_id=poi_id
                )
            messages.success(request, f'Purchase Receipt {receipt.pk} created.')
            return redirect('purchase_receipt_detail', pk=receipt.pk)
            
    return render(request, 'transactions/purchase_receipt_form.html', {
        'suppliers': suppliers,
        'existing_items_json': json.dumps(existing_items),
        'source_purchase_order_id': purchase_order_id,
        'supplier': supplier
    })


def submit_purchase_receipt(request, pk):
    pr = get_object_or_404(PurchaseReceipt, pk=pk)
    pr.submit()
    return redirect('purchase_receipt_detail', pk=pk)


def cancel_purchase_receipt(request, pk):
    pr = get_object_or_404(PurchaseReceipt, pk=pk)
    try:
        pr.cancel()
        messages.success(request, f"Purchase Receipt #{pk} cancelled.")
    except ValidationError as e:
        messages.error(request, e.message if hasattr(e, 'message') else str(e))
    return redirect('purchase_receipt_detail', pk=pk)
