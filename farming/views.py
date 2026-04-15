import json

from django.views.generic import ListView, CreateView, UpdateView, DeleteView
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse_lazy
from django.contrib import messages
from django.db.models import Count, Q
from django.utils import timezone
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_GET

from inventory.models import Batch
from master_data.models import Customer
from .models import (
    CropMaster, CropProductNorm, CultivationRecord,
    AgronomistProfile, PestDiseaseLibrary,
    FieldConsultation, DiagnosisLine, ConsultationPhoto, PrescriptionLine,
)
from .forms import (
    CropMasterForm, CultivationRecordForm,
    AgronomistProfileForm, PestDiseaseLibraryForm,
    FieldConsultationForm, DiagnosisLineForm, ConsultationPhotoForm,
    PrescriptionLineForm,
)


# ── Crop Master CRUD ─────────────────────────────────────────────────────────

class CropListView(ListView):
    model = CropMaster
    template_name = 'farming/crop_list.html'
    context_object_name = 'crops'
    paginate_by = 20

    def get(self, request, *args, **kwargs):
        self.object_list = self.get_queryset()
        context = self.get_context_data(object_list=self.object_list)
        if request.headers.get('HX-Request'):
            return render(request, 'farming/partials/crop_table.html', context)
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        qs = (CropMaster.objects
              .annotate(record_count=Count('cultivation_records'))
              .order_by('name'))
        q = self.request.GET.get('q')
        if q:
            qs = qs.filter(name__icontains=q)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['total_crops']  = CropMaster.objects.count()
        ctx['active_crops'] = CropMaster.objects.filter(is_active=True).count()
        ctx['kharif_count'] = CropMaster.objects.filter(crop_type__in=['KHARIF', 'BOTH']).count()
        ctx['rabi_count']   = CropMaster.objects.filter(crop_type__in=['RABI', 'BOTH']).count()
        return ctx


class CropCreateView(CreateView):
    model = CropMaster
    form_class = CropMasterForm
    template_name = 'farming/crop_form.html'
    success_url = reverse_lazy('crop_list')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from .forms import CropProductNormFormSet
        ctx['norm_formset'] = CropProductNormFormSet(
            self.request.POST or None,
            prefix='norms',
        )
        return ctx

    def form_valid(self, form):
        from .forms import CropProductNormFormSet
        ctx = self.get_context_data()
        norm_formset = ctx['norm_formset']
        if form.is_valid() and norm_formset.is_valid():
            self.object = form.save()
            norm_formset.instance = self.object
            norm_formset.save()
            return redirect(self.success_url)
        return self.render_to_response(self.get_context_data(form=form))


class CropUpdateView(UpdateView):
    model = CropMaster
    form_class = CropMasterForm
    template_name = 'farming/crop_form.html'
    success_url = reverse_lazy('crop_list')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from .forms import CropProductNormFormSet
        ctx['norm_formset'] = CropProductNormFormSet(
            self.request.POST or None,
            instance=self.object,
            prefix='norms',
        )
        return ctx

    def form_valid(self, form):
        ctx = self.get_context_data()
        norm_formset = ctx['norm_formset']
        if form.is_valid() and norm_formset.is_valid():
            self.object = form.save()
            norm_formset.instance = self.object
            norm_formset.save()
            return redirect(self.success_url)
        return self.render_to_response(self.get_context_data(form=form))


class CropDeleteView(DeleteView):
    model = CropMaster
    template_name = 'farming/crop_confirm_delete.html'
    success_url = reverse_lazy('crop_list')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['record_count'] = self.get_object().cultivation_records.count()
        ctx['norm_count']   = self.get_object().norms.count()
        return ctx

    def post(self, request, *args, **kwargs):
        crop = self.get_object()
        record_count = crop.cultivation_records.count()
        if record_count > 0:
            messages.error(
                request,
                f'Cannot delete "{crop.name}" — it is linked to {record_count} '
                f'cultivation record{"s" if record_count != 1 else ""}. '
                'Mark them as Harvested first.'
            )
            return redirect('crop_list')
        return super().post(request, *args, **kwargs)


# ── Agronomist Profile CRUD ───────────────────────────────────────────────────

class AgronomistListView(ListView):
    model = AgronomistProfile
    template_name = 'farming/agronomist_list.html'
    context_object_name = 'agronomists'

    def get(self, request, *args, **kwargs):
        self.object_list = self.get_queryset()
        context = self.get_context_data(object_list=self.object_list)
        if request.headers.get('HX-Request'):
            return render(request, 'farming/partials/agronomist_table.html', context)
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        qs = AgronomistProfile.objects.order_by('name')
        q = self.request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(employee_id__icontains=q) | Q(zone__icontains=q))
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['total'] = AgronomistProfile.objects.count()
        ctx['active'] = AgronomistProfile.objects.filter(is_active=True).count()
        return ctx


class AgronomistCreateView(CreateView):
    model = AgronomistProfile
    form_class = AgronomistProfileForm
    template_name = 'farming/agronomist_form.html'
    success_url = reverse_lazy('agronomist_list')

    def form_valid(self, form):
        messages.success(self.request, f'Agronomist "{form.instance.name}" added.')
        return super().form_valid(form)


class AgronomistUpdateView(UpdateView):
    model = AgronomistProfile
    form_class = AgronomistProfileForm
    template_name = 'farming/agronomist_form.html'
    success_url = reverse_lazy('agronomist_list')

    def form_valid(self, form):
        messages.success(self.request, f'"{form.instance.name}" updated.')
        return super().form_valid(form)


# ── Pest / Disease Library CRUD ───────────────────────────────────────────────

class PestDiseaseListView(ListView):
    model = PestDiseaseLibrary
    template_name = 'farming/pest_list.html'
    context_object_name = 'pests'

    def get(self, request, *args, **kwargs):
        self.object_list = self.get_queryset()
        context = self.get_context_data(object_list=self.object_list)
        if request.headers.get('HX-Request'):
            return render(request, 'farming/partials/pest_table.html', context)
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        qs = PestDiseaseLibrary.objects.prefetch_related('affected_crops').order_by('type', 'name')
        q = self.request.GET.get('q', '').strip()
        t = self.request.GET.get('type', '').strip()
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(local_name__icontains=q))
        if t:
            qs = qs.filter(type=t)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['total'] = PestDiseaseLibrary.objects.count()
        ctx['type_choices'] = PestDiseaseLibrary.Type.choices
        ctx['active_type'] = self.request.GET.get('type', '')
        return ctx


class PestDiseaseCreateView(CreateView):
    model = PestDiseaseLibrary
    form_class = PestDiseaseLibraryForm
    template_name = 'farming/pest_form.html'
    success_url = reverse_lazy('pest_list')

    def form_valid(self, form):
        response = super().form_valid(form)
        form.save_affected_crops(self.object)
        messages.success(self.request, f'"{self.object.name}" added to the library.')
        return response


class PestDiseaseUpdateView(UpdateView):
    model = PestDiseaseLibrary
    form_class = PestDiseaseLibraryForm
    template_name = 'farming/pest_form.html'
    success_url = reverse_lazy('pest_list')

    def form_valid(self, form):
        response = super().form_valid(form)
        form.save_affected_crops(self.object)
        messages.success(self.request, f'"{self.object.name}" updated.')
        return response


# ── Cultivation Records ───────────────────────────────────────────────────────

def cultivation_list(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    records = (CultivationRecord.objects
               .filter(customer=customer)
               .select_related('crop')
               .order_by('-season_year', 'season'))

    # Group by (season_year, season) for display
    grouped = {}
    for rec in records:
        key = (rec.season_year, rec.get_season_display())
        grouped.setdefault(key, []).append(rec)

    # Active crops for the inline add-row select
    crops_qs = CropMaster.objects.filter(is_active=True).order_by('name')

    return render(request, 'farming/cultivation_list.html', {
        'customer': customer,
        'grouped': grouped,
        'crops': crops_qs,
        'add_form': CultivationRecordForm(),
    })


def cultivation_add_row(request, pk):
    """HTMX GET — returns an empty inline form row fragment."""
    customer = get_object_or_404(Customer, pk=pk)
    form = CultivationRecordForm()
    return render(request, 'farming/partials/cultivation_row_form.html', {
        'customer': customer,
        'form': form,
    })


def cultivation_save_row(request, pk):
    """HTMX POST — validates and saves one record, returns rendered row partial."""
    customer = get_object_or_404(Customer, pk=pk)
    form = CultivationRecordForm(request.POST)
    if form.is_valid():
        record = form.save(commit=False)
        record.customer = customer
        record.save()
        return render(request, 'farming/partials/cultivation_row.html', {
            'rec': record,
            'customer': customer,
        })
    return render(request, 'farming/partials/cultivation_row_form.html', {
        'customer': customer,
        'form': form,
    })


def cultivation_status_update(request, pk):
    """HTMX POST — toggle status ACTIVE↔HARVESTED."""
    rec = get_object_or_404(CultivationRecord, pk=pk)
    if request.method == 'POST':
        if rec.status == 'ACTIVE':
            rec.status = 'HARVESTED'
        elif rec.status == 'HARVESTED':
            rec.status = 'ACTIVE'
        # PLANNED → ACTIVE on first confirm
        elif rec.status == 'PLANNED':
            rec.status = 'ACTIVE'
        rec.save(update_fields=['status', 'updated_at'])
    return render(request, 'farming/partials/cultivation_row.html', {
        'rec': rec,
        'customer': rec.customer,
    })


# ── Recommendation Engine ─────────────────────────────────────────────────────

def recommendation_view(request, customer_pk):
    from .services import get_recommendations
    customer = get_object_or_404(Customer, pk=customer_pk)
    lines    = get_recommendations(customer_pk)

    # Group lines by crop for template display
    grouped = {}
    for line in lines:
        grouped.setdefault(line.crop_name, []).append(line)

    return render(request, 'farming/recommendation.html', {
        'customer': customer,
        'grouped': grouped,
        'has_records': CultivationRecord.objects.filter(
            customer=customer, status='ACTIVE'
        ).exists(),
    })


# ── Seasonal Transition ───────────────────────────────────────────────────────

def seasonal_transition_view(request):
    today = timezone.now().date()
    month = today.month

    if month == 10:
        outgoing_season = 'KHARIF'
        outgoing_year   = today.year
        next_season     = 'RABI'
        next_year       = today.year
    else:
        # March (or any other time — show last completed season)
        outgoing_season = 'RABI'
        outgoing_year   = today.year
        next_season     = 'KHARIF'
        next_year       = today.year

    customers = (
        Customer.objects
        .filter(
            cultivation_records__status='ACTIVE',
            cultivation_records__season=outgoing_season,
            cultivation_records__season_year=outgoing_year,
        )
        .distinct()
        .order_by('name')
        .annotate(active_record_count=Count(
            'cultivation_records',
            filter=Q(
                cultivation_records__status='ACTIVE',
                cultivation_records__season=outgoing_season,
                cultivation_records__season_year=outgoing_year,
            )
        ))
    )

    return render(request, 'farming/seasonal_transition.html', {
        'customers':        customers,
        'outgoing_season':  outgoing_season,
        'outgoing_year':    outgoing_year,
        'next_season':      next_season,
        'next_year':        next_year,
    })


def seasonal_action(request, customer_pk):
    """HTMX POST — per-customer row action in the seasonal transition table."""
    customer        = get_object_or_404(Customer, pk=customer_pk)
    action          = request.POST.get('action')          # same | update | skip
    outgoing_season = request.POST.get('outgoing_season')
    outgoing_year   = int(request.POST.get('outgoing_year'))
    next_season     = request.POST.get('next_season')
    next_year       = int(request.POST.get('next_year'))

    if action == 'same':
        active_qs = CultivationRecord.objects.filter(
            customer=customer,
            season=outgoing_season,
            season_year=outgoing_year,
            status='ACTIVE',
        ).select_related('crop')
        # Snapshot before updating
        snapshot = list(active_qs)
        active_qs.update(status='HARVESTED')
        for rec in snapshot:
            CultivationRecord.objects.create(
                customer=customer,
                crop=rec.crop,
                acreage=rec.acreage,
                season=next_season,
                season_year=next_year,
                status='ACTIVE',
                notes=rec.notes,
            )

    return render(request, 'farming/partials/seasonal_customer_row.html', {
        'customer':     customer,
        'action_result': action,
        'next_season':  next_season,
        'next_year':    next_year,
    })


# ── Ag-CDSS: Field Consultation ───────────────────────────────────────────────

def consultation_list_view(request):
    consultations = (
        FieldConsultation.objects
        .select_related('customer', 'agronomist')
        .order_by('-consultation_date', '-created_at')
    )
    q = request.GET.get('q', '').strip()
    if q:
        consultations = consultations.filter(
            Q(consultation_number__icontains=q) | Q(customer__name__icontains=q)
        )
    return render(request, 'farming/consultation_list.html', {
        'consultations': consultations,
        'q': q,
    })


def consultation_new_view(request, customer_pk=None):
    """Page 1 — intake form: creates DRAFT FieldConsultation, redirects to Page 2."""
    from .services import generate_consultation_number, get_active_cultivations
    customer = get_object_or_404(Customer, pk=customer_pk) if customer_pk else None

    if request.method == 'POST':
        form = FieldConsultationForm(request.POST)
        if form.is_valid():
            consultation = form.save(commit=False)
            consultation.consultation_number = generate_consultation_number()
            consultation.status = FieldConsultation.Status.DRAFT
            consultation.save()
            messages.success(request, f'{consultation.consultation_number} created — add your diagnosis below.')
            return redirect('consultation_detail', pk=consultation.pk)
    else:
        initial = {'customer': customer} if customer else {}
        form = FieldConsultationForm(initial=initial)

    # Show active cultivation records if customer known
    cultivations = get_active_cultivations(customer) if customer else []

    return render(request, 'farming/consultation_form.html', {
        'form':         form,
        'customer':     customer,
        'cultivations': cultivations,
    })


def consultation_detail_view(request, pk):
    """Page 2 — diagnosis grid.  Read-only once SUBMITTED."""
    consultation = get_object_or_404(
        FieldConsultation.objects.select_related('customer', 'agronomist', 'field_visit'),
        pk=pk,
    )
    diagnosis_lines = (
        consultation.diagnosis_lines
        .select_related('pest_disease', 'cultivation_record__crop')
        .prefetch_related('photos')
        .order_by('sequence')
    )
    return render(request, 'farming/consultation_detail.html', {
        'consultation':    consultation,
        'diagnosis_lines': diagnosis_lines,
        'editable':        consultation.status == FieldConsultation.Status.DRAFT,
    })


# ── HTMX: Diagnosis row management ───────────────────────────────────────────

def _dx_form_context(consultation, customer, row=None):
    """Build context dict shared by dx_row template (new and edit)."""
    form = DiagnosisLineForm(instance=row, customer=customer)
    return {
        'form':         form,
        'consultation': consultation,
        'row':          row,
        'row_id':       row.pk if row else 0,
    }


def diagnosis_add_row(request, pk):
    """HTMX POST — return a blank DiagnosisLine form row (no DB change yet)."""
    consultation = get_object_or_404(FieldConsultation, pk=pk, status=FieldConsultation.Status.DRAFT)
    ctx = _dx_form_context(consultation, consultation.customer)
    return render(request, 'farming/partials/dx_row.html', ctx)


def diagnosis_save_row(request, pk, row_id):
    """HTMX POST — create (row_id=0) or update an existing DiagnosisLine."""
    consultation = get_object_or_404(FieldConsultation, pk=pk, status=FieldConsultation.Status.DRAFT)
    instance = get_object_or_404(DiagnosisLine, pk=row_id, consultation=consultation) if row_id else None
    form = DiagnosisLineForm(request.POST, instance=instance, customer=consultation.customer)
    if form.is_valid():
        row = form.save(commit=False)
        row.consultation = consultation
        if not row.pk:
            row.sequence = consultation.diagnosis_lines.count()
        row.save()
        return render(request, 'farming/partials/dx_row.html', {
            'form':         DiagnosisLineForm(instance=row, customer=consultation.customer),
            'consultation': consultation,
            'row':          row,
            'row_id':       row.pk,
        })
    # Validation failed — return form with errors
    return render(request, 'farming/partials/dx_row.html', {
        'form':         form,
        'consultation': consultation,
        'row':          instance,
        'row_id':       row_id,
    })


def diagnosis_delete_row(request, pk, row_id):
    """HTMX POST — delete a DiagnosisLine; respond with empty HTML (hx-swap delete)."""
    consultation = get_object_or_404(FieldConsultation, pk=pk, status=FieldConsultation.Status.DRAFT)
    row = get_object_or_404(DiagnosisLine, pk=row_id, consultation=consultation)
    row.delete()
    return HttpResponse(status=200)  # HTMX hx-swap="delete" removes the target


def diagnosis_upload_photo(request, pk, row_id):
    """HTMX POST — attach a photo to a DiagnosisLine; return updated photo strip."""
    consultation = get_object_or_404(FieldConsultation, pk=pk)
    row = get_object_or_404(DiagnosisLine, pk=row_id, consultation=consultation)
    form = ConsultationPhotoForm(request.POST, request.FILES)
    if form.is_valid():
        photo = form.save(commit=False)
        photo.diagnosis_line = row
        photo.save()
    photos = row.photos.order_by('taken_at')
    return render(request, 'farming/partials/dx_photo_strip.html', {
        'row':    row,
        'photos': photos,
        'consultation': consultation,
    })


def consultation_submit(request, pk):
    """POST — transition DRAFT → SUBMITTED."""
    consultation = get_object_or_404(FieldConsultation, pk=pk)
    if request.method == 'POST' and consultation.status == FieldConsultation.Status.DRAFT:
        if not consultation.diagnosis_lines.exists():
            messages.error(request, 'Add at least one diagnosis before submitting.')
        else:
            consultation.status = FieldConsultation.Status.SUBMITTED
            consultation.save(update_fields=['status'])
            messages.success(request, f'{consultation.consultation_number} submitted for review.')
    return redirect('consultation_detail', pk=pk)


@require_GET
def norm_suggest_api(request):
    """JSON API: return CropProductNorm dosage for a (crop, product) pair."""
    from .services import norm_suggest
    crop_id    = request.GET.get('crop_id')
    product_id = request.GET.get('product_id')
    severity   = request.GET.get('severity', '')

    if not crop_id or not product_id:
        return JsonResponse({'found': False})

    result = norm_suggest(crop_id, product_id, severity)
    if result:
        return JsonResponse({
            'found':            True,
            'application_rate': str(result['application_rate']),
            'unit':             result['unit'],
            'severity_used':    result['severity_used'],
        })
    return JsonResponse({'found': False})


# ── Ag-CDSS: Prescription grid (Page 3) ──────────────────────────────────────

def _rx_form_context(consultation, row=None):
    """Build context for rx_row template (new and edit)."""
    form = PrescriptionLineForm(instance=row, consultation=consultation)
    dx_areas = {
        str(dl.pk): float(dl.affected_area_acres)
        for dl in consultation.diagnosis_lines.all()
    }
    return {
        'form':          form,
        'consultation':  consultation,
        'row':           row,
        'row_id':        row.pk if row else 0,
        'dx_areas_json': json.dumps(dx_areas),
    }


def prescription_view(request, pk):
    """Page 3 — prescription grid. Staff can approve from here."""
    consultation = get_object_or_404(
        FieldConsultation.objects.select_related('customer', 'agronomist', 'approved_by'),
        pk=pk,
    )
    diagnosis_lines = (
        consultation.diagnosis_lines
        .select_related('pest_disease', 'cultivation_record__crop')
        .order_by('sequence')
    )
    prescription_lines = (
        consultation.prescription_lines
        .select_related('product', 'diagnosis_line__pest_disease', 'chosen_batch')
        .order_by('sequence')
    )
    dx_areas = {
        str(dl.pk): float(dl.affected_area_acres)
        for dl in diagnosis_lines
    }
    editable = consultation.status in (
        FieldConsultation.Status.SUBMITTED,
        FieldConsultation.Status.APPROVED,
    )
    return render(request, 'farming/prescription_view.html', {
        'consultation':       consultation,
        'diagnosis_lines':    diagnosis_lines,
        'prescription_lines': prescription_lines,
        'dx_areas_json':      json.dumps(dx_areas),
        'editable':           editable,
        'can_approve': (
            request.user.is_staff
            and consultation.status == FieldConsultation.Status.SUBMITTED
        ),
    })


def prescription_add_row(request, pk):
    """HTMX POST — return a blank PrescriptionLine form row."""
    consultation = get_object_or_404(
        FieldConsultation,
        pk=pk,
        status__in=[FieldConsultation.Status.SUBMITTED, FieldConsultation.Status.APPROVED],
    )
    ctx = _rx_form_context(consultation)
    return render(request, 'farming/partials/rx_row.html', ctx)


def prescription_save_row(request, pk, row_id):
    """HTMX POST — create (row_id=0) or update an existing PrescriptionLine."""
    from .services import calculate_total_quantity
    consultation = get_object_or_404(
        FieldConsultation,
        pk=pk,
        status__in=[FieldConsultation.Status.SUBMITTED, FieldConsultation.Status.APPROVED],
    )
    instance = (
        get_object_or_404(PrescriptionLine, pk=row_id, consultation=consultation)
        if row_id else None
    )
    form = PrescriptionLineForm(request.POST, instance=instance, consultation=consultation)
    if form.is_valid():
        row = form.save(commit=False)
        row.consultation = consultation
        if not row.pk:
            row.sequence = consultation.prescription_lines.count()
        # Compute total_quantity server-side
        if row.diagnosis_line:
            row.total_quantity = calculate_total_quantity(
                row.dosage_per_acre, row.diagnosis_line.affected_area_acres
            )
        else:
            row.total_quantity = row.dosage_per_acre  # fallback: treat as 1 unit
        row.save()
        ctx = _rx_form_context(consultation, row)
        return render(request, 'farming/partials/rx_row.html', ctx)
    # Validation failed — return form with errors
    dx_areas = {
        str(dl.pk): float(dl.affected_area_acres)
        for dl in consultation.diagnosis_lines.all()
    }
    return render(request, 'farming/partials/rx_row.html', {
        'form':          form,
        'consultation':  consultation,
        'row':           instance,
        'row_id':        row_id,
        'dx_areas_json': json.dumps(dx_areas),
    })


def prescription_delete_row(request, pk, row_id):
    """HTMX POST — delete a PrescriptionLine; respond with empty HTML (hx-swap delete)."""
    consultation = get_object_or_404(
        FieldConsultation,
        pk=pk,
        status__in=[FieldConsultation.Status.SUBMITTED, FieldConsultation.Status.APPROVED],
    )
    row = get_object_or_404(PrescriptionLine, pk=row_id, consultation=consultation)
    row.delete()
    return HttpResponse(status=200)


def consultation_approve(request, pk):
    """POST — transition SUBMITTED → APPROVED (staff only)."""
    if not request.user.is_staff:
        messages.error(request, 'Only staff members can approve consultations.')
        return redirect('prescription_view', pk=pk)
    consultation = get_object_or_404(FieldConsultation, pk=pk)
    if request.method == 'POST' and consultation.status == FieldConsultation.Status.SUBMITTED:
        consultation.status = FieldConsultation.Status.APPROVED
        consultation.approved_by = request.user
        consultation.approved_at = timezone.now()
        consultation.save(update_fields=['status', 'approved_by', 'approved_at'])
        messages.success(request, f'{consultation.consultation_number} approved.')
    return redirect('prescription_view', pk=pk)


def prescription_dispense_form(request, pk, row_id):
    """HTMX POST — swap the rx_row with a batch-selection dispense panel."""
    import math
    consultation = get_object_or_404(
        FieldConsultation, pk=pk, status=FieldConsultation.Status.APPROVED,
    )
    rx_line = get_object_or_404(
        PrescriptionLine, pk=row_id, consultation=consultation,
        status=PrescriptionLine.Status.RECOMMENDED,
    )
    batches = list(
        Batch.objects
        .filter(product=rx_line.product, current_quantity__gt=0, is_active=True)
        .order_by('expiry_date', 'mrp')
    )
    for b in batches:
        b.suggested_packs = (
            math.ceil(float(rx_line.total_quantity) / float(b.size))
            if b.size and b.size > 0
            else None
        )
    return render(request, 'farming/partials/rx_dispense_panel.html', {
        'consultation': consultation,
        'rx_line':      rx_line,
        'batches':      batches,
    })


def prescription_dispense_confirm(request, pk, row_id):
    """HTMX POST — validate, execute dispense, return updated rx_row."""
    import math
    from .services import dispense_prescription_line
    consultation = get_object_or_404(
        FieldConsultation, pk=pk, status=FieldConsultation.Status.APPROVED,
    )
    rx_line = get_object_or_404(
        PrescriptionLine, pk=row_id, consultation=consultation,
        status=PrescriptionLine.Status.RECOMMENDED,
    )
    batch_id     = request.POST.get('batch_id')
    pack_qty_str = request.POST.get('pack_qty', '0')

    error = None
    batch = None
    try:
        batch    = Batch.objects.get(pk=batch_id, is_active=True)
        pack_qty = int(pack_qty_str)
        if pack_qty <= 0:
            error = 'Quantity must be at least 1.'
        elif pack_qty > batch.current_quantity:
            error = f'Only {batch.current_quantity} pack(s) in stock for this batch.'
    except (Batch.DoesNotExist, ValueError):
        error = 'Please select a valid batch and enter a quantity.'

    if error:
        batches = list(
            Batch.objects
            .filter(product=rx_line.product, current_quantity__gt=0, is_active=True)
            .order_by('expiry_date', 'mrp')
        )
        for b in batches:
            b.suggested_packs = (
                math.ceil(float(rx_line.total_quantity) / float(b.size))
                if b.size and b.size > 0 else None
            )
        return render(request, 'farming/partials/rx_dispense_panel.html', {
            'consultation': consultation,
            'rx_line':      rx_line,
            'batches':      batches,
            'error':        error,
        })

    dispense_prescription_line(rx_line, batch, pack_qty)
    rx_line.refresh_from_db()
    consultation.refresh_from_db()

    ctx = _rx_form_context(consultation, rx_line)
    return render(request, 'farming/partials/rx_row.html', ctx)


def prescription_row_get(request, pk, row_id):
    """HTMX GET — re-render an rx_row (used when cancelling the dispense panel)."""
    consultation = get_object_or_404(FieldConsultation, pk=pk)
    rx_line      = get_object_or_404(PrescriptionLine, pk=row_id, consultation=consultation)
    ctx          = _rx_form_context(consultation, rx_line)
    return render(request, 'farming/partials/rx_row.html', ctx)


def prescription_pdf_view(request, pk):
    """Render WeasyPrint PDF prescription for a consultation."""
    from django.template.loader import render_to_string
    try:
        from weasyprint import HTML
    except ImportError:
        return HttpResponse('WeasyPrint is not installed.', status=500)

    consultation = get_object_or_404(
        FieldConsultation.objects.select_related('customer', 'agronomist', 'approved_by'),
        pk=pk,
    )
    diagnosis_lines = (
        consultation.diagnosis_lines
        .select_related('pest_disease', 'cultivation_record__crop')
        .order_by('sequence')
    )
    prescription_lines = (
        consultation.prescription_lines
        .select_related('product', 'diagnosis_line__pest_disease')
        .order_by('sequence')
    )
    html_string = render_to_string('farming/prescription_pdf.html', {
        'consultation':       consultation,
        'diagnosis_lines':    diagnosis_lines,
        'prescription_lines': prescription_lines,
    }, request=request)
    pdf_bytes = HTML(
        string=html_string,
        base_url=request.build_absolute_uri('/'),
    ).write_pdf()
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = (
        f'inline; filename="prescription-{consultation.consultation_number}.pdf"'
    )
    return response
