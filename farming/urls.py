from django.urls import path
from . import views

urlpatterns = [
    # Crop Master CRUD
    path('crops/',                   views.CropListView.as_view(),   name='crop_list'),
    path('crops/add/',               views.CropCreateView.as_view(), name='crop_add'),
    path('crops/<int:pk>/edit/',     views.CropUpdateView.as_view(), name='crop_edit'),
    path('crops/<int:pk>/delete/',   views.CropDeleteView.as_view(), name='crop_delete'),

    # Agronomist Profile CRUD
    path('agronomists/',               views.AgronomistListView.as_view(),   name='agronomist_list'),
    path('agronomists/add/',           views.AgronomistCreateView.as_view(), name='agronomist_add'),
    path('agronomists/<int:pk>/edit/', views.AgronomistUpdateView.as_view(), name='agronomist_edit'),

    # Pest / Disease Library CRUD
    path('pests/',               views.PestDiseaseListView.as_view(),   name='pest_list'),
    path('pests/add/',           views.PestDiseaseCreateView.as_view(), name='pest_add'),
    path('pests/<int:pk>/edit/', views.PestDiseaseUpdateView.as_view(), name='pest_edit'),

    # Cultivation — status toggle
    path('cultivation/<int:pk>/status/', views.cultivation_status_update, name='cultivation_status_update'),

    # Recommendations
    path('recommendations/<int:customer_pk>/', views.recommendation_view, name='farming_recommendations'),

    # Seasonal Transition
    path('seasonal-transition/',                              views.seasonal_transition_view, name='seasonal_transition'),
    path('seasonal-transition/<int:customer_pk>/action/',    views.seasonal_action,          name='seasonal_action'),

    # Ag-CDSS: Field Consultations — list + Page 1 intake
    path('consultations/',                          views.consultation_list_view,    name='consultation_list'),
    path('consultation/new/',                       views.consultation_new_view,     name='consultation_create'),
    path('consultation/new/<int:customer_pk>/',     views.consultation_new_view,     name='consultation_create_for_customer'),

    # Page 2 — detail / diagnosis grid
    path('consultation/<int:pk>/',                  views.consultation_detail_view,  name='consultation_detail'),
    path('consultation/<int:pk>/submit/',           views.consultation_submit,        name='consultation_submit'),

    # HTMX: per-row diagnosis management
    path('consultation/<int:pk>/diagnosis/add-row/',              views.diagnosis_add_row,      name='diagnosis_add_row'),
    path('consultation/<int:pk>/diagnosis/<int:row_id>/save/',    views.diagnosis_save_row,     name='diagnosis_save_row'),
    path('consultation/<int:pk>/diagnosis/<int:row_id>/delete/',  views.diagnosis_delete_row,   name='diagnosis_delete_row'),
    path('consultation/<int:pk>/diagnosis/<int:row_id>/photo/',   views.diagnosis_upload_photo, name='diagnosis_upload_photo'),

    # Ag-CDSS: Prescription grid (Page 3) + approval + PDF
    path('consultation/<int:pk>/prescriptions/',                             views.prescription_view,        name='prescription_view'),
    path('consultation/<int:pk>/approve/',                                   views.consultation_approve,      name='consultation_approve'),
    path('consultation/<int:pk>/pdf/',                                       views.prescription_pdf_view,     name='prescription_pdf'),

    # HTMX: per-row prescription management
    path('consultation/<int:pk>/prescription/add-row/',                      views.prescription_add_row,         name='prescription_add_row'),
    path('consultation/<int:pk>/prescription/<int:row_id>/save/',            views.prescription_save_row,        name='prescription_save_row'),
    path('consultation/<int:pk>/prescription/<int:row_id>/delete/',          views.prescription_delete_row,      name='prescription_delete_row'),
    path('consultation/<int:pk>/prescription/<int:row_id>/get/',             views.prescription_row_get,         name='prescription_row_get'),

    # Phase 5: Dispense
    path('consultation/<int:pk>/prescription/<int:row_id>/dispense/',        views.prescription_dispense_form,   name='prescription_dispense_form'),
    path('consultation/<int:pk>/prescription/<int:row_id>/dispense/confirm/',views.prescription_dispense_confirm,name='prescription_dispense_confirm'),

    # API
    path('consultations/api/norm-suggest/', views.norm_suggest_api, name='norm_suggest_api'),
]
