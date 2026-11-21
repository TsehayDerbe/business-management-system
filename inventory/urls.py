from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("sales/new/", views.new_sale, name="new_sale"),
    path("sales/<int:pk>/invoice/", views.sale_invoice, name="sale_invoice"),
    path("products/", views.product_list, name="products"),
    path("products/new/", views.product_create, name="product_create"),
    path("products/<int:pk>/edit/", views.product_edit, name="product_edit"),
    path("reports/", views.reports, name="reports"),
    path("reports/export/", views.reports_csv, name="reports_csv"),
]