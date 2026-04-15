from django import forms
from django.utils import timezone

from .models import (
    CropMaster, CropProductNorm, CultivationRecord,
    AgronomistProfile, FieldConsultation, DiagnosisLine,
    ConsultationPhoto, PrescriptionLine, PestDiseaseLibrary, PestDiseaseCropLink,
)


class CropMasterForm(forms.ModelForm):
    class Meta:
        model = CropMaster
        fields = ['name', 'crop_type', 'is_active', 'description']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        base = 'w-full border border-gray-300 rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-green-500 focus:ring-2 focus:ring-green-500/10'
        self.fields['name'].widget.attrs.update({
            'class': base,
            'placeholder': 'e.g. Tomato, Paddy, Cotton',
            'autofocus': True,
        })
        self.fields['crop_type'].widget.attrs.update({'class': base})
        self.fields['description'].widget = forms.Textarea(attrs={
            'class': base,
            'rows': 3,
            'placeholder': 'Optional notes about this crop...',
        })
        self.fields['is_active'].widget.attrs.update({
            'class': 'w-4 h-4 rounded border-gray-300 text-green-600 focus:ring-green-500',
        })

    def clean_name(self):
        name = self.cleaned_data.get('name', '').strip()
        if not name:
            raise forms.ValidationError("Crop name is required.")
        qs = CropMaster.objects.filter(name__iexact=name)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError(f'"{name}" already exists in the crop master.')
        return name


class CropProductNormForm(forms.ModelForm):
    class Meta:
        model = CropProductNorm
        fields = ['product', 'application_rate', 'unit', 'notes']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        base = 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-green-500'
        for field in self.fields:
            self.fields[field].widget.attrs.update({'class': base})


CropProductNormFormSet = forms.inlineformset_factory(
    CropMaster,
    CropProductNorm,
    form=CropProductNormForm,
    fields=['product', 'application_rate', 'unit', 'notes'],
    extra=1,
    can_delete=True,
)


class CultivationRecordForm(forms.ModelForm):
    class Meta:
        model = CultivationRecord
        fields = ['crop', 'acreage', 'season', 'season_year', 'status', 'notes']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        base = 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-green-500'
        for field in self.fields:
            self.fields[field].widget.attrs.update({'class': base})
        # Default season_year to current year
        if not self.instance.pk:
            self.fields['season_year'].initial = timezone.now().year
        self.fields['notes'].widget = forms.Textarea(attrs={
            'class': base, 'rows': 2, 'placeholder': 'Optional notes...'
        })


# ── Agronomist Profile ────────────────────────────────────────────────────────

_FIELD_BASE = 'w-full h-14 bg-gray-50 hover:bg-white border border-transparent hover:border-gray-200 focus:bg-white focus:border-blue-500/20 rounded-2xl px-5 text-base font-medium transition-all outline-none focus:shadow-lg focus:shadow-blue-500/5 placeholder-gray-300'
_FIELD_SELECT = 'w-full h-14 bg-gray-50 hover:bg-white border border-transparent hover:border-gray-200 focus:bg-white focus:border-blue-500/20 rounded-2xl px-5 text-base font-medium transition-all outline-none'


class AgronomistProfileForm(forms.ModelForm):
    class Meta:
        model = AgronomistProfile
        fields = ['employee_id', 'name', 'designation', 'zone', 'phone', 'is_active']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for fname in ['employee_id', 'name', 'zone', 'phone']:
            self.fields[fname].widget.attrs.update({'class': _FIELD_BASE})
        self.fields['designation'].widget.attrs.update({'class': _FIELD_SELECT})
        self.fields['is_active'].widget.attrs.update({
            'class': 'w-5 h-5 rounded border-gray-300 text-green-600 focus:ring-green-500',
        })
        self.fields['employee_id'].widget.attrs['placeholder'] = 'e.g. EMP-001'
        self.fields['name'].widget.attrs['placeholder'] = 'Full name'
        self.fields['zone'].widget.attrs['placeholder'] = 'e.g. North Zone, Vidarbha'
        self.fields['phone'].widget.attrs['placeholder'] = '10-digit mobile'

    def clean_employee_id(self):
        eid = self.cleaned_data.get('employee_id', '').strip().upper()
        qs = AgronomistProfile.objects.filter(employee_id__iexact=eid)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError(f'Employee ID "{eid}" is already taken.')
        return eid


# ── Pest / Disease Library ────────────────────────────────────────────────────

class PestDiseaseLibraryForm(forms.ModelForm):
    affected_crops = forms.ModelMultipleChoiceField(
        queryset=CropMaster.objects.filter(is_active=True).order_by('name'),
        required=False,
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'space-y-1'}),
        help_text='Select all crops affected by this pest / disease.',
    )

    class Meta:
        model = PestDiseaseLibrary
        fields = ['name', 'local_name', 'type', 'symptoms',
                  'management_notes', 'photo', 'is_active']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Pre-populate affected_crops from existing through-model rows
        if self.instance.pk:
            self.fields['affected_crops'].initial = (
                CropMaster.objects.filter(
                    pest_disease_links__pest_disease=self.instance
                )
            )
        for fname in ['name', 'local_name']:
            self.fields[fname].widget.attrs.update({'class': _FIELD_BASE})
        self.fields['name'].widget.attrs['placeholder'] = 'e.g. Aphids, Early Blight'
        self.fields['local_name'].widget.attrs['placeholder'] = 'Local / regional name (optional)'
        self.fields['type'].widget.attrs.update({'class': _FIELD_SELECT})
        for fname in ['symptoms', 'management_notes']:
            self.fields[fname].widget = forms.Textarea(attrs={
                'class': 'w-full bg-gray-50 hover:bg-white border border-transparent hover:border-gray-200 focus:bg-white focus:border-blue-500/20 rounded-2xl p-5 text-base font-medium transition-all outline-none resize-none placeholder-gray-300',
                'rows': 3,
            })
        self.fields['symptoms'].widget.attrs['placeholder'] = 'Describe visible symptoms…'
        self.fields['management_notes'].required = False
        self.fields['is_active'].widget.attrs.update({
            'class': 'w-5 h-5 rounded border-gray-300 text-green-600 focus:ring-green-500',
        })

    def save_affected_crops(self, instance):
        """Sync PestDiseaseCropLink rows from the affected_crops field."""
        selected = set(self.cleaned_data.get('affected_crops', []))
        existing = set(
            CropMaster.objects.filter(pest_disease_links__pest_disease=instance)
        )
        for crop in selected - existing:
            PestDiseaseCropLink.objects.get_or_create(pest_disease=instance, crop=crop)
        for crop in existing - selected:
            PestDiseaseCropLink.objects.filter(pest_disease=instance, crop=crop).delete()


# ── Consultation Photo ────────────────────────────────────────────────────────

class ConsultationPhotoForm(forms.ModelForm):
    class Meta:
        model = ConsultationPhoto
        fields = ['photo', 'caption']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['caption'].widget.attrs.update({
            'class': 'w-full border border-gray-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:border-green-500',
            'placeholder': 'Optional caption…',
        })


# ── Ag-CDSS Phase 1 Forms ─────────────────────────────────────────────────────

_BASE  = 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-green-500 focus:ring-2 focus:ring-green-500/10'
_SMALL = 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-green-500'


class FieldConsultationForm(forms.ModelForm):
    class Meta:
        model = FieldConsultation
        fields = [
            'customer', 'agronomist', 'field_visit',
            'consultation_date', 'consultation_time',
            'weather_conditions', 'crop_stage', 'general_observations',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            field.widget.attrs.setdefault('class', _BASE)
        self.fields['consultation_date'].widget = forms.DateInput(
            attrs={'class': _BASE, 'type': 'date'}
        )
        self.fields['consultation_time'].widget = forms.TimeInput(
            attrs={'class': _BASE, 'type': 'time'}
        )
        self.fields['general_observations'].widget = forms.Textarea(
            attrs={'class': _BASE, 'rows': 3, 'placeholder': 'General field conditions, crop health overview…'}
        )
        self.fields['agronomist'].queryset = AgronomistProfile.objects.filter(is_active=True)
        self.fields['agronomist'].required = False
        self.fields['field_visit'].required = False
        self.fields['consultation_time'].required = False


class DiagnosisLineForm(forms.ModelForm):
    class Meta:
        model = DiagnosisLine
        fields = [
            'cultivation_record', 'pest_disease',
            'severity', 'affected_area_acres', 'symptoms_observed',
        ]

    def __init__(self, *args, customer=None, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            field.widget.attrs.setdefault('class', _SMALL)
        if customer:
            self.fields['cultivation_record'].queryset = (
                CultivationRecord.objects
                .filter(customer=customer, status='ACTIVE')
                .select_related('crop')
                .order_by('crop__name')
            )
        self.fields['cultivation_record'].required = False
        self.fields['symptoms_observed'].widget = forms.Textarea(
            attrs={'class': _SMALL, 'rows': 2, 'placeholder': 'Describe what you observed…'}
        )
        self.fields['pest_disease'].queryset = PestDiseaseLibrary.objects.filter(is_active=True).order_by('type', 'name')
        # Data attrs needed by Alpine norm-suggest bridge
        self.fields['cultivation_record'].widget.attrs['data-role'] = 'cultivation-select'
        self.fields['affected_area_acres'].widget.attrs.update({
            'step': '0.01', 'min': '0', 'placeholder': '0.00',
        })


DiagnosisLineFormSet = forms.inlineformset_factory(
    FieldConsultation,
    DiagnosisLine,
    form=DiagnosisLineForm,
    fields=['cultivation_record', 'pest_disease', 'severity', 'affected_area_acres', 'symptoms_observed'],
    extra=0,
    can_delete=True,
)


class PrescriptionLineForm(forms.ModelForm):
    class Meta:
        model = PrescriptionLine
        fields = [
            'diagnosis_line', 'product',
            'dosage_per_acre', 'dosage_unit',
            'application_method', 'timing', 'frequency', 'notes',
        ]

    def __init__(self, *args, consultation=None, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            field.widget.attrs.setdefault('class', _SMALL)
        if consultation:
            self.fields['diagnosis_line'].queryset = (
                DiagnosisLine.objects
                .filter(consultation=consultation)
                .select_related('pest_disease', 'cultivation_record__crop')
            )
        self.fields['diagnosis_line'].required = False
        self.fields['notes'].widget = forms.Textarea(
            attrs={'class': _SMALL, 'rows': 2, 'placeholder': 'Timing notes, warnings, etc.'}
        )
        self.fields['dosage_per_acre'].widget.attrs.update({
            'step': '0.001', 'min': '0', 'placeholder': '0.000',
            'x-model.number': 'dosage',
        })
        # Sync Alpine dxId when diagnosis_line changes
        self.fields['diagnosis_line'].widget.attrs['x-model'] = 'dxId'


PrescriptionLineFormSet = forms.inlineformset_factory(
    FieldConsultation,
    PrescriptionLine,
    form=PrescriptionLineForm,
    fields=[
        'diagnosis_line', 'product', 'dosage_per_acre', 'dosage_unit',
        'application_method', 'timing', 'frequency', 'notes',
    ],
    extra=0,
    can_delete=True,
)
