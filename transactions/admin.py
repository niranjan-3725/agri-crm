from django.contrib import admin

from .models import (
    PurchaseInvoice, PurchaseItem,
    SalesInvoice, SalesItem,
    PurchaseReturn, PurchaseReturnItem,
    SalesReturn, SalesReturnItem
)

class PurchaseItemInline(admin.StackedInline):
    model = PurchaseItem
    extra = 1

@admin.register(PurchaseInvoice)
class PurchaseInvoiceAdmin(admin.ModelAdmin):
    inlines = [PurchaseItemInline]
    list_display = ('invoice_number', 'supplier', 'date', 'total_amount')

class SalesItemInline(admin.StackedInline):
    model = SalesItem
    extra = 1

@admin.register(SalesInvoice)
class SalesInvoiceAdmin(admin.ModelAdmin):
    inlines = [SalesItemInline]
    list_display = ('invoice_number', 'customer', 'date', 'grand_total')

class PurchaseReturnItemInline(admin.StackedInline):
    model = PurchaseReturnItem
    extra = 1

@admin.register(PurchaseReturn)
class PurchaseReturnAdmin(admin.ModelAdmin):
    inlines = [PurchaseReturnItemInline]
    list_display = ('supplier', 'date', 'total_refund_amount')

class SalesReturnItemInline(admin.StackedInline):
    model = SalesReturnItem
    extra = 1

@admin.register(SalesReturn)
class SalesReturnAdmin(admin.ModelAdmin):
    inlines = [SalesReturnItemInline]
    list_display = ('original_sale', 'date', 'refund_amount')
