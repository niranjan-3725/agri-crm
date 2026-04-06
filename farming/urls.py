from django.urls import path
from . import views

urlpatterns = [
    # Crop Master CRUD
    path('crops/',                   views.CropListView.as_view(),   name='crop_list'),
    path('crops/add/',               views.CropCreateView.as_view(), name='crop_add'),
    path('crops/<int:pk>/edit/',     views.CropUpdateView.as_view(), name='crop_edit'),
    path('crops/<int:pk>/delete/',   views.CropDeleteView.as_view(), name='crop_delete'),

    # Cultivation — status toggle
    path('cultivation/<int:pk>/status/', views.cultivation_status_update, name='cultivation_status_update'),

    # Recommendations
    path('recommendations/<int:customer_pk>/', views.recommendation_view, name='farming_recommendations'),

    # Seasonal Transition
    path('seasonal-transition/',                              views.seasonal_transition_view, name='seasonal_transition'),
    path('seasonal-transition/<int:customer_pk>/action/',    views.seasonal_action,          name='seasonal_action'),

    # Ag-CDSS: Field Consultations
    path('consultations/',                         views.consultation_list_view,   name='consultation_list'),
    path('consultations/new/',                    views.consultation_create_view, name='consultation_create'),
    path('consultations/new/<int:customer_pk>/',  views.consultation_create_view, name='consultation_create_for_customer'),
    path('consultations/htmx/add-diagnosis/',     views.add_diagnosis_row,        name='add_diagnosis_row'),
    path('consultations/htmx/add-prescription/',  views.add_prescription_row,     name='add_prescription_row'),
    path('consultations/api/norm-suggest/',        views.norm_suggest_api,         name='norm_suggest_api'),
]
