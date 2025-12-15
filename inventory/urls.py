from django.urls import path
from . import views

urlpatterns = [
    path('inventory/', views.inventory_list, name='inventory_list'),
]
