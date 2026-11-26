from django import forms
from django.forms import inlineformset_factory
from django.utils import timezone

from .models import (
    DailyClosing,
    Location,
    Product,
    Sale,
    StockTransfer,
    TransferItem,
)
from .permissions import visible_locations


def _shops_for(user):
    if user is None:
        return Location.objects.none()
    return visible_locations(user).filter(kind=Location.SHOP)


class SaleForm(forms.ModelForm):
    class Meta:
        model = Sale
        fields = ["location", "product", "quantity", "payment_method", "receipt_number"]

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        shops = _shops_for(user)
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


class ClosingForm(forms.ModelForm):
    class Meta:
        model = DailyClosing
        fields = ["location", "date", "counted_cash", "note"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        }

    def __init__(self, *args, user=None, **kwargs):
        initial = kwargs.setdefault("initial", {})
        initial.setdefault("date", timezone.localdate())
        super().__init__(*args, **kwargs)
        shops = _shops_for(user)
        self.fields["location"].queryset = shops
        if shops.count() == 1:
            self.fields["location"].empty_label = None
        self.fields["counted_cash"].label = "Cash counted in the till (ETB)"

    def clean_date(self):
        day = self.cleaned_data["date"]
        if day > timezone.localdate():
            raise forms.ValidationError("You can't close a day in the future.")
        return day

    def clean_counted_cash(self):
        counted = self.cleaned_data["counted_cash"]
        if counted < 0:
            raise forms.ValidationError("The amount can't be negative.")
        return counted

    def clean(self):
        cleaned = super().clean()
        location = cleaned.get("location")
        day = cleaned.get("date")
        counted = cleaned.get("counted_cash")
        if location and day and counted is not None:
            expected = DailyClosing.cash_sales_total(location, day)
            if counted != expected and not (cleaned.get("note") or "").strip():
                self.add_error(
                    "note",
                    "Your count does not match the recorded cash sales. "
                    "Recount the cash, or explain the difference here.",
                )
        return cleaned