from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
# Force reload
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from datetime import timedelta
import json
from django.http import HttpResponse, JsonResponse
from django.db import transaction
from django.db.models import Sum, Count, Q, F, ExpressionWrapper, FloatField
from django.core.paginator import Paginator
from django.core.exceptions import ValidationError
from decimal import Decimal
from master_data.models import Product, Customer, Supplier, Category, Manufacturer
from inventory.models import Batch
from .models import SalesInvoice, SalesItem, PurchaseInvoice, PurchaseItem, PurchaseReturn, PurchaseReturnItem, SalesReturn, SalesReturnItem, SupplierPayment

def search_products(request):
    query = request.GET.get('q', '')
    if query:
        products = Product.objects.filter(name__icontains=query)[:20]
    else:
        products = Product.objects.all()[:50]
        
    if request.GET.get('format') == 'json':
        data = [{
            'id': p.id, 
            'name': p.name,
            'tax_rate': float(p.category.total_tax) if p.category else 0
        } for p in products]
        return JsonResponse(data, safe=False)
        
    options = "".join([f'<option value="{p.name}"></option>' for p in products])
    return HttpResponse(options)

def get_batch_details(request):
    batch_number = request.GET.get('batch_number')
    if not batch_number:
        return HttpResponse("")
    
    try:
        # Assuming batch_number is unique per product or we just take the first matching active one
        # Ideally we should filter by product too, but the prompt says Input: batch_id or batch_number
        # Let's assume the dropdown sends the batch ID or we filter by the visible text
        # PROMPT REQ: "Input: batch_id" -> Logic: Fetch Batch.
        # But HTMX usually sends value. Let's assume input name="batch_id" mapping.
        
        batch_id = request.GET.get('batch_id')
        batch = Batch.objects.get(id=batch_id)
        
        # Calculate tax rate logic (from Category)
        tax_rate = batch.product.category.total_tax
        
        html = f"""
        <input type="hidden" class="unit-price" value="{batch.base_selling_price}">
        <input type="hidden" class="tax-rate" value="{tax_rate}">
        <input type="hidden" class="available-stock" value="{batch.current_quantity}">
        <span class="text-sm text-gray-500">
            Price: {batch.base_selling_price} | Stock: {batch.current_quantity} | Tax: {tax_rate}%
        </span>
        """
        return HttpResponse(html)
    except Batch.DoesNotExist:
        return HttpResponse("")

def create_sale(request):
    if request.method == 'POST':
        try:
            with transaction.atomic():
                customer_id = request.POST.get('customer')
                date = request.POST.get('date')
                
                customer = Customer.objects.get(id=customer_id) if customer_id else None
                
                # Create Invoice
                invoice = SalesInvoice.objects.create(
                    customer=customer,
                    date=date,
                    total_taxable=0,
                    total_cgst=0,
                    total_sgst=0,
                    grand_total=0 # Will update after items
                )
                
                # Process Items
                batch_ids = request.POST.getlist('batch_id[]')
                quantities = request.POST.getlist('qty[]')
                prices = request.POST.getlist('price[]')
                
                total_taxable = 0
                total_cgst = 0
                total_sgst = 0
                grand_total = 0
                
                for i in range(len(batch_ids)):
                    batch_id = batch_ids[i]
                    qty = int(quantities[i])
                    price = float(prices[i])
                    
                    if not batch_id or qty <= 0:
                        continue
                        
                    batch = Batch.objects.get(id=batch_id)
                    
                    # Calculations
                    tax_rate = batch.product.category.total_tax
                    tax_amount = (price * qty * float(tax_rate)) / 100
                    total = (price * qty) + tax_amount
                    
                    # Create Item (Signals will handle stock deduction)
                    item = SalesItem(
                        invoice=invoice,
                        batch=batch,
                        quantity=qty,
                        unit_price=price,
                        tax_rate=tax_rate,
                        tax_amount=tax_amount,
                        total_amount=total
                    )
                    # Run validation (checks stock)
                    item.clean()
                    item.save()
                    
                    total_taxable += (price * qty)
                    # Approximate split
                    total_cgst += tax_amount / 2
                    total_sgst += tax_amount / 2
                    grand_total += total
                
                # Update Invoice Totals
                invoice.total_taxable = total_taxable
                invoice.total_cgst = total_cgst
                invoice.total_sgst = total_sgst
                invoice.grand_total = grand_total
                invoice.save()
                
                return redirect('dashboard')
                
        except ValidationError as e:
            customers = Customer.objects.all()
            return render(request, 'transactions/sales_form.html', {'customers': customers, 'error': e.message})
        except Exception as e:
            customers = Customer.objects.all()
            return render(request, 'transactions/sales_form.html', {'customers': customers, 'error': str(e)})

    # GET Request
    customers = Customer.objects.all()
    # Batches for dropdown (Active and > 0 stock)
    batches = Batch.objects.filter(is_active=True, current_quantity__gt=0).select_related('product')
    return render(request, 'transactions/sales_form.html', {'customers': customers, 'batches': batches})

def sales_list(request):
    invoices_list = SalesInvoice.objects.all().order_by('-date', '-id')
    
    # Filter
    query = request.GET.get('q')
    if query:
        invoices_list = invoices_list.filter(
            Q(customer__name__icontains=query) | 
            Q(invoice_number__icontains=query) |
            Q(customer__mobile_no__icontains=query)
        )
    
    date_filter = request.GET.get('date')
    if date_filter:
        invoices_list = invoices_list.filter(date=date_filter)

    # Calculate Total Revenue for visible items
    total_revenue = invoices_list.aggregate(Sum('grand_total'))['grand_total__sum'] or 0
    
    # Pagination
    paginator = Paginator(invoices_list, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'invoices': page_obj,
        'total_revenue': total_revenue,
        'q': query,
        'date_filter': date_filter,
    }
    
    if request.headers.get('HX-Request'):
        return render(request, 'transactions/partials/sales_table.html', context)
        
    return render(request, 'transactions/sales_list.html', context)

def invoice_detail(request, pk):
    invoice = get_object_or_404(SalesInvoice, pk=pk)
    return render(request, 'transactions/invoice_detail.html', {'invoice': invoice})

def purchase_list(request):
    invoices_list = PurchaseInvoice.objects.all().order_by('-date', '-id')
    
    # Filter
    query = request.GET.get('q')
    if query:
        invoices_list = invoices_list.filter(
            Q(supplier__name__icontains=query) | 
            Q(invoice_number__icontains=query)
        )
    
    # Annotate items count
    invoices_list = invoices_list.annotate(items_count=Count('items'))

    # Monthly Overview Data
    now = timezone.now()
    current_year = now.year
    current_month = now.month
    
    # Calculate previous month date (handle year rollover)
    first_day_this_month = now.replace(day=1)
    prev_month_date = first_day_this_month - timedelta(days=1)
    prev_month = prev_month_date.month
    prev_year = prev_month_date.year

    # Current Month Total
    monthly_total = PurchaseInvoice.objects.filter(
        date__year=current_year, 
        date__month=current_month
    ).aggregate(Sum('total_amount'))['total_amount__sum'] or 0

    # Last Month Total
    last_month_total = PurchaseInvoice.objects.filter(
        date__year=prev_year, 
        date__month=prev_month
    ).aggregate(Sum('total_amount'))['total_amount__sum'] or 0

    # Trend Analysis
    has_last_data = last_month_total > 0
    percentage_diff = 0
    trend = 'neutral'

    if has_last_data:
        diff = monthly_total - last_month_total
        percentage_diff = (abs(diff) / last_month_total) * 100
        if diff > 0:
            trend = 'up'
        elif diff < 0:
            trend = 'down'
    
    # Top Suppliers (Indofil Industries etc mockup equivalent)
    # Annotate suppliers with total purchase amount
    top_suppliers = Supplier.objects.annotate(
        total_purchased=Sum('purchaseinvoice__total_amount')
    ).order_by('-total_purchased')[:5]

    # Pagination
    paginator = Paginator(invoices_list, 10) # Matches 'ITEMS_PER_PAGE = 5' roughly, or 10
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'invoices': page_obj,
        'q': query,
        'monthly_total': monthly_total,
        'top_suppliers': top_suppliers,
        'percentage_diff': round(percentage_diff, 1),
        'trend': trend,
        'has_last_data': has_last_data,
    }
    
    if request.headers.get('HX-Request'):
        return render(request, 'transactions/partials/purchase_table.html', context)
        
    return render(request, 'transactions/purchase_list.html', context)

@csrf_exempt
def accounts_payable(request):
    """
    Payable Command Center: KPI Dashboard for Supplier Payments
    """
    now = timezone.now()
    today = now.date()
    current_year = now.year
    current_month = now.month

    # list Queries
    # Invoices: UNPAID/PARTIAL OR PAID (Recent - last 30 days) to show "Settled" status
    thirty_days_ago = today - timedelta(days=30)
    pending_invoices = PurchaseInvoice.objects.filter(
        Q(payment_status__in=['UNPAID', 'PARTIAL']) | 
        Q(payment_status='PAID', date__gte=thirty_days_ago)
    ).order_by('due_date')

    # Recent Activity: Last 10 payments
    recent_payments = SupplierPayment.objects.select_related('invoice', 'invoice__supplier').order_by('-payment_date', '-created_at')[:10]

    # KPI 1: Total Outstanding 
    total_outstanding = pending_invoices.aggregate(Sum('balance_due'))['balance_due__sum'] or 0

    # KPI 2: Overdue Amount (Due date passed)
    overdue_amount = pending_invoices.filter(due_date__lt=today).aggregate(Sum('balance_due'))['balance_due__sum'] or 0

    # KPI 3: Paid This Month
    paid_this_month = SupplierPayment.objects.filter(
        payment_date__year=current_year,
        payment_date__month=current_month
    ).aggregate(Sum('amount'))['amount__sum'] or 0

    context = {
        'pending_invoices': pending_invoices,
        'recent_payments': recent_payments,
        'total_outstanding': total_outstanding,
        'overdue_amount': overdue_amount,
        'paid_this_month': paid_this_month,
        'today': today,
    }
    return render(request, 'transactions/accounts_payable.html', context)

@csrf_exempt
@require_POST
def record_payment(request):
    invoice_id = request.POST.get('invoice_id')
    amount = Decimal(request.POST.get('amount', 0))
    mode = request.POST.get('payment_mode')
    notes = request.POST.get('notes', '') # Capture notes
    
    invoice = get_object_or_404(PurchaseInvoice, id=invoice_id)
    
    # Create Payment (Signal updates invoice balance/status)
    SupplierPayment.objects.create(
        invoice=invoice,
        amount=amount,
        payment_mode=mode,
        payment_date=timezone.now().date(),
        notes=notes # Save notes
    )
    
    return HttpResponse(status=200)

@require_POST
def delete_supplier_payment(request, pk):
    payment = get_object_or_404(SupplierPayment, pk=pk)
    invoice_pk = payment.invoice.pk
    payment.delete() # Signal handles balance update
    return redirect('purchase_detail', pk=invoice_pk)

def purchase_detail(request, pk):
    invoice = get_object_or_404(PurchaseInvoice, pk=pk)
    items = invoice.items.select_related('batch__product').annotate(
        margin=ExpressionWrapper(
            (F('batch__base_selling_price') - F('basic_rate')) * 100.0 / F('basic_rate'),
            output_field=FloatField()
        )
    ).all()
    
    # Calculate totals for breakdown
    tax_total = items.aggregate(Sum('tax_amount'))['tax_amount__sum'] or 0
    loading = invoice.loading_charges or 0
    discount = invoice.additional_discount or 0
    
    # Logic: Grand Total = Subtotal + Tax + Loading - Discount
    # So: Subtotal = Grand Total - Tax - Loading + Discount
    subtotal = invoice.total_amount - tax_total - loading + discount
    
    return render(request, 'transactions/purchase_detail.html', {
        'invoice': invoice,
        'items': items,
        'tax_total': tax_total,
        'subtotal': subtotal
    })

def purchase_edit(request, pk):
    invoice = get_object_or_404(PurchaseInvoice, pk=pk)
    suppliers = Supplier.objects.all()
    categories = Category.objects.all()
    manufacturers = Manufacturer.objects.all()
    
    # Get existing items for pre-population
    existing_items = []
    for item in invoice.items.select_related('batch__product'):
        # Fallback: if basic_rate is 0, use batch.purchase_price as the cost
        cost = float(item.basic_rate) if item.basic_rate else float(item.batch.purchase_price or 0)
        selling = float(item.selling_price) if item.selling_price else (float(item.batch.base_selling_price) if item.batch.base_selling_price else 0)
        
        # Use stored margin if available, else calculate from cost/selling
        if item.profit_margin:
            margin = float(item.profit_margin)
        elif cost > 0:
            margin = round(((selling - cost) / cost) * 100, 2)
        else:
            margin = 0
            
        tax_amt = float(item.tax_amount)
        net_cost = cost + (tax_amt / item.quantity if item.quantity else 0)

        existing_items.append({
            'id': item.id, # Row ID (optional but good for key?) Actually rows use counter.
            'product_id': item.batch.product.id,
            'product_name': item.batch.product.name,
            'searchResults': [],
            'showDropdown': False,
            'batch_number': item.batch.batch_number,
            'mfg_date': str(item.batch.manufacturing_date) if item.batch.manufacturing_date else '',
            'expiry_date': str(item.batch.expiry_date) if item.batch.expiry_date else '',
            'size': str(item.batch.size) if item.batch.size else '',
            'unit': item.batch.unit or 'kg',
            'qty': item.quantity,
            'mrp': float(item.batch.mrp) if item.batch.mrp else 0,
            'selling_price': selling,
            'rate': cost,
            'net_cost': round(net_cost, 2),
            'margin_percent': margin,
            'product_tax_rate': float(item.batch.product.category.total_tax) if item.batch.product.category else 0,
            'tax_amount': tax_amt,
            'total': float(item.total_amount)
        })
    
    if request.method == 'POST':
        try:
            with transaction.atomic():
                # Validate supplier_id before updating
                supplier_id = request.POST.get('supplier')
                if not supplier_id:
                    return render(request, 'transactions/purchase_form.html', {
                        'invoice': invoice,
                        'suppliers': suppliers,
                        'categories': categories,
                        'manufacturers': manufacturers,
                        'existing_items': existing_items,
                        'existing_items_json': json.dumps(existing_items),
                        'error': 'Please select a valid supplier.'
                    })
                
                try:
                    supplier = Supplier.objects.get(id=supplier_id)
                except (ValueError, Supplier.DoesNotExist):
                    return render(request, 'transactions/purchase_form.html', {
                        'invoice': invoice,
                        'suppliers': suppliers,
                        'categories': categories,
                        'manufacturers': manufacturers,
                        'existing_items': existing_items,
                        'existing_items_json': json.dumps(existing_items),
                        'error': 'Invalid supplier selected. Please choose a valid supplier.'
                    })
                
                # Update invoice header
                invoice.supplier = supplier
                invoice.invoice_number = request.POST.get('invoice_number')
                invoice.date = request.POST.get('date')
                invoice.loading_charges = request.POST.get('loading_charges') or 0
                invoice.additional_discount = request.POST.get('discount') or 0
                
                # Delete old items and reverse stock
                for item in invoice.items.all():
                    item.batch.current_quantity -= item.quantity
                    item.batch.save()
                    item.delete()
                
                # Process new items (same logic as create_purchase)
                product_names = request.POST.getlist('product_name[]')
                batch_numbers = request.POST.getlist('batch_number[]')
                mfg_dates = request.POST.getlist('mfg_date[]')
                expiry_dates = request.POST.getlist('expiry_date[]')
                sizes = request.POST.getlist('size[]')
                units = request.POST.getlist('unit[]')
                mrps = request.POST.getlist('mrp[]')
                rates = request.POST.getlist('purchase_rate[]')
                selling_prices = request.POST.getlist('selling_price[]')
                margins = request.POST.getlist('margin[]')
                quantities = request.POST.getlist('qty[]')
                
                grand_total = 0
                
                for i in range(len(product_names)):
                    product_name = product_names[i]
                    if not product_name: continue # Skip empty rows
                    
                    product = Product.objects.get(name=product_name)
                    
                    batch_number = batch_numbers[i]
                    mfg_date = mfg_dates[i] if i < len(mfg_dates) and mfg_dates[i] else None
                    expiry = expiry_dates[i] if i < len(expiry_dates) and expiry_dates[i] else None
                    size_val = sizes[i] if i < len(sizes) and sizes[i] else 0
                    unit_val = units[i] if i < len(units) else 'kg'
                    mrp = float(mrps[i]) if i < len(mrps) and mrps[i] else 0
                    rate_pre_tax = float(rates[i]) if rates[i] else 0
                    sell_price = float(selling_prices[i]) if i < len(selling_prices) and selling_prices[i] else mrp
                    margin_val = float(margins[i]) if i < len(margins) and margins[i] else 0
                    qty = int(quantities[i]) if quantities[i] else 0
                    
                    tax_rate = float(product.category.total_tax) if product.category else 0
                    tax_amount_per_unit = rate_pre_tax * (tax_rate / 100)
                    total_tax_amount = tax_amount_per_unit * qty
                    net_cost_per_unit = rate_pre_tax + tax_amount_per_unit
                    total_line_amount = net_cost_per_unit * qty
                    
                    batch, created = Batch.objects.get_or_create(
                        product=product,
                        batch_number=batch_number,
                        defaults={
                            'manufacturing_date': mfg_date,
                            'expiry_date': expiry,
                            'size': size_val,
                            'unit': unit_val,
                            'purchase_price': net_cost_per_unit,
                            'mrp': mrp,
                            'base_selling_price': sell_price,
                            'current_quantity': 0
                        }
                    )
                    
                    if not created:
                        batch.manufacturing_date = mfg_date or batch.manufacturing_date
                        batch.expiry_date = expiry or batch.expiry_date
                        batch.size = size_val or batch.size
                        batch.unit = unit_val or batch.unit
                        batch.mrp = mrp or batch.mrp
                        batch.base_selling_price = sell_price or batch.base_selling_price
                        batch.purchase_price = net_cost_per_unit
                        batch.save()
                    
                    batch.current_quantity += qty
                    batch.save()
                    
                    PurchaseItem.objects.create(
                        invoice=invoice,
                        batch=batch,
                        quantity=qty,
                        tax_amount=total_tax_amount,
                        basic_rate=rate_pre_tax,
                        selling_price=sell_price,
                        profit_margin=margin_val,
                        total_amount=total_line_amount
                    )
                    
                    grand_total += total_line_amount
                
                invoice.total_amount = Decimal(str(grand_total + float(invoice.loading_charges) - float(invoice.additional_discount)))
                
                # Sprint 22: Payment Status Tracking
                payment_status = request.POST.get('payment_status', 'UNPAID')
                amount_paid = Decimal(request.POST.get('amount_paid') or 0)
                
                if payment_status == 'PAID':
                    amount_paid = invoice.total_amount
                    
                invoice.payment_status = payment_status
                invoice.amount_paid = amount_paid
                invoice.save()
                
                return redirect('purchase_detail', pk=invoice.pk)
                
        except Exception as e:
            return render(request, 'transactions/purchase_form.html', {
                'invoice': invoice,
                'suppliers': suppliers,
                'categories': categories,
                'manufacturers': manufacturers,
                'existing_items': existing_items,
                'existing_items_json': json.dumps(existing_items),
                'error': str(e)
            })
    
    return render(request, 'transactions/purchase_form.html', {
        'invoice': invoice,
        'suppliers': suppliers,
        'categories': categories,
        'manufacturers': manufacturers,
        'existing_items': existing_items,
        'existing_items_json': json.dumps(existing_items)
    })

def purchase_delete(request, pk):
    invoice = get_object_or_404(PurchaseInvoice, pk=pk)
    
    if request.method == 'POST':
        # Reverse stock for all items before deleting
        for item in invoice.items.all():
            item.batch.current_quantity -= item.quantity
            item.batch.save()
        invoice.delete()
        return redirect('purchase_list')
    
    return render(request, 'transactions/purchase_confirm_delete.html', {
        'invoice': invoice
    })

def get_product_details(request):
    product_name = request.GET.get('name')
    if not product_name:
        return JsonResponse({'error': 'Product name required'}, status=400)
    
    try:
        product = Product.objects.get(name=product_name)
        return JsonResponse({
            'id': product.id,
            'tax_rate': float(product.category.total_tax)
        })
    except Product.DoesNotExist:
         return JsonResponse({'error': 'Product not found'}, status=404)

def create_purchase(request):
    suppliers = Supplier.objects.all()
    categories = Category.objects.all()
    manufacturers = Manufacturer.objects.all()
    
    if request.method == 'POST':
        try:
            with transaction.atomic():
                supplier_id = request.POST.get('supplier')
                invoice_number = request.POST.get('invoice_number')
                date = request.POST.get('date')
                
                # Validate supplier_id before querying
                if not supplier_id:
                    return render(request, 'transactions/purchase_form.html', {
                        'suppliers': suppliers, 
                        'categories': categories, 
                        'manufacturers': manufacturers, 
                        'error': 'Please select a valid supplier.'
                    })
                
                try:
                    supplier = Supplier.objects.get(id=supplier_id)
                except (ValueError, Supplier.DoesNotExist):
                    return render(request, 'transactions/purchase_form.html', {
                        'suppliers': suppliers, 
                        'categories': categories, 
                        'manufacturers': manufacturers, 
                        'error': 'Invalid supplier selected. Please choose a valid supplier.'
                    })
                
                # Header
                loading_charges = float(request.POST.get('loading_charges') or 0)
                additional_discount = float(request.POST.get('discount') or 0)
                
                invoice = PurchaseInvoice.objects.create(
                    supplier=supplier,
                    invoice_number=invoice_number,
                    date=date,
                    loading_charges=loading_charges,
                    additional_discount=additional_discount,
                    total_amount=0 
                )
                
                # Items
                product_names = request.POST.getlist('product_search') 
                
                # Note: The template will use Alpine to name inputs as product_name[], etc.
                # But we should rely on the names we set in the template.
                # Let's assume the template sets correct array names.
                
                product_names = request.POST.getlist('product_name[]')
                batch_numbers = request.POST.getlist('batch_number[]')
                mfg_dates = request.POST.getlist('mfg_date[]')
                expiry_dates = request.POST.getlist('expiry_date[]')
                sizes = request.POST.getlist('size[]') 
                units = request.POST.getlist('unit[]')
                mrps = request.POST.getlist('mrp[]')
                
                # These fields from our new form:
                purchase_rates = request.POST.getlist('purchase_rate[]') # Pre-Tax
                selling_prices = request.POST.getlist('selling_price[]')
                margins = request.POST.getlist('margin[]')
                quantities = request.POST.getlist('qty[]')
                
                grand_total = 0
                
                for i in range(len(product_names)):
                    p_name = product_names[i]
                    if not p_name: continue
                    
                    product = Product.objects.get(name=p_name)
                    batch_no = batch_numbers[i]
                    mfg_date = mfg_dates[i] if mfg_dates[i] else None
                    expiry = expiry_dates[i] if expiry_dates[i] else None
                    
                    size = float(sizes[i]) if sizes[i] else 0
                    unit = units[i] if units[i] else 'kg'
                    
                    mrp = float(mrps[i]) if mrps[i] else 0
                    rate_pre_tax = float(purchase_rates[i]) if purchase_rates[i] else 0
                    qty = int(quantities[i]) if quantities[i] else 0
                    sell_price = float(selling_prices[i]) if selling_prices[i] else mrp
                    margin_val = float(margins[i]) if i < len(margins) and margins[i] else 0
                    
                    # Tax Calculation
                    tax_rate = float(product.category.total_tax)
                    tax_amount_per_unit = rate_pre_tax * (tax_rate / 100)
                    total_tax_amount = tax_amount_per_unit * qty
                    
                    net_cost_per_unit = rate_pre_tax + tax_amount_per_unit
                    total_line_amount = net_cost_per_unit * qty
                    
                    # Create Batch
                    batch, created = Batch.objects.get_or_create(
                        product=product,
                        batch_number=batch_no,
                        mrp=mrp,
                        defaults={
                            'manufacturing_date': mfg_date,
                            'expiry_date': expiry,
                            'purchase_price': net_cost_per_unit, 
                            'base_selling_price': sell_price,
                            'current_quantity': 0,
                            'size': size,
                            'unit': unit,
                            'is_active': True
                        }
                    )

                    if not created:
                        batch.manufacturing_date = mfg_date or batch.manufacturing_date
                        batch.expiry_date = expiry or batch.expiry_date
                        batch.size = size or batch.size
                        batch.unit = unit or batch.unit
                        batch.mrp = mrp or batch.mrp
                        batch.base_selling_price = sell_price or batch.base_selling_price
                        batch.purchase_price = net_cost_per_unit
                        batch.save()
                    
                    # Purchase Item
                    PurchaseItem.objects.create(
                        invoice=invoice,
                        batch=batch,
                        quantity=qty,
                        tax_amount=total_tax_amount,
                        basic_rate=rate_pre_tax,
                        selling_price=sell_price,
                        profit_margin=margin_val,
                        total_amount=total_line_amount
                    )
                    
                    grand_total += total_line_amount
                    

                
                invoice.total_amount = Decimal(str(grand_total + loading_charges - additional_discount))
                
                # Sprint 22: Payment Status Tracking
                payment_status = request.POST.get('payment_status', 'UNPAID')
                amount_paid = Decimal(request.POST.get('amount_paid') or 0)
                
                if payment_status == 'PAID':
                    amount_paid = invoice.total_amount
                    
                invoice.payment_status = payment_status
                invoice.amount_paid = amount_paid
                invoice.save()
                
                return redirect('purchase_list')

        except ValidationError as e:
            return render(request, 'transactions/purchase_form.html', {
                'suppliers': suppliers, 
                'categories': categories, 
                'manufacturers': manufacturers, 
                'error': e.message
            })
        except Exception as e:
            return render(request, 'transactions/purchase_form.html', {
                'suppliers': suppliers, 
                'categories': categories, 
                'manufacturers': manufacturers, 
                'error': str(e)
            })

    return render(request, 'transactions/purchase_form.html', {
        'suppliers': suppliers,
        'categories': categories,
        'manufacturers': manufacturers
    })


def returns_list(request):
    sales_returns = SalesReturn.objects.all().order_by('-date')
    purchase_returns = PurchaseReturn.objects.all().order_by('-date')
    return render(request, 'transactions/returns_list.html', {
        'sales_returns': sales_returns,
        'purchase_returns': purchase_returns
    })

def create_sales_return(request):
    # INWARD: Customer returns item to shop. Stock INCREASES.
    if request.method == 'POST':
        try:
            with transaction.atomic():
                customer_id = request.POST.get('customer')
                date = request.POST.get('date')
                customer = Customer.objects.get(id=customer_id)
                
                sales_return = SalesReturn.objects.create(
                    customer=customer,
                    date=date,
                    refund_amount=0
                )
                
                batch_ids = request.POST.getlist('batch_id[]')
                quantities = request.POST.getlist('qty[]')
                
                total_refund = 0
                
                for i in range(len(batch_ids)):
                    if not batch_ids[i] or not quantities[i]: continue
                    
                    batch = Batch.objects.get(id=batch_ids[i])
                    qty = int(quantities[i])
                    
                    # Refund amount calculation? 
                    # Prompt didn't specify input for refund price per item, but usually needed.
                    # Assuming price is derived or manually input?
                    # "Loop items and create SalesReturnItem" - Model has refund_amount? 
                    # No, SalesReturnItem just links batch/qty. SalesReturn has total refund_amount.
                    # Wait, let's check models. SalesReturnItem DOES NOT have price? 
                    # Let's check models. -> SalesReturnItem: quantity (only).
                    # SalesReturn: refund_amount.
                    # This implies distinct item prices are NOT tracked in SalesReturnItem? 
                    # Or maybe I should add it? Prompt says: "Create SalesReturnItem".
                    # Prompt for Template says: "Create sales_return_form... Clone sales_form... Visual Cue orange".
                    # Sales Form has Price. 
                    # Let's verify model schema for SalesReturnItem.
                    
                    # Checks model definition for SalesReturnItem:
                    # class SalesReturnItem(models.Model): ... quantity = models.IntegerField() ...
                    # It does NOT have price. This is a potential flaw in user design or simplified.
                    # However, SalesReturn (Header) has total_refund_amount.
                    # I will collect the total refund from the frontend "Grand Total" or sum of items?
                    # The form will surely have prices. I should probably add price to SalesReturnItem or just sum it up for the header.
                    # Given strict instructions "create SalesReturnItem", I'll stick to model.
                    # I will rely on the Form sending a total refund amount or sum it up.
                    # Actually, for accurate returns, we usually need per-item refund price.
                    # I will assume the form calculates total and we save that to Header.
                    
                    # BUT wait, PurchaseReturnItem HAS refund_price field in models.py (Viewed earlier).
                    # SalesReturnItem seemingly does not? Let me re-read models.py content I viewed.
                    # Line 101: class SalesReturnItem... batch, quantity. NO PRICE.
                    # Okay, so for Sales Return, we only track Qty coming back? And total money out?
                    # So I will calculate Total Refund from form data but not save per-item price.
                    
                    SalesReturnItem.objects.create(
                        return_invoice=sales_return,
                        batch=batch,
                        quantity=qty
                    )
                    
                    # We might want to capture the rate from the form to calc total, even if not saving to Item.
                    # Let's assume there is a price[] input in the form (Cloned from sales_form).
                    
                # We need to capture the total refund amount.
                # Since we don't store per-item price, we should probably ask for a "Total Refund" input 
                # OR sum up from hidden fields.
                # Let's sum up from form inputs "price[]" * "qty[]".
                prices = request.POST.getlist('price[]')
                grand_total = 0
                for i in range(len(batch_ids)):
                     if i < len(prices) and prices[i] and quantities[i]:
                         grand_total += float(prices[i]) * int(quantities[i])
                
                sales_return.refund_amount = grand_total
                sales_return.save()
                
                return redirect('returns_list')

        except Exception as e:
            customers = Customer.objects.all()
            batches = Batch.objects.filter(is_active=True, current_quantity__gt=0) 
            # Note: For returns, we might return items even if 0 stock? Yes.
            # But the dropdown usually shows batches.
            return render(request, 'transactions/sales_return_form.html', {'customers': customers, 'batches': batches, 'error': str(e)})

    # GET
    customers = Customer.objects.all()
    batches = Batch.objects.filter(is_active=True).select_related('product')
    return render(request, 'transactions/sales_return_form.html', {'customers': customers, 'batches': batches})

def create_purchase_return(request):
    # OUTWARD: Return to Supplier. Stock DECREASES.
    if request.method == 'POST':
        try:
            with transaction.atomic():
                supplier_id = request.POST.get('supplier')
                date = request.POST.get('date')
                reason = request.POST.get('reason')
                supplier = Supplier.objects.get(id=supplier_id)
                
                purchase_return = PurchaseReturn.objects.create(
                    supplier=supplier,
                    date=date,
                    reason=reason,
                    total_refund_amount=0
                )
                
                batch_ids = request.POST.getlist('batch_id[]')
                quantities = request.POST.getlist('qty[]')
                prices = request.POST.getlist('price[]') # Refund Price
                
                grand_total = 0
                
                for i in range(len(batch_ids)):
                    if not batch_ids[i] or not quantities[i]: continue
                    
                    batch_id = batch_ids[i]
                    qty = int(quantities[i])
                    price = float(prices[i]) if prices[i] else 0
                    
                    batch = Batch.objects.get(id=batch_id)
                    
                    # Validation: Cannot return more than we have
                    if qty > batch.current_quantity:
                        raise ValidationError(f"Cannot return {qty} of {batch}. Only {batch.current_quantity} in stock.")
                        
                    PurchaseReturnItem.objects.create(
                        return_invoice=purchase_return,
                        batch=batch,
                        quantity=qty,
                        refund_price=price
                    )
                    
                    grand_total += (price * qty)
                
                purchase_return.total_refund_amount = grand_total
                purchase_return.save()
                
                return redirect('returns_list')

        except ValidationError as e:
            suppliers = Supplier.objects.all()
            batches = Batch.objects.filter(is_active=True, current_quantity__gt=0)
            return render(request, 'transactions/purchase_return_form.html', {'suppliers': suppliers, 'batches': batches, 'error': e.message})
        except Exception as e:
            suppliers = Supplier.objects.all()
            batches = Batch.objects.filter(is_active=True, current_quantity__gt=0)
            return render(request, 'transactions/purchase_return_form.html', {'suppliers': suppliers, 'batches': batches, 'error': str(e)})

    # GET
    suppliers = Supplier.objects.all()
    batches = Batch.objects.filter(is_active=True, current_quantity__gt=0).select_related('product')
    return render(request, 'transactions/purchase_return_form.html', {'suppliers': suppliers, 'batches': batches})

@require_POST
def create_supplier(request):
    import json
    try:
        data = json.loads(request.body)
        name = data.get('name')
        
        if not name:
            return JsonResponse({'error': 'Name is required'}, status=400)
            
        supplier, created = Supplier.objects.get_or_create(
            name=name,
            defaults={
                'phone': data.get('phone', ''),
                'gstin': data.get('gstin', ''),
                'address': data.get('address', '')
            }
        )
        
        return JsonResponse({
            'success': True,
            'id': supplier.id,
            'name': supplier.name,
            'created': created
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)

@require_POST
def create_product(request):
    import json
    try:
        data = json.loads(request.body)
        name = data.get('name')
        category_id = data.get('category_id')
        manufacturer_id = data.get('manufacturer_id')
        
        if not name: return JsonResponse({'error': 'Name is required'}, status=400)
        if not category_id: return JsonResponse({'error': 'Category is required'}, status=400)
        if not manufacturer_id: return JsonResponse({'error': 'Manufacturer is required'}, status=400)
        
        product, created = Product.objects.get_or_create(
            name=name,
            defaults={
                'hsn_code': data.get('hsn_code', ''),
                'unit_type': data.get('unit_type', 'Kg'),
                'category_id': category_id,
                'manufacturer_id': manufacturer_id
            }
        )
        
        return JsonResponse({
            'success': True,
            'id': product.id,
            'name': product.name,
            'tax_rate': float(product.category.total_tax) if product.category else 0
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)
