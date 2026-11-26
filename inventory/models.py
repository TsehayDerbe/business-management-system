from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Sum
from django.utils import timezone


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

    CLOSED_MESSAGE = (
        "Today's cash for this shop is already closed. New sales can't be added."
    )

    def day_is_closed(self):
        return DailyClosing.objects.filter(
            location=self.location, date=timezone.localdate()
        ).exists()

    def clean(self):
        if not self.pk and self.product_id and self.location_id and self.quantity:
            if self.day_is_closed():
                raise ValidationError(self.CLOSED_MESSAGE)
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
        if self.day_is_closed():
            raise ValueError(self.CLOSED_MESSAGE)
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


class StockTransfer(models.Model):
    DRAFT = "DRAFT"
    DISPATCHED = "DISPATCHED"
    RECEIVED = "RECEIVED"
    DISCREPANCY = "DISCREPANCY"
    STATUS_CHOICES = [
        (DRAFT, "Draft"),
        (DISPATCHED, "Dispatched (in transit)"),
        (RECEIVED, "Received"),
        (DISCREPANCY, "Received with discrepancy"),
    ]

    reference = models.CharField(max_length=20, blank=True, editable=False)
    from_location = models.ForeignKey(
        Location, on_delete=models.PROTECT, related_name="transfers_out"
    )
    to_location = models.ForeignKey(
        Location, on_delete=models.PROTECT, related_name="transfers_in"
    )
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=DRAFT)
    note = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    dispatched_at = models.DateTimeField(null=True, blank=True)
    received_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    received_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def clean(self):
        if self.from_location_id and self.from_location_id == self.to_location_id:
            raise ValidationError("Source and destination must be different.")

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.reference:
            self.reference = f"TR-{self.pk:05d}"
            super().save(update_fields=["reference"])

    @transaction.atomic
    def dispatch(self, user):
        if self.status != self.DRAFT:
            raise ValueError("Only draft transfers can be dispatched.")
        items = list(self.items.select_related("product"))
        if not items:
            raise ValueError("Add at least one item first.")
        for item in items:
            apply_stock_change(
                item.product,
                self.from_location,
                -item.quantity_sent,
                StockMovement.TRANSFER_OUT,
                user=user,
                reference=self.reference,
                note=f"To {self.to_location.name}",
            )
        self.status = self.DISPATCHED
        self.dispatched_at = timezone.now()
        self.save(update_fields=["status", "dispatched_at"])

    @transaction.atomic
    def receive(self, user):
        if self.status != self.DISPATCHED:
            raise ValueError("Only dispatched transfers can be received.")
        items = list(self.items.select_related("product"))
        if any(item.quantity_received is None for item in items):
            raise ValueError("Enter the received quantity for every item first.")
        has_difference = False
        for item in items:
            if item.quantity_received > item.quantity_sent:
                raise ValueError(
                    f"{item.product.name}: received more than was sent."
                )
            if item.quantity_received:
                apply_stock_change(
                    item.product,
                    self.to_location,
                    item.quantity_received,
                    StockMovement.TRANSFER_IN,
                    user=user,
                    reference=self.reference,
                    note=f"From {self.from_location.name}",
                )
            if item.quantity_received != item.quantity_sent:
                has_difference = True
        self.status = self.DISCREPANCY if has_difference else self.RECEIVED
        self.received_by = user
        self.received_at = timezone.now()
        self.save(update_fields=["status", "received_by", "received_at"])

    def __str__(self):
        return f"{self.reference or 'New transfer'}: {self.from_location} to {self.to_location}"


class TransferItem(models.Model):
    transfer = models.ForeignKey(
        StockTransfer, on_delete=models.CASCADE, related_name="items"
    )
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    quantity_sent = models.PositiveIntegerField()
    quantity_received = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        unique_together = ("transfer", "product")

    @property
    def difference(self):
        if self.quantity_received is None:
            return None
        return self.quantity_sent - self.quantity_received

    def __str__(self):
        return f"{self.product.name}: {self.quantity_sent}"


class DailyClosing(models.Model):
    location = models.ForeignKey(
        Location, on_delete=models.PROTECT, related_name="closings"
    )
    date = models.DateField()
    expected_cash = models.DecimalField(
        max_digits=12, decimal_places=2, editable=False
    )
    counted_cash = models.DecimalField(max_digits=12, decimal_places=2)
    difference = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        editable=False,
        help_text="Counted minus expected. Negative means cash is missing.",
    )
    note = models.CharField(max_length=255, blank=True)
    closed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    closed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("location", "date")
        ordering = ["-date", "location__name"]

    @staticmethod
    def cash_sales_total(location, day):
        total = Sale.objects.filter(
            location=location, payment_method=Sale.CASH, sold_at__date=day
        ).aggregate(total=Sum("total_price"))["total"]
        return total or Decimal("0")

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValueError("A closed day cannot be changed.")
        self.expected_cash = self.cash_sales_total(self.location, self.date)
        self.difference = self.counted_cash - self.expected_cash
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.location.name} {self.date}: {self.difference:+}"