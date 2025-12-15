from django.contrib import admin

from .models import Batch
    
@admin.register(Batch)
class BatchAdmin(admin.ModelAdmin):
    list_display = ('product', 'batch_number', 'current_quantity', 'mrp', 'base_selling_price', 'expiry_date', 'is_active')
    search_fields = ('product__name', 'batch_number')
    list_filter = ('is_active', 'expiry_date')
