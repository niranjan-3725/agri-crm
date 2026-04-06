from django.urls import path
from . import views
from farming import views as farming_views

urlpatterns = [
    # Customer URLs
    path('customers/', views.CustomerListView.as_view(), name='customer_list'),
    path('customers/add/', views.CustomerCreateView.as_view(), name='customer_add'),
    path('customers/<int:pk>/edit/', views.CustomerUpdateView.as_view(), name='customer_edit'),
    path('customers/<int:pk>/delete/', views.CustomerDeleteView.as_view(), name='customer_delete'),
    path('customers/export/', views.export_customers, name='customer_export'),
    path('customers/check-mobile/', views.check_mobile, name='customer_check_mobile'),

    # Cultivation Records — customer-scoped (lives under /masters/customers/<pk>/)
    path('customers/<int:pk>/cultivation/',          farming_views.cultivation_list,      name='cultivation_list'),
    path('customers/<int:pk>/cultivation/add-row/',  farming_views.cultivation_add_row,   name='cultivation_add_row'),
    path('customers/<int:pk>/cultivation/save/',     farming_views.cultivation_save_row,  name='cultivation_save_row'),
    path('villages/create/', views.create_village, name='create_village'),

    # Village Master URLs
    path('villages/', views.VillageListView.as_view(), name='village_list'),
    path('villages/add/', views.VillageCreateView.as_view(), name='village_add'),
    path('villages/<int:pk>/edit/', views.VillageUpdateView.as_view(), name='village_edit'),
    path('villages/<int:pk>/delete/', views.VillageDeleteView.as_view(), name='village_delete'),

    # Supplier URLs
    path('suppliers/', views.SupplierListView.as_view(), name='supplier_list'),
    path('suppliers/add/', views.SupplierCreateView.as_view(), name='supplier_add'),
    path('suppliers/<int:pk>/edit/', views.SupplierUpdateView.as_view(), name='supplier_edit'),
    path('suppliers/<int:pk>/delete/', views.SupplierDeleteView.as_view(), name='supplier_delete'),

    # Product URLs
    path('products/', views.ProductListView.as_view(), name='product_list'),
    path('products/add/', views.ProductCreateView.as_view(), name='product_add'),
    path('products/add/ajax/', views.create_product_ajax, name='create_product_ajax'),
    path('products/<int:pk>/edit/', views.ProductUpdateView.as_view(), name='product_edit'),
    path('products/<int:pk>/delete/', views.ProductDeleteView.as_view(), name='product_delete'),

    # Product quick-create helpers
    path('categories/create/', views.create_category, name='create_category'),
    path('manufacturers/create/', views.create_manufacturer, name='create_manufacturer'),

    # Category URLs
    path('categories/', views.CategoryListView.as_view(), name='category_list'),
    path('categories/add/', views.CategoryCreateView.as_view(), name='category_add'),
    path('categories/<int:pk>/edit/', views.CategoryUpdateView.as_view(), name='category_edit'),
    path('categories/<int:pk>/delete/', views.CategoryDeleteView.as_view(), name='category_delete'),

    # Manufacturer URLs
    path('manufacturers/', views.ManufacturerListView.as_view(), name='manufacturer_list'),
    path('manufacturers/add/', views.ManufacturerCreateView.as_view(), name='manufacturer_add'),
    path('manufacturers/<int:pk>/edit/', views.ManufacturerUpdateView.as_view(), name='manufacturer_edit'),
    path('manufacturers/<int:pk>/delete/', views.ManufacturerDeleteView.as_view(), name='manufacturer_delete'),
]
