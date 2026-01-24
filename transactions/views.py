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
from .models import SalesInvoice, SalesItem, PurchaseInvoice, PurchaseItem, PurchaseReturn, PurchaseReturnItem, SalesReturn, SalesReturnItem, SupplierPayment, CustomerPayment
from django.contrib import messages

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

def search_customers(request):
    query = request.GET.get('q', '')
    if query:
        customers = Customer.objects.filter(
            Q(name__icontains=query) | 
            Q(mobile_no__icontains=query)
        )[:20]
    else:
        customers = Customer.objects.all()[:20]
    
    data = [{
        'id': c.id,
        'name': c.name,
        'mobile_no': c.mobile_no,
        'city': c.city or ''
    } for c in customers]
    
    return JsonResponse(data, safe=False)

@csrf_exempt
def create_customer_ajax(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            name = data.get('name')
            mobile = data.get('mobile_no')
            city = data.get('city')
            
            if not name or not mobile:
                return JsonResponse({'error': 'Name and Mobile Number are required'}, status=400)
                
            customer = Customer.objects.create(
                name=name,
                mobile_no=mobile,
                city=city,
                address='' # Optional
            )
            
            return JsonResponse({
                'success': True,
                'id': customer.id,
                'name': customer.name,
                'mobile_no': customer.mobile_no,
                'city': customer.city
            })
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)
    return JsonResponse({'error': 'Invalid method'}, status=405)

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

def get_product_sizes(request):
    product_id = request.GET.get('product_id')
    if not product_id:
        return JsonResponse([], safe=False)
    
    # Get distinct active sizes/units with valid stock
    batches = Batch.objects.filter(
        product_id=product_id, 
        is_active=True, 
        current_quantity__gt=0,
        expiry_date__gt=timezone.now().date()
    ).values('size', 'unit').distinct()
    
    data = [{
        'size': float(b['size']),
        'unit': b['unit'],
        'label': f"{float(b['size'])} {b['unit']}"
    } for b in batches]
    
    return JsonResponse(data, safe=False)

def get_batches_for_product(request):
    product_id = request.GET.get('product_id')
    
    if not product_id:
        return JsonResponse([], safe=False)
    
    filters = {
        'product_id': product_id,
        'is_active': True,
        'current_quantity__gt': 0,
        'expiry_date__gt': timezone.now().date()
    }
    
    # Optional Size/Unit filters
    size = request.GET.get('size')
    unit = request.GET.get('unit')
    
    if size:
        filters['size'] = size
    if unit:
        filters['unit'] = unit
    
    batches = Batch.objects.filter(**filters).order_by('expiry_date')
    
    data = [{
        'id': b.id,
        'batch_number': b.batch_number,
        'quantity': b.current_quantity,
        'price': float(b.base_selling_price) if b.base_selling_price else 0,
        'cost': float(b.purchase_price) if b.purchase_price else 0,
        'manufacturing_date': b.manufacturing_date,
        'expiry_date': b.expiry_date
    } for b in batches]
    
    return JsonResponse(data, safe=False)

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
                    
                    # Calculations (Sprint 45: Back-calculate tax from Total)
                    # Input Price is Final Selling Price (Tax Inclusive)
                    total = price * qty
                    tax_rate = batch.product.category.total_tax
                    tax_rate_float = float(tax_rate)
                    
                    # Back Calculate Tax
                    # Total = Taxable * (1 + Rate/100)
                    # Taxable = Total / (1 + Rate/100)
                    taxable_value = total / (1 + (tax_rate_float / 100))
                    tax_amount = total - taxable_value
                    
                    # Create Item (Signals will handle stock deduction)
                    item = SalesItem(
                        invoice=invoice,
                        batch=batch,
                        quantity=qty,
                        unit_price=price, # Storing Tax-Inclusive Price
                        tax_rate=tax_rate,
                        tax_amount=tax_amount,
                        total_amount=total
                    )
                    # Run validation (checks stock)
                    item.clean()
                    item.save()
                    
                    total_taxable += taxable_value
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
                
                # Sprint 40: Payment Status Tracking
                # Logic: Create CustomerPayment which triggers signal update_sales_invoice_payment_status
                payment_status = request.POST.get('payment_status', 'UNPAID')
                amount_rec_str = request.POST.get('amount_received')
                
                payment_amount = Decimal('0.00')
                
                if payment_status == 'PAID':
                     payment_amount = invoice.grand_total
                elif payment_status == 'PARTIAL' and amount_rec_str:
                     payment_amount = Decimal(amount_rec_str)
                
                if payment_amount > 0:
                    CustomerPayment.objects.create(
                        invoice=invoice,
                        amount=payment_amount,
                        payment_date=invoice.date, # Assume payment on same date
                        payment_mode='CASH', # Default for quick sale
                        notes='Initial Payment via Sales Form'
                    )
                
                return redirect('dashboard')
                
        except ValidationError as e:
            customers = Customer.objects.all()
            return render(request, 'transactions/sales_form_v2.html', {'customers': customers, 'error': e.message})
        except Exception as e:
            customers = Customer.objects.all()
            return render(request, 'transactions/sales_form_v2.html', {'customers': customers, 'error': str(e)})

    # GET Request
    customers = Customer.objects.all()
    # Batches for dropdown (Active and > 0 stock)
    batches = Batch.objects.filter(is_active=True, current_quantity__gt=0).select_related('product')
    return render(request, 'transactions/sales_form_v2.html', {'customers': customers, 'batches': batches})

def sales_list(request):
    invoices_list = SalesInvoice.objects.select_related('customer').all().order_by('-date', '-id')
    
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

@transaction.atomic
def delete_invoice(request, pk):
    invoice = get_object_or_404(SalesInvoice, pk=pk)
    
    # Refund Wallet Payments (only positive amounts, reversals are negative)
    for payment in invoice.payments.filter(amount__gt=0):
        if payment.payment_mode == 'WALLET':
            if invoice.customer:
                invoice.customer.wallet_balance += payment.amount
                invoice.customer.save()
                print(f"Refunded {payment.amount} to Wallet for Invoice #{invoice.pk}")
    
    # Delete payments in correct order to respect reversal_of FK constraint
    # First: Delete reversal entries (those that have reversal_of set)
    invoice.payments.filter(reversal_of__isnull=False).delete()
    # Then: Delete original payments
    invoice.payments.all().delete()
    
    # Delete the invoice
    invoice.delete()
    
    messages.success(request, "Invoice deleted and wallet refunded if applicable.")
    return redirect('sales_list')

def edit_sale(request, pk):
    """Edit an existing sales invoice - follows purchase_edit pattern."""
    invoice = get_object_or_404(SalesInvoice, pk=pk)
    customers = Customer.objects.all()
    
    # Build existing items for pre-population
    existing_items = []
    for item in invoice.items.select_related('batch__product'):
        size_val = item.batch.size if item.batch.size else ''
        unit_val = item.batch.unit or ''
        existing_items.append({
            'id': item.id,
            'batch_id': item.batch.id,
            'product_id': item.batch.product.id,
            'product_name': item.batch.product.name,
            'batch_number': item.batch.batch_number,
            'size': str(size_val),
            'unit': unit_val,
            'size_label': f"{size_val} {unit_val}" if size_val else '',
            'mfg_date': str(item.batch.manufacturing_date) if item.batch.manufacturing_date else '',
            'expiry_date': str(item.batch.expiry_date) if item.batch.expiry_date else '',
            'current_stock': item.batch.current_quantity + item.quantity,  # Add back this item's qty  
            'qty': item.quantity,
            'price': float(item.unit_price),
            'tax_rate': float(item.tax_rate),
            'tax_amount': float(item.tax_amount),
            'total': float(item.total_amount)
        })
    
    if request.method == 'POST':
        try:
            with transaction.atomic():
                customer_id = request.POST.get('customer')
                date = request.POST.get('date')
                
                customer = Customer.objects.get(id=customer_id) if customer_id else None
                
                # Restore stock from old items before deleting
                for item in invoice.items.all():
                    item.batch.current_quantity += item.quantity
                    item.batch.save()
                    item.delete()
                
                # Update invoice header
                invoice.customer = customer
                invoice.date = date
                
                # Process new items
                batch_ids = request.POST.getlist('batch_id[]')
                quantities = request.POST.getlist('qty[]')
                prices = request.POST.getlist('price[]')
                
                total_taxable = 0
                total_cgst = 0
                total_sgst = 0
                grand_total = 0
                
                for i in range(len(batch_ids)):
                    batch_id = batch_ids[i]
                    qty = int(quantities[i]) if quantities[i] else 0
                    price = float(prices[i]) if prices[i] else 0
                    
                    if not batch_id or qty <= 0:
                        continue
                        
                    batch = Batch.objects.get(id=batch_id)
                    
                    # Calculations (Sprint 45: Back-calculate tax from Total)
                    total = price * qty
                    tax_rate = batch.product.category.total_tax
                    tax_rate_float = float(tax_rate)
                    
                    # Back Calculate Tax
                    taxable_value = total / (1 + (tax_rate_float / 100))
                    tax_amount = total - taxable_value
                    
                    # Create Item
                    item = SalesItem(
                        invoice=invoice,
                        batch=batch,
                        quantity=qty,
                        unit_price=price, # Storing Tax-Inclusive Price
                        tax_rate=tax_rate,
                        tax_amount=tax_amount,
                        total_amount=total
                    )
                    item.clean()  # Validate stock
                    item.save()
                    
                    # Stock deducted by signal
                    
                    total_taxable += taxable_value
                    total_cgst += tax_amount / 2
                    total_sgst += tax_amount / 2
                    grand_total += total
                
                # Update Invoice Totals
                invoice.total_taxable = total_taxable
                invoice.total_cgst = total_cgst
                invoice.total_sgst = total_sgst
                invoice.grand_total = grand_total
                invoice.save()
                
                # Sprint 22: Payment Status Tracking for Edit
                # Logic: Create CustomerPayment which triggers signal update_sales_invoice_payment_status
                payment_status = request.POST.get('payment_status', 'UNPAID')
                amount_rec_str = request.POST.get('amount_received')
                
                # We need to handle the incremental payment
                # If user says "PAID", they want to pay the *remaining* balance.
                # If "PARTIAL", they are paying a specific amount *now*.
                
                payment_amount_to_record = Decimal('0.00')
                
                # Current status (before this edit's payment)
                # invoice.amount_received is already up to date from previous payments
                
                if payment_status == 'PAID':
                     # Pay off the entire remaining balance
                     # Balance Due = Grand Total - Amount Received
                     payment_amount_to_record = invoice.grand_total - invoice.amount_received
                     if payment_amount_to_record < 0: payment_amount_to_record = 0
                     
                elif payment_status == 'PARTIAL' and amount_rec_str:
                     # This is the *new* payment amount being added, NOT the total paid
                     # But wait, the UI usually shows "Amount Received" as the *current transaction's* payment in POS
                     # Let's assume the input is the "amount being paid right now".
                     payment_amount_to_record = Decimal(amount_rec_str)
                
                if payment_amount_to_record > 0:
                    CustomerPayment.objects.create(
                        invoice=invoice,
                        amount=payment_amount_to_record,
                        payment_date=invoice.date, # Assume payment on same date
                        payment_mode='CASH', # Default for quick sale
                        notes='Additional Payment via Sales Edit'
                    )
                
                return redirect('invoice_detail', pk=invoice.pk)
                
        except ValidationError as e:
            return render(request, 'transactions/sales_form_v2.html', {
                'invoice': invoice,
                'customers': customers,
                'existing_items': existing_items,
                'existing_items_json': json.dumps(existing_items),
                'error': e.message
            })
        except Exception as e:
            return render(request, 'transactions/sales_form_v2.html', {
                'invoice': invoice,
                'customers': customers,
                'existing_items': existing_items,
                'existing_items_json': json.dumps(existing_items),
                'error': str(e)
            })
    
    # GET: Render form with pre-populated data
    batches = Batch.objects.filter(is_active=True, current_quantity__gt=0).select_related('product')
    return render(request, 'transactions/sales_form_v2.html', {
        'invoice': invoice,
        'customers': customers,
        'batches': batches,
        'existing_items': existing_items,
        'existing_items_json': json.dumps(existing_items),
        'amount_paid': float(invoice.amount_received)
    })

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
    
    # Sprint 49: Universal Zero-Negative Safeguard
    if amount <= 0:
         return JsonResponse({'success': False, 'error': 'Payment must be positive.'}, status=400)

    # Sprint 48: Strict Payment Validation for Suppliers
    if amount > invoice.balance_due:
        return JsonResponse({'success': False, 'error': f'Payment amount (₹{amount}) cannot exceed balance due (₹{invoice.balance_due}).'}, status=400)
    
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


def get_customer_invoices(request):
    customer_id = request.GET.get('customer_id')
    if not customer_id:
        if request.GET.get('format') == 'json':
            return JsonResponse([], safe=False)
        return HttpResponse("")
    
    invoices = SalesInvoice.objects.filter(
        customer_id=customer_id, 
        payment_status__in=['PAID', 'PARTIAL', 'UNPAID']
    ).order_by('-date')
    
    if request.GET.get('format') == 'json':
        query = request.GET.get('q', '')
        if query:
            invoices = invoices.filter(
                Q(invoice_number__icontains=query) | 
                Q(grand_total__icontains=query)
            )
            
        # Limit results for performance
        invoices = invoices[:20]
        
        data = [{
            'id': inv.id,
            'invoice_number': inv.invoice_number,
            'date': inv.date.strftime('%Y-%m-%d'),
            'grand_total': float(inv.grand_total)
        } for inv in invoices]
        return JsonResponse(data, safe=False)
    
    options = '<option value="">-- Select Invoice --</option>'
    for inv in invoices:
        options += f'<option value="{inv.id}">#{inv.invoice_number} ({inv.date}) - ₹{inv.grand_total}</option>'
        
    return HttpResponse(options)

def get_invoice_items(request):
    invoice_id = request.GET.get('invoice_id')
    if not invoice_id:
        return JsonResponse([], safe=False)
        
    invoice = get_object_or_404(SalesInvoice, pk=invoice_id)
    items_data = []
    
    for item in invoice.items.select_related('batch', 'batch__product').all():
        already_returned = SalesReturnItem.objects.filter(
            return_invoice__original_sale=invoice, 
            batch=item.batch
        ).aggregate(Sum('quantity'))['quantity__sum'] or 0
        
        max_returnable = item.quantity - already_returned
        
        if max_returnable > 0:
            items_data.append({
                'id': item.id, 
                'product_name': item.batch.product.name,
                'batch_id': item.batch.id,
                'batch_number': item.batch.batch_number,
                'qty_sold': item.quantity,
                'qty_returned_already': already_returned,
                'max_returnable': max_returnable,
                'price': float(item.unit_price),
                'price': float(item.unit_price),
                'unit': item.batch.unit,
                'size': float(item.batch.size),
                'mfg_date': item.batch.manufacturing_date.strftime('%d-%m-%Y') if item.batch.manufacturing_date else '-',
                'exp_date': item.batch.expiry_date.strftime('%d-%m-%Y') if item.batch.expiry_date else '-'
            })
            
    return JsonResponse(items_data, safe=False)

def returns_list(request):
    sales_returns = SalesReturn.objects.all().order_by('-date')
    purchase_returns = PurchaseReturn.objects.all().order_by('-date')
    
    total_sales_refunds = sales_returns.aggregate(Sum('refund_amount'))['refund_amount__sum'] or 0
    total_purchase_refunds = purchase_returns.aggregate(Sum('total_refund_amount'))['total_refund_amount__sum'] or 0
    
    return render(request, 'transactions/returns_list.html', {
        'sales_returns': sales_returns,
        'purchase_returns': purchase_returns,
        'total_sales_refunds': total_sales_refunds,
        'total_purchase_refunds': total_purchase_refunds
    })

def create_sales_return(request):
    # INWARD: Customer returns item to shop. Stock INCREASES.
    print("DEBUG: create_sales_return called")
    print(f"DEBUG: request.method = {request.method}")
    
    if request.method == 'POST':
        print("DEBUG: Processing POST request")
        print(f"DEBUG: POST data keys = {list(request.POST.keys())}")
        
        try:
            with transaction.atomic():
                customer_id = request.POST.get('customer')
                date = request.POST.get('date')
                original_sale_id = request.POST.get('original_sale')
                
                print(f"DEBUG: customer_id={customer_id}, date={date}, original_sale_id={original_sale_id}")
                
                if not customer_id:
                    raise ValueError("Customer ID is required")
                    
                customer = Customer.objects.get(id=customer_id)
                print(f"DEBUG: Found customer: {customer}")
                
                # Get original sale if provided
                original_sale = None
                if original_sale_id:
                    original_sale = SalesInvoice.objects.get(id=original_sale_id)
                    print(f"DEBUG: Found original_sale: {original_sale}")
                
                sales_return = SalesReturn.objects.create(
                    customer=customer,
                    original_sale=original_sale,
                    date=date,
                    refund_amount=0
                )
                print(f"DEBUG: Created SalesReturn pk={sales_return.pk}")
                
                batch_ids = request.POST.getlist('batch_id[]')
                quantities = request.POST.getlist('qty[]')
                prices = request.POST.getlist('price[]')
                
                print(f"DEBUG: batch_ids={batch_ids}")
                print(f"DEBUG: quantities={quantities}")
                print(f"DEBUG: prices={prices}")
                
                grand_total = Decimal('0')
                items_created = 0
                
                for i in range(len(batch_ids)):
                    batch_id = batch_ids[i] if i < len(batch_ids) else ''
                    qty_str = quantities[i] if i < len(quantities) else ''
                    price_str = prices[i] if i < len(prices) else ''
                    
                    print(f"DEBUG: Processing row {i}: batch_id={batch_id}, qty={qty_str}, price={price_str}")
                    
                    if not batch_id or not qty_str:
                        print(f"DEBUG: Skipping row {i} - empty batch_id or qty")
                        continue
                    
                    batch = Batch.objects.get(id=batch_id)
                    qty = int(qty_str)
                    price = Decimal(price_str) if price_str else Decimal('0')
                    # price already set above as Decimal
                    
                    print(f"DEBUG: Creating SalesReturnItem for batch={batch}, qty={qty}")
                    
                    SalesReturnItem.objects.create(
                        return_invoice=sales_return,
                        batch=batch,
                        quantity=qty
                    )
                    items_created += 1
                    
                    # INWARD Stock Adjustment
                    batch.current_quantity += qty
                    batch.save()
                    print(f"DEBUG: Updated batch stock: {batch.current_quantity}")
                    
                    grand_total += price * qty
                    
                print(f"DEBUG: Items created: {items_created}, grand_total: {grand_total}")
                
                sales_return.refund_amount = grand_total
                sales_return.save()
                print(f"DEBUG: Updated SalesReturn refund_amount to {grand_total}")
                
                # Sprint 59: Targeted Return Settlement
                # If return is linked to an invoice, apply credit directly to that invoice.
                # Otherwise, give generic wallet credit.
                target_invoice = sales_return.original_sale
                payment_mode = 'SALES_RETURN' if target_invoice else 'WALLET_CREDIT'
                
                print(f"DEBUG: Creating CustomerPayment with amount={grand_total}, invoice={target_invoice}, mode={payment_mode}")
                
                cp = CustomerPayment.objects.create(
                    invoice=target_invoice, 
                    amount=grand_total,
                    payment_mode=payment_mode,
                    payment_date=date,
                    notes=f"Return Adjustment #{sales_return.pk}" if target_invoice else f"Auto-credit for Return #{sales_return.pk}",
                    sales_return=sales_return
                )
                print(f"DEBUG: Created CustomerPayment pk={cp.pk}")
                
                messages.success(request, f"Sales return created successfully. Refund: ₹{grand_total}")
                print("DEBUG: SUCCESS - Redirecting to returns_list")
                return redirect('returns_list')

        except Exception as e:
            import traceback
            print(f"ERROR creating return: {e}")
            print(f"TRACEBACK: {traceback.format_exc()}")
            messages.error(request, f"Error creating return: {str(e)}")
            return redirect('returns_list')
            
    return render(request, 'transactions/sales_return_form.html')

def sales_return_detail(request, pk):
    sales_return = get_object_or_404(SalesReturn, pk=pk)
    return render(request, 'transactions/sales_return_detail.html', {
        'return': sales_return
    })

@require_POST
def delete_sales_return(request, pk):
    sales_return = get_object_or_404(SalesReturn, pk=pk)
    try:
        with transaction.atomic():
            # 1. Reverse Inventory Impact (Stock Deduction)
            # When return was created: Stock += Qty
            # Now deleting return: Stock -= Qty
            for item in sales_return.items.all():
                batch = item.batch
                # Ensure we don't go negative if stock was already consumed (Edge case)
                # But physically, if we undo a return, the stock should leave.
                batch.current_quantity -= item.quantity
                batch.save()
            
            # 2. Reverse Financial Impact (Wallet Debit)
            # When return was created: Wallet += Amount (Credit)
            # Now deleting return: Deleting the payment entry will trigger the signal to reverse it.
            # Signal: post_delete on CustomerPayment -> if WALLET_CREDIT -> Wallet -= Amount.
            if hasattr(sales_return, 'payment_entry') and sales_return.payment_entry:
                sales_return.payment_entry.delete()
                
            # 3. Delete the Return Record
            sales_return.delete()
            
            messages.success(request, "Sales return deleted successfully. Stock deducted and wallet reversed.")
            return redirect('returns_list')
            
    except Exception as e:
        print(f"Error deleting return: {e}")
        messages.error(request, f"Error deleting return: {str(e)}")
        return redirect('sales_return_detail', pk=pk)

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
                    
                    # FIX: Deduct Stock
                    batch.current_quantity -= qty
                    batch.save()
                    
                    PurchaseReturnItem.objects.create(
                        return_invoice=purchase_return,
                        batch=batch,
                        quantity=qty,
                        refund_price=price
                    )
                    
                    grand_total += (price * qty)
                
                purchase_return.total_refund_amount = grand_total
                purchase_return.save()
                
                # FIX: Create Debit Note (SupplierPayment)
                if grand_total > 0:
                    SupplierPayment.objects.create(
                        invoice=purchase_return.original_invoice, # Can be None now
                        amount=grand_total,
                        payment_mode='DEBIT_NOTE', # Technically 'DEBIT_NOTE' is not in CHOICES yet?
                        # User Prompt: payment_mode: 'DEBIT_NOTE'
                        # I should check logic or CHOICES.
                        # SupplierPayment.PAYMENT_MODE_CHOICES doesn't have DEBIT_NOTE.
                        # I should add it to CHOICES in models.py as well.
                        purchase_return=purchase_return,
                        notes=f"Auto-debit for Return #{purchase_return.pk}"
                    )
                
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

def purchase_return_detail(request, pk):
    purchase_return = get_object_or_404(PurchaseReturn, pk=pk)
    return render(request, 'transactions/purchase_return_detail.html', {
        'return': purchase_return
    })

@require_POST
def delete_purchase_return(request, pk):
    purchase_return = get_object_or_404(PurchaseReturn, pk=pk)
    
    try:
        with transaction.atomic():
            # 1. Reverse Inventory (Stock Restoration)
            # When created: Stock decreased.
            # Now deleting: Stock must increase.
            for item in purchase_return.items.all():
                batch = item.batch
                batch.current_quantity += item.quantity
                batch.save()
            
            # 2. Reverse Finance (Delete Debit Note)
            if hasattr(purchase_return, 'payment_entry') and purchase_return.payment_entry:
                purchase_return.payment_entry.delete()
                
            # 3. Delete Record
            purchase_return.delete()
            
            messages.success(request, "Supplier return deleted. Stock restored and debit note removed.")
            return redirect('returns_list')
            
    except Exception as e:
        messages.error(request, f"Error deleting return: {str(e)}")
        return redirect('purchase_return_detail', pk=pk)

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

# Sprint 40: Customer Payments
def record_receipt(request, pk):
    invoice = get_object_or_404(SalesInvoice, pk=pk)
    if request.method == 'POST':
        try:
            amount = Decimal(request.POST.get('amount'))
            payment_mode = request.POST.get('payment_mode')
            payment_date = request.POST.get('payment_date') or timezone.now().date()
            notes = request.POST.get('notes')

            # Sprint 49: Universal Zero-Negative Safeguard
            if amount <= 0:
                 return JsonResponse({'success': False, 'error': 'Payment must be positive.'}, status=400)
            
            # Sprint 47: Smart Overpayment Handling
            excess_amount = amount - invoice.balance_due
            payment_amount = amount

            if excess_amount > 0:
                payment_amount = invoice.balance_due
                # Credit excess to wallet
                if invoice.customer:
                    customer = invoice.customer
                    customer.wallet_balance += excess_amount
                    customer.save()
                    notes = f"{notes} (Overpayment of ₹{excess_amount} added to Wallet)" if notes else f"(Overpayment of ₹{excess_amount} added to Wallet)"
            
            CustomerPayment.objects.create(
                invoice=invoice,
                amount=payment_amount,
                payment_mode=payment_mode,
                payment_date=payment_date,
                notes=notes
            )
            messages.success(request, f"Receipt of ₹{amount} recorded successfully.")
        except Exception as e:
            messages.error(request, f"Error recording receipt: {str(e)}")
            
    return redirect('invoice_detail', pk=pk)

@csrf_exempt
@require_POST
def delete_customer_payment(request, pk):
    from django.db.models import ProtectedError
    
    payment = get_object_or_404(CustomerPayment, pk=pk)
    invoice_pk = payment.invoice.pk
    
    try:
        payment.delete()
        messages.success(request, "Payment deleted successfully.")
    except ProtectedError:
        messages.error(request, "Cannot delete this payment because it has been reversed. Please delete the Reversal entry first.")
        
    return redirect('invoice_detail', pk=invoice_pk)

def customer_ledger(request):
    """
    Sprint 44: Customer Ledger Dashboard with Search
    Sprint 46: Added collected_this_month and recent_receipts for parity with Payables.
    Shows net position (Wallet vs Unpaid Invoices) for customers.
    """
    from django.db.models import Prefetch, Value, DecimalField
    from django.db.models.functions import Coalesce

    now = timezone.now()
    q = request.GET.get('q', '').strip()
    
    # Prefetch only UNPAID/PARTIAL invoices
    unpaid_invoices_pref = Prefetch(
        'salesinvoice_set',
        queryset=SalesInvoice.objects.filter(payment_status__in=['UNPAID', 'PARTIAL']).order_by('date'),
        to_attr='unpaid_invoices'
    )

    # Base query with annotations
    customers = Customer.objects.annotate(
        total_due=Coalesce(
            Sum('salesinvoice__balance_due', filter=Q(salesinvoice__payment_status__in=['UNPAID', 'PARTIAL'])), 
            Value(Decimal('0')), 
            output_field=DecimalField()
        ),
    ).annotate(
        net_position=ExpressionWrapper(F('wallet_balance') - F('total_due'), output_field=DecimalField())
    )
    
    # Filtering logic
    if q:
        # Search: Show all matching customers including zero-balance
        customers = customers.filter(
            Q(name__icontains=q) | Q(mobile_no__icontains=q)
        )
    else:
        # Default: Only show customers with active balance
        customers = customers.filter(
            Q(total_due__gt=0) | Q(wallet_balance__gt=0)
        )
    
    customers = customers.prefetch_related(unpaid_invoices_pref).order_by('-total_due')

    # Market Stats (only for non-search view)
    if not q:
        market_outstanding = customers.aggregate(Sum('total_due'))['total_due__sum'] or 0
        total_advances = customers.aggregate(Sum('wallet_balance'))['wallet_balance__sum'] or 0
    else:
        market_outstanding = 0
        total_advances = 0
    
    # Sprint 46: Collection KPIs
    # Collected this month (exclude WALLET - only real cash/UPI flow)
    collected_this_month = CustomerPayment.objects.filter(
        payment_date__year=now.year,
        payment_date__month=now.month
    ).exclude(payment_mode='WALLET').aggregate(Sum('amount'))['amount__sum'] or 0
    
    # Recent receipts for activity timeline (last 10)
    recent_receipts = CustomerPayment.objects.select_related(
        'invoice', 'invoice__customer'
    ).order_by('-created_at')[:10]
    
    context = {
        'customers': customers,
        'market_outstanding': market_outstanding,
        'total_advances': total_advances,
        'collected_this_month': collected_this_month,
        'recent_receipts': recent_receipts,
        'q': q,
        'is_search_result': bool(q),
    }
    
    # HTMX partial response
    if request.headers.get('HX-Request'):
        return render(request, 'transactions/partials/receivables_customer_list.html', context)
    
    return render(request, 'transactions/receivables_dashboard.html', context)

@csrf_exempt
@require_POST
def settle_invoice_via_wallet(request, invoice_id):
    invoice = get_object_or_404(SalesInvoice, pk=invoice_id)
    customer = invoice.customer
    
    if not customer:
        messages.error(request, "Invoice has no customer.")
        return redirect('customer_ledger')

    # Calculate max possible payment
    amount_to_pay = min(invoice.balance_due, customer.wallet_balance)
    
    if amount_to_pay > 0:
        # Create Payment (Signal handles logic: Deduct Wallet, Mark Invoice Paid)
        CustomerPayment.objects.create(
            invoice=invoice,
            amount=amount_to_pay,
            payment_mode='WALLET', 
            notes='Settled via One-Click Dashboard'
        )
        messages.success(request, f"Settled \u20B9{amount_to_pay} for #{invoice.invoice_number}")
    else:
        messages.error(request, "Insufficient wallet balance or invoice already paid.")
        
    return redirect('customer_ledger')


def customer_statement_view(request, pk):
    """
    Sprint 54: Unified Customer Account Statement (Khata)
    Sprint 54 Fix: Removed SalesReturn (double-counting), fixed WALLET handling.
    
    Accounting Logic (must match Dashboard):
    - Net Position = wallet_balance - total_due
    - total_due = Sum of balance_due from UNPAID/PARTIAL invoices
    
    Statement shows transaction history but final balance must match net_position.
    WALLET mode payments = internal allocation (no debt change).
    """
    from datetime import datetime
    
    customer = get_object_or_404(Customer, pk=pk)
    
    # Build unified transaction list
    all_transactions = []
    
    # 1. Invoices (Debit - Customer owes more)
    for inv in SalesInvoice.objects.filter(customer=customer).order_by('date'):
        all_transactions.append({
            'obj': inv,
            'date': inv.date,
            'created_at': inv.date,
            'txn_type': 'Invoice',
            'particulars': f"Invoice #{inv.invoice_number}",
            'amount': inv.grand_total,
            'is_debit': True,
            'is_reversal': False,
            'is_wallet_allocation': False,
            'payment_id': None,
            'can_reverse': False,
            'payment_mode': None
        })
    
    # 2. Payments (Credit - Customer debt reduces, EXCEPT for WALLET mode)
    # Sprint 54 Fix: Include ALL payments for this customer (via invoice)
    # Sprint 57 Fix: Include payments via Invoice AND Sales Returns (Wallet Credit)
    for pmt in CustomerPayment.objects.filter(
        Q(invoice__customer=customer) | Q(sales_return__customer=customer)
    ).select_related('invoice', 'sales_return').order_by('created_at'):
        is_reversal = pmt.amount < 0 or pmt.reversal_of is not None
        pmt_mode = pmt.payment_mode
        pmt_mode_display = pmt.get_payment_mode_display()
        
        # WALLET mode = internal allocation (funds move from wallet to invoice)
        # This does NOT reduce net debt - it's just allocation of existing credit
        is_wallet_allocation = (pmt_mode == 'WALLET') and not is_reversal
        
        if is_reversal:
            particulars = f"Reversal ({pmt_mode_display})"
        elif hasattr(pmt, 'sales_return') and pmt.sales_return:
             particulars = f"Sales Return #{pmt.sales_return.pk}"
        elif is_wallet_allocation:
           if pmt.notes and "Auto-credit" in pmt.notes:
             particulars = pmt.notes
           else:
             particulars = f"Wallet → Invoice #{pmt.invoice.invoice_number}"
        elif pmt.payment_mode == 'SALES_RETURN' and pmt.invoice:
             particulars = f"Return Adjustment (Inv #{pmt.invoice.invoice_number})"
        elif pmt.invoice:
             particulars = f"Payment ({pmt_mode_display}) - #{pmt.invoice.invoice_number}"
        else:
             particulars = f"Payment ({pmt_mode_display}) - General"
        
        # Determine debit/credit:
        # - Reversals = debit (debt increases back)
        # - Wallet allocations = neither (internal movement, but show as credit for visibility)
        # - Regular payments = credit (debt decreases)
        
        all_transactions.append({
            'obj': pmt,
            'date': pmt.payment_date,
            'created_at': pmt.created_at,
            'txn_type': 'Payment',
            'particulars': particulars,
            'amount': abs(pmt.amount),
            'is_debit': is_reversal,
            'is_reversal': is_reversal,
            'is_wallet_allocation': is_wallet_allocation,
            'is_sales_return': bool(hasattr(pmt, 'sales_return') and pmt.sales_return),
            'payment_id': pmt.id,
            'can_reverse': not is_reversal and not hasattr(pmt, 'reversal_entry'),
            'payment_mode': pmt_mode
        })
    
    # NOTE: SalesReturn query REMOVED - Sprint 54 Fix
    # Returns create WALLET_CREDIT payments which are already captured above.
    # Adding SalesReturn separately = double-counting bug.
    
    # Sort by date, then by created_at for same-day ordering
    def get_sort_key(x):
        sort_date = x['date']
        sort_time = x['created_at']
        if isinstance(sort_time, datetime):
            return (sort_date, sort_time)
        else:
            naive_dt = datetime.combine(sort_time, datetime.min.time())
            aware_dt = timezone.make_aware(naive_dt, timezone.get_default_timezone())
            return (sort_date, aware_dt)
    
    all_transactions.sort(key=get_sort_key)
    
    # Calculate Running Balance
    # Convention: Positive balance = Customer OWES us (debit balance)
    #             Negative balance = We OWE customer (credit balance / wallet surplus)
    balance = Decimal('0.00')
    
    for txn in all_transactions:
        # Only change balance for real money movement, not internal allocations
        if txn['is_wallet_allocation']:
            # Wallet usage = internal allocation, no net change
            # But we still show it in Credit column for visibility
            pass  # Balance stays the same
        elif txn['is_debit']:
            # Invoice or Reversal - debt increases
            balance += txn['amount']
        else:
            # Regular Payment (CASH, UPI, WALLET_CREDIT, REFUND) - debt decreases
            balance -= txn['amount']
        
        txn['running_balance'] = balance
    
    # Net balance for header display (MUST match Dashboard's net_position)
    # Dashboard formula: net_position = wallet_balance - total_due
    # total_due = Sum of balance_due from UNPAID/PARTIAL invoices
    total_due = SalesInvoice.objects.filter(
        customer=customer,
        payment_status__in=['UNPAID', 'PARTIAL']
    ).aggregate(total=Sum('balance_due'))['total'] or Decimal('0')
    
    net_balance = customer.wallet_balance - total_due
    
    return render(request, 'transactions/customer_statement.html', {
        'customer': customer,
        'transactions': all_transactions,
        'net_balance': net_balance,
        'wallet_balance': customer.wallet_balance,
        'total_due': total_due
    })

@csrf_exempt
@require_POST
def reverse_wallet_transaction(request, payment_id):
    """
    Sprint 51: Reverse a wallet transaction.
    Sprint 54: Uses reversal_of FK for strict double-reversal prevention.
    Creates a counter-entry (Negative Amount) to void a mistake.
    """
    original = get_object_or_404(CustomerPayment, pk=payment_id)
    
    # Sprint 54: Check via OneToOneField relationship instead of notes pattern
    # If original already has a reversal_entry, it has been reversed before
    if hasattr(original, 'reversal_entry'):
        return JsonResponse({'success': False, 'error': 'Transaction already reversed.'}, status=400)

    # Sprint 60: Statement Integrity Lock
    # Prevent users from voiding a Return Credit directly. They must delete the Sales Return record.
    if hasattr(original, 'sales_return') and original.sales_return:
        return JsonResponse({'success': False, 'error': 'Cannot reverse a Return Credit directly. Please delete the Sales Return record.'}, status=400)

    # Also check if this payment IS a reversal itself (can't reverse a reversal)
    if original.reversal_of is not None:
        return JsonResponse({'success': False, 'error': 'Cannot reverse a reversal entry.'}, status=400)

    # Logic: Create Counter-Entry (Sprint 53: Inverse Reversal)
    # Keep Mode (e.g. WALLET), but use Negative Amount.
    # Effect: Invoice Sum(500, -500) = 0. Invoice Reverts to Unpaid.
    # Wallet Signal: balance -= -500 => balance += 500. Restored.
    
    reverse_amount = -original.amount
    new_mode = original.payment_mode
    
    CustomerPayment.objects.create(
        invoice=original.invoice, 
        amount=reverse_amount,
        payment_mode=new_mode,
        payment_date=timezone.now(),
        notes=f"Reversal of #{original.id} - {original.notes}",
        reversal_of=original  # Sprint 54: Link to original payment via FK
    )
    
    return JsonResponse({'success': True})
