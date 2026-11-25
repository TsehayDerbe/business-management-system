from django import forms

from .models import Product, Sale


class SaleForm(forms.ModelForm):
    class Meta:
        model = Sale
        fields = ["location", "product", "quantity", "payment_method", "receipt_number"]

    def clean_quantity(self):
        quantity = self.cleaned_data["quantity"]
        if quantity < 1:
            raise forms.ValidationError("Quantity must be at least 1.")
        return quantity


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ["name", "sku", "category", "price", "low_stock_level"]