from django import forms
from .models import Customer, Supplier, Category, Manufacturer, Product, Village


class VillageForm(forms.ModelForm):
    class Meta:
        model = Village
        fields = ['name', 'is_active']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['name'].widget.attrs.update({
            'class': 'w-full border border-gray-300 rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-emerald-500 focus:ring-2 focus:ring-emerald-500/10',
            'placeholder': 'e.g. Nagpur, Wardha, Amravati',
            'autofocus': True,
        })
        self.fields['is_active'].widget.attrs.update({
            'class': 'w-4 h-4 rounded border-gray-300 text-emerald-600 focus:ring-emerald-500',
        })

    def clean_name(self):
        name = self.cleaned_data.get('name', '').strip()
        if not name:
            raise forms.ValidationError("Village name is required.")
        # Uniqueness check (case-insensitive), exclude self when editing
        qs = Village.objects.filter(name__iexact=name)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError(f'"{name}" already exists in the village master.')
        return name


class StyledFormMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields:
            self.fields[field].widget.attrs.update({
                'class': 'w-full border border-gray-300 p-2 rounded focus:outline-none focus:border-blue-500'
            })


class CustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = ['name', 'mobile_no', 'village', 'address', 'gstin', 'father_name', 'land_size']

    def clean_mobile_no(self):
        mobile_no = self.cleaned_data.get('mobile_no')
        if not mobile_no:
            return mobile_no

        if not mobile_no.isdigit():
            raise forms.ValidationError("Mobile number must contain only digits.")

        if len(mobile_no) != 10:
            raise forms.ValidationError("Mobile number must be exactly 10 digits.")

        # Uniqueness — exclude self when editing (Rule 31)
        query = Customer.objects.filter(mobile_no=mobile_no)
        if self.instance.pk:
            query = query.exclude(pk=self.instance.pk)
        if query.exists():
            raise forms.ValidationError("This mobile number is already registered.")

        return mobile_no

class SupplierForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Supplier
        fields = ['name', 'gstin', 'phone', 'address', 'is_distributor']

class CategoryForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Category
        fields = ['name', 'cgst_rate', 'sgst_rate', 'igst_rate']

class ManufacturerForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Manufacturer
        fields = ['name', 'description']

class ProductForm(forms.ModelForm):
    """Product form with Identity Pair uniqueness validation (name + manufacturer)."""

    class Meta:
        model = Product
        fields = ['name', 'hsn_code', 'unit_type', 'category', 'manufacturer']

    def clean(self):
        cleaned_data = super().clean()
        name = cleaned_data.get('name', '').strip()
        manufacturer = cleaned_data.get('manufacturer')

        if name and manufacturer:
            qs = Product.objects.filter(name__iexact=name, manufacturer=manufacturer)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError(
                    f'"{name}" from this manufacturer already exists. '
                    'Products are uniquely identified by Name + Manufacturer.'
                )
        return cleaned_data
