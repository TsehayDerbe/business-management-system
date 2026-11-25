from django.contrib import admin

from .models import (
    Location,
    Product,
    Region,
    Sale,
    StockLevel,
    StockMovement,
    UserProfile,
)


@admin.register(Region)
class RegionAdmin(admin.ModelAdmin):
    list_display = ("name",)


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "region", "city", "is_active")
    list_filter = ("kind", "region", "city")


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "sku", "category", "price", "low_stock_level")
    search_fields = ("name", "sku")
    list_filter = ("category",)


@admin.register(StockLevel)
class StockLevelAdmin(admin.ModelAdmin):
    list_display = ("product", "location", "quantity")
    list_filter = ("location",)

    def save_model(self, request, obj, form, change):
        old_quantity = 0
        if change:
            old_quantity = StockLevel.objects.get(pk=obj.pk).quantity
        super().save_model(request, obj, form, change)
        delta = obj.quantity - old_quantity
        if delta:
            StockMovement.objects.create(
                product=obj.product,
                location=obj.location,
                kind=StockMovement.ADJUSTMENT,
                change=delta,
                balance_after=obj.quantity,
                created_by=request.user,
                note="Set in admin",
            )


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "location",
        "product",
        "kind",
        "change",
        "balance_after",
        "reference",
        "created_by",
    )
    list_filter = ("location", "kind", "product")
    search_fields = ("reference", "note")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "region", "location")
    list_filter = ("role", "region")


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = (
        "product",
        "location",
        "quantity",
        "total_price",
        "payment_method",
        "receipt_number",
        "sold_by",
        "sold_at",
    )
    list_filter = ("location", "payment_method", "sold_at")

    def save_model(self, request, obj, form, change):
        if not change and not obj.sold_by:
            obj.sold_by = request.user
        super().save_model(request, obj, form, change)