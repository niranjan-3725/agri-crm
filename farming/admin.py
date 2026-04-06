from django.contrib import admin

from .models import CropMaster, CropProductNorm, CultivationRecord


class CropProductNormInline(admin.TabularInline):
    model = CropProductNorm
    extra = 1
    fields = ['product', 'application_rate', 'unit', 'notes']


@admin.register(CropMaster)
class CropMasterAdmin(admin.ModelAdmin):
    list_display  = ['name', 'crop_type', 'is_active']
    list_filter   = ['crop_type', 'is_active']
    search_fields = ['name']
    inlines       = [CropProductNormInline]


@admin.register(CropProductNorm)
class CropProductNormAdmin(admin.ModelAdmin):
    list_display  = ['crop', 'product', 'application_rate', 'unit']
    list_filter   = ['crop']
    search_fields = ['crop__name', 'product__name']


@admin.register(CultivationRecord)
class CultivationRecordAdmin(admin.ModelAdmin):
    list_display  = ['customer', 'crop', 'acreage', 'season', 'season_year', 'status']
    list_filter   = ['season', 'season_year', 'status', 'crop']
    search_fields = ['customer__name', 'crop__name']
    raw_id_fields = ['customer', 'crop']
