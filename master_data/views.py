from django.shortcuts import render
from django.http import HttpResponse
from django.db.models import Q, Count, Sum
from django.urls import reverse_lazy
from django.views.generic import ListView, CreateView, UpdateView, DeleteView
from django.utils import timezone
import csv
from .models import Customer, Supplier
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
        
        # Top cities by customer count
        context['top_cities'] = (
            Customer.objects
            .exclude(city__isnull=True)
            .exclude(city='')
            .values('city')
            .annotate(count=Count('id'))
            .order_by('-count')[:5]
        )
        
        return context

class CustomerCreateView(CreateView):
    model = Customer
    form_class = CustomerForm
    template_name = 'master_data/customer_form.html'
    success_url = reverse_lazy('customer_list')

class CustomerUpdateView(UpdateView):
    model = Customer
    form_class = CustomerForm
    template_name = 'master_data/customer_form.html'
    success_url = reverse_lazy('customer_list')

class CustomerDeleteView(DeleteView):
    model = Customer
    template_name = 'master_data/customer_confirm_delete.html'
    success_url = reverse_lazy('customer_list')

def export_customers(request):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="customer_list.csv"'

    writer = csv.writer(response)
    writer.writerow(['Customer Name', 'Mobile Number', 'City/Village', 'Address', 'GSTIN'])

    customers = Customer.objects.all().order_by('name')
    for customer in customers:
        writer.writerow([
            customer.name,
            customer.mobile_no,
            customer.city or '',
            customer.address,
            customer.gstin or ''
        ])

    return response

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
        total_payables = PurchaseInvoice.objects.aggregate(total=Sum('balance_due'))['total'] or 0
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

class ProductCreateView(CreateView):
    model = Product
    form_class = ProductForm
    template_name = 'master_data/product_form.html'
    success_url = reverse_lazy('product_list')

class ProductUpdateView(UpdateView):
    model = Product
    form_class = ProductForm
    template_name = 'master_data/product_form.html'
    success_url = reverse_lazy('product_list')

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
