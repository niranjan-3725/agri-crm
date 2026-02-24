
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.contrib import messages
from decimal import Decimal
import json

from .models import (
    Quotation, QuotationItem, SalesOrder, SalesOrderItem,
    DeliveryNote, DeliveryNoteItem, Customer, Batch,
    DOCUMENT_STATUS_CHOICES
)

# --- QUOTATION VIEWS ---
@login_required
def quotation_list(request):
    quotations = Quotation.objects.all().order_by('-date', '-id')
    return render(request, 'transactions/quotation_list.html', {'quotations': quotations})

@login_required
def quotation_detail(request, pk):
    quotation = get_object_or_404(Quotation, pk=pk)
    return render(request, 'transactions/quotation_detail.html', {'quotation': quotation})

@login_required
def create_quotation(request):
    if request.method == 'POST':
        with transaction.atomic():
            customer_id = request.POST.get('customer')
            date = request.POST.get('date')
            customer = Customer.objects.get(id=customer_id) if customer_id else None
            
            quotation = Quotation.objects.create(
                customer=customer, date=date, grand_total=0
            )
            
            batch_ids = request.POST.getlist('batch_id[]')
            quantities = request.POST.getlist('qty[]')
            prices = request.POST.getlist('price[]')
            
            grand_total = 0
            for i in range(len(batch_ids)):
                if not batch_ids[i] or int(quantities[i]) <= 0: continue
                batch = Batch.objects.get(id=batch_ids[i])
                qty = int(quantities[i])
                price = float(prices[i])
                amount = qty * price
                
                QuotationItem.objects.create(
                    quotation=quotation, batch=batch, quantity=qty,
                    unit_price=price, amount=amount
                )
                grand_total += amount
                
            quotation.grand_total = grand_total
            quotation.save()
            messages.success(request, f'Quotation {quotation.id} created.')
            return redirect('quotation_detail', pk=quotation.pk)
    return render(request, 'transactions/quotation_form.html')

@login_required
def submit_quotation(request, pk):
    q = get_object_or_404(Quotation, pk=pk)
    q.submit()
    return redirect('quotation_detail', pk=pk)

@login_required
def cancel_quotation(request, pk):
    q = get_object_or_404(Quotation, pk=pk)
    q.cancel()
    return redirect('quotation_detail', pk=pk)

# --- SALES ORDER VIEWS ---
@login_required
def sales_order_list(request):
    orders = SalesOrder.objects.all().order_by('-date', '-id')
    return render(request, 'transactions/sales_order_list.html', {'orders': orders})

@login_required
def sales_order_detail(request, pk):
    order = get_object_or_404(SalesOrder, pk=pk)
    return render(request, 'transactions/sales_order_detail.html', {'order': order})

@login_required
def create_sales_order(request):
    quotation_id = request.GET.get('quotation_id')
    existing_items = []
    initial_customer = None
    
    if quotation_id:
        q = get_object_or_404(Quotation, pk=quotation_id)
        initial_customer = q.customer
        for item in q.items.all():
            existing_items.append({
                'product_id': item.batch.product.id,
                'product_name': item.batch.product.name,
                'batch_id': item.batch.id,
                'batch_number': item.batch.batch_number,
                'current_stock': item.batch.current_quantity,
                'qty': item.quantity,
                'price': float(item.unit_price),
                'total': float(item.amount),
                'size': item.batch.size,
                'unit': item.batch.unit,
                'size_label': f'{item.batch.size} {item.batch.unit}' if item.batch.size else '',
                'mfg_date': str(item.batch.manufacturing_date) if item.batch.manufacturing_date else '',
                'expiry_date': str(item.batch.expiry_date) if item.batch.expiry_date else '',
                'quotation_item_id': item.id
            })

    if request.method == 'POST':
        with transaction.atomic():
            customer_id = request.POST.get('customer')
            date = request.POST.get('date')
            customer = Customer.objects.get(id=customer_id) if customer_id else None
            q_id = request.POST.get('source_quotation_id')
            
            order = SalesOrder.objects.create(
                customer=customer, date=date, grand_total=0,
                quotation_id=q_id if q_id else None
            )
            
            batch_ids = request.POST.getlist('batch_id[]')
            quantities = request.POST.getlist('qty[]')
            prices = request.POST.getlist('price[]')
            
            grand_total = 0
            for i in range(len(batch_ids)):
                if not batch_ids[i] or int(quantities[i]) <= 0: continue
                batch = Batch.objects.get(id=batch_ids[i])
                qty = int(quantities[i])
                price = float(prices[i])
                amount = qty * price
                
                SalesOrderItem.objects.create(
                    sales_order=order, batch=batch, quantity=qty,
                    unit_price=price, amount=amount
                )
                grand_total += amount
                
            order.grand_total = grand_total
            order.save()
            messages.success(request, f'Sales Order {order.id} created.')
            return redirect('sales_order_detail', pk=order.pk)
            
    return render(request, 'transactions/sales_order_form.html', {
        'existing_items': existing_items,
        'initial_customer': initial_customer,
        'source_quotation_id': quotation_id
    })

@login_required
def submit_sales_order(request, pk):
    o = get_object_or_404(SalesOrder, pk=pk)
    o.submit()
    return redirect('sales_order_detail', pk=pk)

@login_required
def cancel_sales_order(request, pk):
    o = get_object_or_404(SalesOrder, pk=pk)
    o.cancel()
    return redirect('sales_order_detail', pk=pk)
    
# --- DELIVERY NOTE VIEWS ---
@login_required
def delivery_note_list(request):
    notes = DeliveryNote.objects.all().order_by('-date', '-id')
    return render(request, 'transactions/delivery_note_list.html', {'notes': notes})

@login_required
def delivery_note_detail(request, pk):
    note = get_object_or_404(DeliveryNote, pk=pk)
    return render(request, 'transactions/delivery_note_detail.html', {'note': note})

@login_required
def create_delivery_note(request):
    sales_order_id = request.GET.get('sales_order_id')
    existing_items = []
    initial_customer = None
    
    if sales_order_id:
        so = get_object_or_404(SalesOrder, pk=sales_order_id)
        initial_customer = so.customer
        for item in so.items.all():
            pending_qty = item.quantity - item.delivered_qty
            if pending_qty > 0:
                existing_items.append({
                    'product_id': item.batch.product.id,
                    'product_name': item.batch.product.name,
                    'batch_id': item.batch.id,
                    'batch_number': item.batch.batch_number,
                    'current_stock': item.batch.current_quantity,
                    'qty': pending_qty,
                    'price': float(item.unit_price),
                    'total': float(pending_qty * item.unit_price),
                    'size': item.batch.size,
                    'unit': item.batch.unit,
                    'size_label': f'{item.batch.size} {item.batch.unit}' if item.batch.size else '',
                    'mfg_date': str(item.batch.manufacturing_date) if item.batch.manufacturing_date else '',
                    'expiry_date': str(item.batch.expiry_date) if item.batch.expiry_date else '',
                    'sales_order_item_id': item.id
                })

    if request.method == 'POST':
        with transaction.atomic():
            customer_id = request.POST.get('customer')
            date = request.POST.get('date')
            customer = Customer.objects.get(id=customer_id) if customer_id else None
            so_id = request.POST.get('source_sales_order_id')
            
            note = DeliveryNote.objects.create(
                customer=customer, date=date, 
                sales_order_id=so_id if so_id else None
            )
            
            batch_ids = request.POST.getlist('batch_id[]')
            quantities = request.POST.getlist('qty[]')
            
            for i in range(len(batch_ids)):
                if not batch_ids[i] or int(quantities[i]) <= 0: continue
                batch = Batch.objects.get(id=batch_ids[i])
                qty = int(quantities[i])
                
                soi_id = None
                if so_id:
                    soi = SalesOrderItem.objects.filter(sales_order_id=so_id, batch_id=batch.id).first()
                    if soi:
                        soi_id = soi.id
                
                DeliveryNoteItem.objects.create(
                    delivery_note=note, batch=batch, quantity=qty,
                    sales_order_item_id=soi_id
                )
                
            messages.success(request, f'Delivery Note {note.id} created.')
            return redirect('delivery_note_detail', pk=note.pk)
            
    return render(request, 'transactions/delivery_note_form.html', {
        'existing_items': existing_items,
        'initial_customer': initial_customer,
        'source_sales_order_id': sales_order_id
    })

@login_required
def submit_delivery_note(request, pk):
    n = get_object_or_404(DeliveryNote, pk=pk)
    n.submit()
    return redirect('delivery_note_detail', pk=pk)

@login_required
def cancel_delivery_note(request, pk):
    n = get_object_or_404(DeliveryNote, pk=pk)
    n.cancel()
    return redirect('delivery_note_detail', pk=pk)

