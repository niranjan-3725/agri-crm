from django import forms
from django.utils import timezone

from .models import (
    CropMaster, CropProductNorm, CultivationRecord,
    AgronomistProfile, FieldConsultation, DiagnosisLine,
    PrescriptionLine, PestDiseaseLibrary,
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
            'dosage_per_acre', 'dosage_unit', 'total_quantity',
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
                .select_related('pest_disease')
            )
        self.fields['diagnosis_line'].required = False
        self.fields['notes'].widget = forms.Textarea(
            attrs={'class': _SMALL, 'rows': 2, 'placeholder': 'Timing notes, warnings, etc.'}
        )
        self.fields['dosage_per_acre'].widget.attrs.update({
            'step': '0.001', 'min': '0', 'placeholder': '0.000',
            'x-model.number': 'dosage',
        })
        self.fields['total_quantity'].widget.attrs.update({
            'step': '0.001', 'min': '0', 'readonly': True,
            ':value': 'computedTotal',
            'class': _SMALL + ' bg-gray-50 text-gray-500 cursor-not-allowed',
        })


PrescriptionLineFormSet = forms.inlineformset_factory(
    FieldConsultation,
    PrescriptionLine,
    form=PrescriptionLineForm,
    fields=[
        'diagnosis_line', 'product', 'dosage_per_acre', 'dosage_unit',
        'total_quantity', 'application_method', 'timing', 'frequency', 'notes',
    ],
    extra=0,
    can_delete=True,
)
