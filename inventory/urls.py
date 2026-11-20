from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("sales/new/", views.new_sale, name="new_sale"),
    path("products/", views.product_list, name="products"),
]