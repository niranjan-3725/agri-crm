from django.urls import path
from . import views

urlpatterns = [
    path('inventory/', views.inventory_list, name='inventory_list'),
    path('inventory/<int:batch_id>/reconcile/', views.stock_reconcile, name='stock_reconcile'),
]
