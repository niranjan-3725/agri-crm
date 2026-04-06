from django.shortcuts import render
from django.http import HttpResponse
from django.db.models import Q, Count, Sum
from django.urls import reverse_lazy
from django.views.generic import ListView, CreateView, UpdateView, DeleteView
from django.utils import timezone
import csv
import json
from django.http import JsonResponse
from .models import Customer, Supplier, Village
from .forms import CustomerForm, SupplierForm
from transactions.models import PurchaseInvoice

# --- Customer Views ---

class CustomerListView(ListView):
    model = Customer
    template_name = 'master_data/customer_list.html'
    context_object_name = 'customers'
    paginate_by = 20

    def get(self, request, *args, **kwargs):
        self.object_list = self.get_queryset()
        context = self.get_context_data(object_list=self.object_list)
        if request.headers.get('HX-Request'):
            return render(request, 'master_data/partials/customer_table.html', context)
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        queryset = super().get_queryset().order_by('name')
        q = self.request.GET.get('q')
        if q:
            queryset = queryset.filter(
                Q(name__icontains=q) |
                Q(mobile_no__icontains=q)
            )
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Total customer count
        context['total_customers'] = Customer.objects.count()
        
        # New customers this month
        now = timezone.now()
        first_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        context['new_this_month'] = Customer.objects.filter(created_at__gte=first_of_month).count()
        
        # Top villages by customer count
        context['top_cities'] = (
            Customer.objects
            .filter(village__isnull=False)
            .values('village__name')
            .annotate(count=Count('id'))
            .order_by('-count')[:5]
        )
        
        return context

def _villages_json():
    """Serialise active villages for Alpine.js searchable dropdown."""
    return json.dumps(
        list(Village.objects.filter(is_active=True).order_by('name').values('id', 'name'))
    )


class CustomerCreateView(CreateView):
    model = Customer
    form_class = CustomerForm
    template_name = 'master_data/customer_form.html'
    success_url = reverse_lazy('customer_list')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['villages_json'] = _villages_json()
        return ctx


class CustomerUpdateView(UpdateView):
    model = Customer
    form_class = CustomerForm
    template_name = 'master_data/customer_form.html'
    success_url = reverse_lazy('customer_list')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['villages_json'] = _villages_json()
        return ctx

class CustomerDeleteView(DeleteView):
    model = Customer
    template_name = 'master_data/customer_confirm_delete.html'
    success_url = reverse_lazy('customer_list')

def export_customers(request):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="customer_list.csv"'

    writer = csv.writer(response)
    writer.writerow(['Customer Name', 'Mobile Number', 'City/Village', 'Address', 'GSTIN'])

    customers = Customer.objects.select_related('village').order_by('name')
    for customer in customers:
        writer.writerow([
            customer.name,
            customer.mobile_no,
            customer.village.name if customer.village else '',
            customer.address,
            customer.gstin or '',
        ])

    return response


def create_village(request):
    """HTMX/fetch endpoint — quick village creation from the customer form modal."""
    if request.method != 'POST':
        from django.http import JsonResponse
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    from django.http import JsonResponse
    name = request.POST.get('name', '').strip()
    if not name:
        return JsonResponse({'error': 'Village name is required.'}, status=400)
    village, _ = Village.objects.get_or_create(
        name__iexact=name,
        defaults={'name': name, 'is_active': True},
    )
    return JsonResponse({'id': village.id, 'name': village.name})


def check_mobile(request):
    """HTMX endpoint — inline duplicate detection for mobile number field."""
    mobile_no = request.GET.get('mobile_no', '').strip()
    customer_id = request.GET.get('customer_id', '').strip()

    if len(mobile_no) != 10 or not mobile_no.isdigit():
        return HttpResponse('')

    query = Customer.objects.filter(mobile_no=mobile_no)
    if customer_id:
        query = query.exclude(pk=customer_id)

    if query.exists():
        existing = query.select_related('village').first()
        location = f' · {existing.village.name}' if existing.village else ''
        return HttpResponse(
            f'<p class="text-amber-600 text-xs font-bold pl-1 mt-1 flex items-center gap-1">'
            f'<svg class="w-3.5 h-3.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">'
            f'<path d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/>'
            f'</svg>'
            f'Already registered: <strong>{existing.name}</strong>{location}'
            f'</p>'
        )

    return HttpResponse(
        '<p class="text-emerald-600 text-xs font-bold pl-1 mt-1 flex items-center gap-1">'
        '<svg class="w-3.5 h-3.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">'
        '<polyline points="20 6 9 17 4 12"/>'
        '</svg>'
        'Number available'
        '</p>'
    )

# --- Supplier Views ---

class SupplierListView(ListView):
    model = Supplier
    template_name = 'master_data/supplier_list.html'
    context_object_name = 'suppliers'
    paginate_by = 20

    def get(self, request, *args, **kwargs):
        self.object_list = self.get_queryset()
        context = self.get_context_data(object_list=self.object_list)
        if request.headers.get('HX-Request'):
            return render(request, 'master_data/partials/supplier_table.html', context)
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        queryset = super().get_queryset().order_by('name')
        q = self.request.GET.get('q')
        if q:
            queryset = queryset.filter(
                Q(name__icontains=q) |
                Q(gstin__icontains=q)
            )
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Stats
        context['total_suppliers'] = Supplier.objects.count()
        
        # Total Payables (from Transactions)
        total_payables = PurchaseInvoice.objects.filter(status='ACTIVE').aggregate(total=Sum('balance_due'))['total'] or 0
        context['total_payables'] = total_payables
        
        # Top Distributors
        context['top_distributors'] = Supplier.objects.filter(is_distributor=True).order_by('name')[:5]
        
        return context

class SupplierCreateView(CreateView):
    model = Supplier
    form_class = SupplierForm
    template_name = 'master_data/supplier_form.html'
    success_url = reverse_lazy('supplier_list')

class SupplierUpdateView(UpdateView):
    model = Supplier
    form_class = SupplierForm
    template_name = 'master_data/supplier_form.html'
    success_url = reverse_lazy('supplier_list')

class SupplierDeleteView(DeleteView):
    model = Supplier
    template_name = 'master_data/supplier_confirm_delete.html'
    success_url = reverse_lazy('supplier_list')

# --- Product Views ---
from .models import Product
from .forms import ProductForm

class ProductListView(ListView):
    model = Product
    template_name = 'master_data/product_list.html'
    context_object_name = 'products'
    paginate_by = 20

    def get(self, request, *args, **kwargs):
        self.object_list = self.get_queryset()
        context = self.get_context_data(object_list=self.object_list)
        if request.headers.get('HX-Request'):
            return render(request, 'master_data/partials/product_table.html', context)
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        queryset = super().get_queryset().select_related('category', 'manufacturer').order_by('name')
        q = self.request.GET.get('q')
        if q:
            queryset = queryset.filter(name__icontains=q)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Stats
        context['total_products'] = Product.objects.count()
        
        # Top Categories by Product Count
        context['category_counts'] = (
            Category.objects
            .annotate(product_count=Count('products'))
            .filter(product_count__gt=0)
            .order_by('-product_count')[:5]
        )
        
        return context

def _categories_json():
    """Serialise all categories for Alpine.js searchable dropdown."""
    return json.dumps(
        list(Category.objects.order_by('name').values('id', 'name'))
    )

def _manufacturers_json():
    """Serialise all manufacturers for Alpine.js searchable dropdown."""
    return json.dumps(
        list(Manufacturer.objects.order_by('name').values('id', 'name'))
    )


def create_category(request):
    """Quick-Add endpoint — create a category inline from the product form modal."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    name = request.POST.get('name', '').strip()
    if not name:
        return JsonResponse({'error': 'Category name is required.'}, status=400)
    cgst = request.POST.get('cgst_rate', '0') or '0'
    sgst = request.POST.get('sgst_rate', '0') or '0'
    try:
        category = Category.objects.get(name__iexact=name)
        created = False
    except Category.DoesNotExist:
        category = Category.objects.create(
            name=name,
            cgst_rate=cgst,
            sgst_rate=sgst,
            igst_rate=0,
        )
        created = True
    return JsonResponse({'id': category.id, 'name': category.name, 'created': created})


def create_manufacturer(request):
    """Quick-Add endpoint — create a manufacturer inline from the product form modal."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    name = request.POST.get('name', '').strip()
    if not name:
        return JsonResponse({'error': 'Manufacturer name is required.'}, status=400)
    try:
        manufacturer = Manufacturer.objects.get(name__iexact=name)
        created = False
    except Manufacturer.DoesNotExist:
        manufacturer = Manufacturer.objects.create(name=name)
        created = True
    return JsonResponse({'id': manufacturer.id, 'name': manufacturer.name, 'created': created})


class ProductCreateView(CreateView):
    model = Product
    form_class = ProductForm
    template_name = 'master_data/product_form.html'
    success_url = reverse_lazy('product_list')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['categories_json'] = _categories_json()
        ctx['manufacturers_json'] = _manufacturers_json()
        return ctx

class ProductUpdateView(UpdateView):
    model = Product
    form_class = ProductForm
    template_name = 'master_data/product_form.html'
    success_url = reverse_lazy('product_list')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['categories_json'] = _categories_json()
        ctx['manufacturers_json'] = _manufacturers_json()
        return ctx

class ProductDeleteView(DeleteView):
    model = Product
    template_name = 'master_data/product_confirm_delete.html'
    success_url = reverse_lazy('product_list')

def create_product_ajax(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        category_id = request.POST.get('category')
        manufacturer_id = request.POST.get('manufacturer')
        unit_type = request.POST.get('unit_type')
        hsn_code = request.POST.get('hsn_code')
        
        if name and category_id and manufacturer_id and unit_type:
            try:
                category = Category.objects.get(id=category_id)
                manufacturer = Manufacturer.objects.get(id=manufacturer_id)
                
                product = Product.objects.create(
                    name=name,
                    category=category,
                    manufacturer=manufacturer,
                    unit_type=unit_type,
                    hsn_code=hsn_code
                )
                # Return the option tag selected
                return HttpResponse(f'<option value="{product.name}" selected>{product.name}</option>')
            except Exception as e:
                return HttpResponse(f'<option value="">Error: {e}</option>', status=400)
    
    return HttpResponse("Invalid Request", status=400)

# --- Category Views ---
from .models import Category
from .forms import CategoryForm

class CategoryListView(ListView):
    model = Category
    template_name = 'master_data/category_list.html'
    context_object_name = 'categories'
    
    def get(self, request, *args, **kwargs):
        self.object_list = self.get_queryset()
        context = self.get_context_data(object_list=self.object_list)
        if request.headers.get('HX-Request'):
            return render(request, 'master_data/partials/category_grid.html', context)
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
         queryset = super().get_queryset().order_by('name')
         q = self.request.GET.get('q')
         if q:
             queryset = queryset.filter(name__icontains=q)
         return queryset

class CategoryCreateView(CreateView):
    model = Category
    form_class = CategoryForm
    template_name = 'master_data/category_form.html'
    success_url = reverse_lazy('category_list')

class CategoryUpdateView(UpdateView):
    model = Category
    form_class = CategoryForm
    template_name = 'master_data/category_form.html'
    success_url = reverse_lazy('category_list')

class CategoryDeleteView(DeleteView):
    model = Category
    template_name = 'master_data/category_confirm_delete.html'
    success_url = reverse_lazy('category_list')

# --- Village Views ---
from .forms import VillageForm
from django.contrib import messages
from django.shortcuts import redirect

class VillageListView(ListView):
    model = Village
    template_name = 'master_data/village_list.html'
    context_object_name = 'villages'
    paginate_by = 20

    def get(self, request, *args, **kwargs):
        self.object_list = self.get_queryset()
        context = self.get_context_data(object_list=self.object_list)
        if request.headers.get('HX-Request'):
            return render(request, 'master_data/partials/village_table.html', context)
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        queryset = (
            Village.objects
            .annotate(customer_count=Count('customer'))
            .order_by('name')
        )
        q = self.request.GET.get('q')
        if q:
            queryset = queryset.filter(name__icontains=q)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['total_villages'] = Village.objects.count()
        context['active_villages'] = Village.objects.filter(is_active=True).count()
        context['top_villages'] = (
            Village.objects
            .annotate(customer_count=Count('customer'))
            .filter(customer_count__gt=0)
            .order_by('-customer_count')[:5]
        )
        return context


class VillageCreateView(CreateView):
    model = Village
    form_class = VillageForm
    template_name = 'master_data/village_form.html'
    success_url = reverse_lazy('village_list')


class VillageUpdateView(UpdateView):
    model = Village
    form_class = VillageForm
    template_name = 'master_data/village_form.html'
    success_url = reverse_lazy('village_list')


class VillageDeleteView(DeleteView):
    model = Village
    template_name = 'master_data/village_confirm_delete.html'
    success_url = reverse_lazy('village_list')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['customer_count'] = self.get_object().customer_set.count()
        return ctx

    def post(self, request, *args, **kwargs):
        village = self.get_object()
        customer_count = village.customer_set.count()
        if customer_count > 0:
            messages.error(
                request,
                f'Cannot delete "{village.name}" — it is linked to {customer_count} '
                f'customer{"s" if customer_count != 1 else ""}. '
                'Reassign or remove those customers first.'
            )
            return redirect('village_list')
        return super().post(request, *args, **kwargs)


# --- Manufacturer Views ---
from .models import Manufacturer
from .forms import ManufacturerForm

class ManufacturerListView(ListView):
    model = Manufacturer
    template_name = 'master_data/manufacturer_list.html'
    context_object_name = 'manufacturers'

    def get(self, request, *args, **kwargs):
        self.object_list = self.get_queryset()
        context = self.get_context_data(object_list=self.object_list)
        if request.headers.get('HX-Request'):
            return render(request, 'master_data/partials/manufacturer_grid.html', context)
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
         queryset = super().get_queryset().order_by('name')
         q = self.request.GET.get('q')
         if q:
             queryset = queryset.filter(name__icontains=q)
         return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['recent_manufacturers'] = Manufacturer.objects.order_by('-id')[:5]
        return context

class ManufacturerCreateView(CreateView):
    model = Manufacturer
    form_class = ManufacturerForm
    template_name = 'master_data/manufacturer_form.html'
    success_url = reverse_lazy('manufacturer_list')

class ManufacturerUpdateView(UpdateView):
    model = Manufacturer
    form_class = ManufacturerForm
    template_name = 'master_data/manufacturer_form.html'
    success_url = reverse_lazy('manufacturer_list')

class ManufacturerDeleteView(DeleteView):
    model = Manufacturer
    template_name = 'master_data/manufacturer_confirm_delete.html'
    success_url = reverse_lazy('manufacturer_list')
