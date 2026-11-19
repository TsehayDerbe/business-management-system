from django.contrib.auth.decorators import login_required
from django.db.models import F, Sum
from django.shortcuts import render
from django.utils import timezone

from .models import Product, Sale


@login_required
def dashboard(request):
    today = timezone.localdate()
    todays_sales = Sale.objects.filter(sold_at__date=today).select_related("product")
    total_today = todays_sales.aggregate(total=Sum("total_price"))["total"] or 0
    low_stock = Product.objects.filter(quantity__lte=F("low_stock_level"))

    context = {
        "today": today,
        "todays_sales": todays_sales,
        "total_today": total_today,
        "sales_count": todays_sales.count(),
        "low_stock": low_stock,
        "product_count": Product.objects.count(),
    }
    return render(request, "inventory/dashboard.html", context)