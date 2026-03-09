"""accounting URL configuration — Sprint 19: General Ledger UI."""

from django.urls import path
from . import views

urlpatterns = [
    path('ledger/', views.general_ledger, name='general_ledger'),
    path('ledger/validate/', views.validate_ledger, name='validate_ledger'),
    path(
        'gl/resolve/<str:reference_type>/<int:reference_id>/',
        views.resolve_source_document,
        name='resolve_source_document',
    ),
]
