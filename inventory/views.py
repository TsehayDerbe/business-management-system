import csv
from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, F, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .forms import ProductForm, SaleForm
from .invoices import build_invoice_pdf
from .models import Product, Sale
from .permissions import is_manager, manager_required


@login_required
def dashboard(request):
    today = timezone.localdate()
    todays_sales = Sale.objects.filter(sold_at__date=today).select_related("product")
    if not is_manager(request.user):
        todays_sales = todays_sales.filter(sold_by=request.user)
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


@login_required
def new_sale(request):
    if request.method == "POST":
        form = SaleForm(request.POST)
        if form.is_valid():
            sale = form.save(commit=False)
            sale.sold_by = request.user
            sale.save()
            messages.success(
                request,
                f"Sale recorded: {sale.quantity} x {sale.product.name} = {sale.total_price} ETB",
            )
            return redirect("dashboard")
    else:
        form = SaleForm()
    return render(request, "inventory/new_sale.html", {"form": form})


@login_required
def sale_invoice(request, pk):
    sale = get_object_or_404(Sale.objects.select_related("product", "sold_by"), pk=pk)
    if not is_manager(request.user) and sale.sold_by_id != request.user.id:
        raise PermissionDenied
    pdf = build_invoice_pdf(sale)
    response = HttpResponse(pdf, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="invoice-{sale.pk:05d}.pdf"'
    return response


@login_required
def product_list(request):
    query = request.GET.get("q", "").strip()
    products = Product.objects.order_by("name")
    if query:
        products = products.filter(Q(name__icontains=query) | Q(sku__icontains=query))
    return render(
        request,
        "inventory/products.html",
        {"products": products, "query": query},
    )


@manager_required
def product_create(request):
    form = ProductForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        product = form.save()
        messages.success(request, f"Product added: {product.name}")
        return redirect("products")
    return render(
        request, "inventory/product_form.html", {"form": form, "title": "Add product"}
    )


@manager_required
def product_edit(request, pk):
    product = get_object_or_404(Product, pk=pk)
    form = ProductForm(request.POST or None, instance=product)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"Product updated: {product.name}")
        return redirect("products")
    return render(
        request,
        "inventory/product_form.html",
        {"form": form, "title": f"Edit {product.name}"},
    )


def _parse_date(value, default):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return default


def _report_sales(request):
    today = timezone.localdate()
    start = _parse_date(request.GET.get("start"), today - timedelta(days=29))
    end = _parse_date(request.GET.get("end"), today)
    if start > end:
        start, end = end, start
    sales = (
        Sale.objects.filter(sold_at__date__gte=start, sold_at__date__lte=end)
        .select_related("product", "sold_by")
        .order_by("-sold_at")
    )
    return start, end, sales


@manager_required
def reports(request):
    start, end, sales = _report_sales(request)
    totals = sales.aggregate(
        revenue=Sum("total_price"), units=Sum("quantity"), count=Count("id")
    )
    top_products = (
        sales.values("product__name", "product__sku")
        .annotate(units=Sum("quantity"), revenue=Sum("total_price"))
        .order_by("-revenue")[:5]
    )
    context = {
        "start": start,
        "end": end,
        "sales": sales,
        "totals": totals,
        "top_products": top_products,
    }
    return render(request, "inventory/reports.html", context)


@manager_required
def reports_csv(request):
    start, end, sales = _report_sales(request)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="sales-{start}-to-{end}.csv"'
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(
        ["Invoice", "Date", "Product", "SKU", "Unit price", "Quantity", "Total", "Sold by"]
    )
    for sale in sales:
        writer.writerow(
            [
                f"INV-{sale.pk:05d}",
                timezone.localtime(sale.sold_at).strftime("%Y-%m-%d %H:%M"),
                sale.product.name,
                sale.product.sku,
                sale.product.price,
                sale.quantity,
                sale.total_price,
                sale.sold_by.get_username() if sale.sold_by else "",
            ]
        )
    return response