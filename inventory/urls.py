from django.urls import path

from . import transfer_views, views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("stock/", views.stock, name="stock"),
    path("sales/new/", views.new_sale, name="new_sale"),
    path("sales/<int:pk>/invoice/", views.sale_invoice, name="sale_invoice"),
    path("transfers/", transfer_views.transfer_list, name="transfers"),
    path("transfers/new/", transfer_views.transfer_create, name="transfer_create"),
    path("transfers/<int:pk>/", transfer_views.transfer_detail, name="transfer_detail"),
    path("products/", views.product_list, name="products"),
    path("products/new/", views.product_create, name="product_create"),
    path("products/<int:pk>/edit/", views.product_edit, name="product_edit"),
    path("reports/", views.reports, name="reports"),
    path("reports/export/", views.reports_csv, name="reports_csv"),
]