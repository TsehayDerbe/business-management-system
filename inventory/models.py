from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import models, transaction


class Region(models.Model):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Location(models.Model):
    HEAD_OFFICE = "HQ"
    SHOP = "SHOP"
    KIND_CHOICES = [
        (HEAD_OFFICE, "Head office warehouse"),
        (SHOP, "Shop"),
    ]

    name = models.CharField(max_length=150, unique=True)
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default=SHOP)
    region = models.ForeignKey(
        Region,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="locations",
    )
    city = models.CharField(max_length=100, blank=True)
    address = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def clean(self):
        if self.kind == self.SHOP and not self.region_id:
            raise ValidationError("A shop must belong to a region.")

    def __str__(self):
        return self.name


class Product(models.Model):
    CATEGORY_CHOICES = [
        ("SIM", "SIM card"),
        ("AIRTIME", "Airtime / voucher"),
        ("DEVICE", "Device"),
        ("ACCESSORY", "Accessory"),
    ]

    name = models.CharField(max_length=200)
    sku = models.CharField(max_length=50, unique=True)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default="SIM")
    price = models.DecimalField(max_digits=10, decimal_places=2)
    low_stock_level = models.PositiveIntegerField(default=5)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.sku})"


class StockLevel(models.Model):
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name="stock_levels"
    )
    location = models.ForeignKey(
        Location, on_delete=models.PROTECT, related_name="stock_levels"
    )
    quantity = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ("product", "location")
        ordering = ["location__name", "product__name"]

    def is_low(self):
        return self.quantity <= self.product.low_stock_level

    def __str__(self):
        return f"{self.product.name} @ {self.location.name}: {self.quantity}"


class StockMovement(models.Model):
    RECEIPT = "RECEIPT"
    SALE = "SALE"
    TRANSFER_OUT = "TRANSFER_OUT"
    TRANSFER_IN = "TRANSFER_IN"
    ADJUSTMENT = "ADJUSTMENT"
    KIND_CHOICES = [
        (RECEIPT, "Stock received"),
        (SALE, "Sale"),
        (TRANSFER_OUT, "Transfer out"),
        (TRANSFER_IN, "Transfer in"),
        (ADJUSTMENT, "Adjustment"),
    ]

    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name="movements"
    )
    location = models.ForeignKey(
        Location, on_delete=models.PROTECT, related_name="movements"
    )
    kind = models.CharField(max_length=15, choices=KIND_CHOICES)
    change = models.IntegerField(help_text="Positive adds stock, negative removes it.")
    balance_after = models.PositiveIntegerField()
    reference = models.CharField(max_length=100, blank=True)
    note = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.get_kind_display()} {self.change:+d} {self.product.name} @ {self.location.name}"


def apply_stock_change(product, location, delta, kind, user=None, reference="", note=""):
    """Change stock at a location and record the movement. Never goes below zero."""
    with transaction.atomic():
        stock, _ = StockLevel.objects.select_for_update().get_or_create(
            product=product, location=location
        )
        new_quantity = stock.quantity + delta
        if new_quantity < 0:
            raise ValueError("Not enough stock at this location.")
        stock.quantity = new_quantity
        stock.save()
        return StockMovement.objects.create(
            product=product,
            location=location,
            kind=kind,
            change=delta,
            balance_after=new_quantity,
            reference=reference,
            note=note,
            created_by=user,
        )


class UserProfile(models.Model):
    ADMIN = "ADMIN"
    STOCK = "STOCK"
    OPS = "OPS"
    SHOP = "SHOP"
    ROLE_CHOICES = [
        (ADMIN, "Head office admin"),
        (STOCK, "Stock controller"),
        (OPS, "Operations team"),
        (SHOP, "Sales manager (shop)"),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default=SHOP)
    region = models.ForeignKey(
        Region, on_delete=models.SET_NULL, null=True, blank=True
    )
    location = models.ForeignKey(
        Location, on_delete=models.SET_NULL, null=True, blank=True
    )

    def __str__(self):
        return f"{self.user.username} ({self.get_role_display()})"


class Sale(models.Model):
    CASH = "CASH"
    MOBILE = "MOBILE"
    BANK = "BANK"
    PAYMENT_CHOICES = [
        (CASH, "Cash"),
        (MOBILE, "Mobile money"),
        (BANK, "Bank transfer"),
    ]

    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    location = models.ForeignKey(Location, on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField()
    total_price = models.DecimalField(max_digits=12, decimal_places=2, editable=False)
    payment_method = models.CharField(
        max_length=10, choices=PAYMENT_CHOICES, default=CASH
    )
    receipt_number = models.CharField(
        max_length=100,
        blank=True,
        help_text="Number printed on the cash register's receipt.",
    )
    sold_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    sold_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        if not self.pk and self.product_id and self.location_id and self.quantity:
            available = (
                StockLevel.objects.filter(product=self.product, location=self.location)
                .values_list("quantity", flat=True)
                .first()
                or 0
            )
            if self.quantity > available:
                raise ValidationError(
                    f"Only {available} units of {self.product.name} at {self.location.name}."
                )

    @transaction.atomic
    def save(self, *args, **kwargs):
        if self.pk:
            return super().save(*args, **kwargs)
        self.total_price = self.product.price * self.quantity
        super().save(*args, **kwargs)
        apply_stock_change(
            self.product,
            self.location,
            -self.quantity,
            StockMovement.SALE,
            user=self.sold_by,
            reference=f"Sale #{self.pk}",
        )

    def __str__(self):
        return f"{self.quantity} x {self.product.name} @ {self.location.name}"