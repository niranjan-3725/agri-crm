from django.contrib import admin
from .models import Category, Manufacturer, Product, Supplier, Customer

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'cgst_rate', 'sgst_rate', 'igst_rate', 'total_tax')

@admin.register(Manufacturer)
class ManufacturerAdmin(admin.ModelAdmin):
    list_display = ('name',)

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'hsn_code', 'unit_type', 'category', 'manufacturer')
    list_filter = ('category', 'manufacturer', 'unit_type')
    search_fields = ('name', 'hsn_code')

@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ('name', 'gstin', 'phone', 'is_distributor')

@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('name', 'mobile_no', 'gstin')
