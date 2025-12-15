from django import forms
from .models import Customer, Supplier, Category, Manufacturer, Product

class StyledFormMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields:
            self.fields[field].widget.attrs.update({
                'class': 'w-full border border-gray-300 p-2 rounded focus:outline-none focus:border-blue-500'
            })

class CustomerForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Customer
        fields = ['name', 'mobile_no', 'city', 'address', 'gstin']

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

class ProductForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Product
        fields = ['name', 'hsn_code', 'unit_type', 'category', 'manufacturer']
        widgets = {
             'category': forms.Select(attrs={'class': 'w-full border border-gray-300 p-2 rounded focus:outline-none focus:border-blue-500'}),
             'manufacturer': forms.Select(attrs={'class': 'w-full border border-gray-300 p-2 rounded focus:outline-none focus:border-blue-500'}),
             'unit_type': forms.Select(attrs={'class': 'w-full border border-gray-300 p-2 rounded focus:outline-none focus:border-blue-500'}),
        }
