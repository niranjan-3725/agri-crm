from django.contrib import admin

from .models import Batch, StockMovement


@admin.register(Batch)
class BatchAdmin(admin.ModelAdmin):
    list_display = ('product', 'batch_number', 'current_quantity', 'mrp', 'base_selling_price', 'expiry_date', 'is_active')
    search_fields = ('product__name', 'batch_number')
    list_filter = ('is_active', 'expiry_date')


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ('batch', 'quantity', 'reference_document_type', 'reference_document_id', 'created_at')
    list_filter = ('reference_document_type', 'created_at')
    search_fields = ('batch__product__name', 'batch__batch_number')
    readonly_fields = ('batch', 'quantity', 'reference_document_type', 'reference_document_id', 'created_at')

    def has_add_permission(self, request):
        return False  # Ledger is append-only via service layer

    def has_change_permission(self, request, obj=None):
        return False  # Immutable

