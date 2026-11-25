from django import forms
from django.forms import inlineformset_factory

from .models import Location, Product, Sale, StockTransfer, TransferItem
from .permissions import visible_locations


class SaleForm(forms.ModelForm):
    class Meta:
        model = Sale
        fields = ["location", "product", "quantity", "payment_method", "receipt_number"]

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        shops = Location.objects.none()
        if user is not None:
            shops = visible_locations(user).filter(kind=Location.SHOP)
        self.fields["location"].queryset = shops
        if shops.count() == 1:
            self.fields["location"].empty_label = None

    def clean_quantity(self):
        quantity = self.cleaned_data["quantity"]
        if quantity < 1:
            raise forms.ValidationError("Quantity must be at least 1.")
        return quantity


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ["name", "sku", "category", "price", "low_stock_level"]


class TransferForm(forms.ModelForm):
    class Meta:
        model = StockTransfer
        fields = ["from_location", "to_location", "note"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        active = Location.objects.filter(is_active=True)
        self.fields["from_location"].queryset = active
        self.fields["to_location"].queryset = active


class TransferItemForm(forms.ModelForm):
    class Meta:
        model = TransferItem
        fields = ["product", "quantity_sent"]

    def clean_quantity_sent(self):
        quantity = self.cleaned_data["quantity_sent"]
        if quantity < 1:
            raise forms.ValidationError("Quantity must be at least 1.")
        return quantity


TransferItemFormSet = inlineformset_factory(
    StockTransfer,
    TransferItem,
    form=TransferItemForm,
    extra=4,
    can_delete=False,
)