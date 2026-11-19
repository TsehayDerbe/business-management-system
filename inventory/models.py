from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import models


class Product(models.Model):
    name = models.CharField(max_length=200)
    sku = models.CharField(max_length=50, unique=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveIntegerField(default=0)
    low_stock_level = models.PositiveIntegerField(default=5)
    created_at = models.DateTimeField(auto_now_add=True)

    def is_low_stock(self):
        return self.quantity <= self.low_stock_level

    def __str__(self):
        return f"{self.name} ({self.sku})"


class Sale(models.Model):
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField()
    total_price = models.DecimalField(max_digits=12, decimal_places=2, editable=False)
    sold_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    sold_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        if not self.pk and self.product_id and self.quantity:
            if self.quantity > self.product.quantity:
                raise ValidationError(
                    f"Only {self.product.quantity} units of {self.product.name} in stock."
                )

    def save(self, *args, **kwargs):
        if not self.pk:
            if self.quantity > self.product.quantity:
                raise ValueError("Not enough stock for this sale.")
            self.total_price = self.product.price * self.quantity
            self.product.quantity -= self.quantity
            self.product.save()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.quantity} x {self.product.name}"