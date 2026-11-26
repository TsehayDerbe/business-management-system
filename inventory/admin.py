from django.contrib import admin, messages

from .models import (
    DailyClosing,
    Location,
    Product,
    Region,
    Sale,
    StockLevel,
    StockMovement,
    StockTransfer,
    TransferItem,
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


class TransferItemInline(admin.TabularInline):
    model = TransferItem
    extra = 1

    def get_readonly_fields(self, request, obj=None):
        if obj is None or obj.status == StockTransfer.DRAFT:
            return ("quantity_received",)
        if obj.status == StockTransfer.DISPATCHED:
            return ("product", "quantity_sent")
        return ("product", "quantity_sent", "quantity_received", "difference")

    def has_add_permission(self, request, obj=None):
        return obj is None or obj.status == StockTransfer.DRAFT

    def has_delete_permission(self, request, obj=None):
        return obj is None or obj.status == StockTransfer.DRAFT


@admin.register(StockTransfer)
class StockTransferAdmin(admin.ModelAdmin):
    list_display = (
        "reference",
        "from_location",
        "to_location",
        "status",
        "created_at",
        "dispatched_at",
        "received_at",
    )
    list_filter = ("status", "to_location")
    inlines = [TransferItemInline]
    actions = ["dispatch_selected", "receive_selected"]

    def get_readonly_fields(self, request, obj=None):
        base = (
            "reference",
            "status",
            "created_by",
            "created_at",
            "dispatched_at",
            "received_by",
            "received_at",
        )
        if obj is not None and obj.status != StockTransfer.DRAFT:
            return base + ("from_location", "to_location", "note")
        return base

    def has_delete_permission(self, request, obj=None):
        return obj is not None and obj.status == StockTransfer.DRAFT

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    @admin.action(description="Dispatch selected transfers (take stock out of the source)")
    def dispatch_selected(self, request, queryset):
        for transfer in queryset:
            try:
                transfer.dispatch(request.user)
                self.message_user(
                    request, f"{transfer.reference} dispatched.", messages.SUCCESS
                )
            except ValueError as error:
                self.message_user(
                    request, f"{transfer.reference}: {error}", messages.ERROR
                )

    @admin.action(description="Confirm receipt of selected transfers (add stock at the destination)")
    def receive_selected(self, request, queryset):
        for transfer in queryset:
            try:
                transfer.receive(request.user)
                self.message_user(
                    request,
                    f"{transfer.reference} received: {transfer.get_status_display()}.",
                    messages.SUCCESS,
                )
            except ValueError as error:
                self.message_user(
                    request, f"{transfer.reference}: {error}", messages.ERROR
                )


@admin.register(DailyClosing)
class DailyClosingAdmin(admin.ModelAdmin):
    list_display = (
        "date",
        "location",
        "expected_cash",
        "counted_cash",
        "difference",
        "closed_by",
    )
    list_filter = ("location", "date")

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