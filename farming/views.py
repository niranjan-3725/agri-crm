from django.views.generic import ListView, CreateView, UpdateView, DeleteView
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse_lazy
from django.contrib import messages
from django.db.models import Count, Q
from django.utils import timezone
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_GET

from master_data.models import Customer
from .models import (
    CropMaster, CropProductNorm, CultivationRecord,
    FieldConsultation, DiagnosisLine, PrescriptionLine,
)
from .forms import (
    CropMasterForm, CultivationRecordForm,
    FieldConsultationForm, DiagnosisLineFormSet, DiagnosisLineForm,
    PrescriptionLineFormSet, PrescriptionLineForm,
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


def _generate_consultation_number():
    """Thread-safe sequential document number: FC-YYYYMMDD-NNNN."""
    today_str = timezone.now().strftime('%Y%m%d')
    prefix = f'FC-{today_str}-'
    last = (
        FieldConsultation.objects
        .filter(consultation_number__startswith=prefix)
        .order_by('-consultation_number')
        .first()
    )
    seq = (int(last.consultation_number.split('-')[-1]) + 1) if last else 1
    return f'{prefix}{seq:04d}'


def consultation_create_view(request, customer_pk=None):
    """Create a new FieldConsultation with inline Diagnosis and Prescription rows."""
    customer = get_object_or_404(Customer, pk=customer_pk) if customer_pk else None

    if request.method == 'POST':
        form = FieldConsultationForm(request.POST)
        dx_formset = DiagnosisLineFormSet(request.POST, request.FILES, prefix='dx')
        rx_formset = PrescriptionLineFormSet(request.POST, request.FILES, prefix='rx')

        if form.is_valid() and dx_formset.is_valid() and rx_formset.is_valid():
            consultation = form.save(commit=False)
            consultation.consultation_number = _generate_consultation_number()
            consultation.save()

            dx_formset.instance = consultation
            dx_formset.save()

            rx_formset.instance = consultation
            rx_formset.save()

            messages.success(
                request,
                f'Consultation {consultation.consultation_number} saved successfully.'
            )
            return redirect('consultation_list')
    else:
        initial = {'customer': customer} if customer else {}
        form = FieldConsultationForm(initial=initial)
        dx_formset = DiagnosisLineFormSet(
            prefix='dx',
            queryset=DiagnosisLine.objects.none(),
        )
        rx_formset = PrescriptionLineFormSet(
            prefix='rx',
            queryset=PrescriptionLine.objects.none(),
        )

    return render(request, 'farming/consultation_form.html', {
        'form':        form,
        'dx_formset':  dx_formset,
        'rx_formset':  rx_formset,
        'customer':    customer,
        'page_title':  'New Consultation',
        'norm_crops':  CropMaster.objects.filter(is_active=True).order_by('name'),
    })


@require_GET
def add_diagnosis_row(request):
    """HTMX: return a single blank DiagnosisLine form row fragment."""
    form_index = int(request.GET.get('form_index', 0))
    customer_pk = request.GET.get('customer_pk')
    customer = Customer.objects.filter(pk=customer_pk).first() if customer_pk else None
    form = DiagnosisLineForm(prefix=f'dx-{form_index}', customer=customer)
    return render(request, 'farming/partials/diagnosis_row.html', {
        'form':       form,
        'form_index': form_index,
    })


@require_GET
def add_prescription_row(request):
    """HTMX: return a single blank PrescriptionLine form row fragment."""
    form_index = int(request.GET.get('form_index', 0))
    form = PrescriptionLineForm(prefix=f'rx-{form_index}')
    return render(request, 'farming/partials/prescription_row.html', {
        'form':       form,
        'form_index': form_index,
        'norm_crops': CropMaster.objects.filter(is_active=True).order_by('name'),
    })


@require_GET
def norm_suggest_api(request):
    """JSON API: return CropProductNorm dosage for a (crop, product) pair."""
    crop_id    = request.GET.get('crop_id')
    product_id = request.GET.get('product_id')

    if not crop_id or not product_id:
        return JsonResponse({'found': False})

    norm = CropProductNorm.objects.filter(
        crop_id=crop_id,
        product_id=product_id,
    ).first()

    if norm:
        return JsonResponse({
            'found':            True,
            'application_rate': str(norm.application_rate),
            'unit':             norm.unit,
        })
    return JsonResponse({'found': False})
