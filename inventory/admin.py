from django.contrib import admin
from .models import Product, Sale


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'sku', 'price', 'quantity', 'low_stock_level')
    search_fields = ('name', 'sku')


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = ('product', 'quantity', 'total_price', 'sold_by', 'sold_at')
    list_filter = ('sold_at',)