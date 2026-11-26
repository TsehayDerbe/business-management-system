import csv
from datetime import date, timedelta

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count, F, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .forms import ProductForm, SaleForm
from .invoices import build_invoice_pdf
from .models import DailyClosing, Location, Product, Sale, StockLevel, StockTransfer
from .permissions import (
    head_office_required,
    is_head_office,
    sales_required,
    staff_required,
    stock_manager_required,
    visible_locations,
)


@staff_required
def dashboard(request):
    user = request.user
    locations = visible_locations(user)
    today = timezone.localdate()

    sales_today = Sale.objects.filter(location__in=locations, sold_at__date=today)
    totals = sales_today.aggregate(
        revenue=Sum("total_price"), units=Sum("quantity"), count=Count("id")
    )
    recent_sales = sales_today.select_related("product", "location").order_by(
        "-sold_at"
    )[:20]
    low_stock = StockLevel.objects.filter(
        location__in=locations, quantity__lte=F("product__low_stock_level")
    ).select_related("product", "location")

    transfers = StockTransfer.objects.filter(
        Q(from_location__in=locations) | Q(to_location__in=locations)
    )
    in_transit = transfers.filter(status=StockTransfer.DISPATCHED).count()
    discrepancies = transfers.filter(status=StockTransfer.DISCREPANCY).count()

    shops = locations.filter(kind=Location.SHOP)
    closed_today = DailyClosing.objects.filter(location__in=shops, date=today)
    not_closed = shops.count() - closed_today.count()
    cash_shortages = closed_today.filter(difference__lt=0).count()

    shop_rows = []
    if is_head_office(user):
        scope = "All shops (head office view)"
        shop_rows = (
            locations.filter(kind=Location.SHOP)
            .annotate(
                sales_count=Count("sale", filter=Q(sale__sold_at__date=today)),
                revenue=Sum("sale__total_price", filter=Q(sale__sold_at__date=today)),
            )
            .order_by("city", "name")
        )
    else:
        shop = locations.first()
        scope = shop.name if shop else "No shop assigned to your account"

    context = {
        "today": today,
        "scope": scope,
        "totals": totals,
        "recent_sales": recent_sales,
        "low_stock": low_stock,
        "in_transit": in_transit,
        "discrepancies": discrepancies,
        "not_closed": not_closed,
        "cash_shortages": cash_shortages,
        "shop_rows": shop_rows,
    }
    return render(request, "inventory/dashboard.html", context)


@staff_required
def stock(request):
    locations = visible_locations(request.user)
    levels = (
        StockLevel.objects.filter(location__in=locations)
        .select_related("product", "location")
        .order_by("location__name", "product__name")
    )
    selected = request.GET.get("location", "")
    if selected.isdigit():
        levels = levels.filter(location_id=int(selected))
    context = {
        "levels": levels,
        "locations": locations,
        "selected": selected,
    }
    return render(request, "inventory/stock.html", context)


@sales_required
def new_sale(request):
    form = SaleForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        sale = form.save(commit=False)
        sale.sold_by = request.user
        try:
            sale.save()
        except ValueError as error:
            form.add_error(None, str(error))
        else:
            messages.success(
                request,
                f"Sale recorded: {sale.quantity} x {sale.product.name} "
                f"= {sale.total_price} ETB",
            )
            return redirect("dashboard")
    return render(request, "inventory/new_sale.html", {"form": form})


@staff_required
def sale_invoice(request, pk):
    sale = get_object_or_404(
        Sale.objects.select_related("product", "sold_by", "location"), pk=pk
    )
    if not visible_locations(request.user).filter(pk=sale.location_id).exists():
        raise PermissionDenied
    pdf = build_invoice_pdf(sale)
    response = HttpResponse(pdf, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="invoice-{sale.pk:05d}.pdf"'
    return response


@head_office_required
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


@stock_manager_required
def product_create(request):
    form = ProductForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        product = form.save()
        messages.success(request, f"Product added: {product.name}")
        return redirect("products")
    return render(
        request, "inventory/product_form.html", {"form": form, "title": "Add product"}
    )


@stock_manager_required
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
        Sale.objects.filter(
            location__in=visible_locations(request.user),
            sold_at__date__gte=start,
            sold_at__date__lte=end,
        )
        .select_related("product", "sold_by", "location")
        .order_by("-sold_at")
    )
    return start, end, sales


@head_office_required
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


@head_office_required
def reports_csv(request):
    start, end, sales = _report_sales(request)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="sales-{start}-to-{end}.csv"'
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(
        [
            "Invoice",
            "Date",
            "Shop",
            "City",
            "Product",
            "SKU",
            "Unit price",
            "Quantity",
            "Total",
            "Payment",
            "Receipt no.",
            "Sold by",
        ]
    )
    for sale in sales:
        writer.writerow(
            [
                f"INV-{sale.pk:05d}",
                timezone.localtime(sale.sold_at).strftime("%Y-%m-%d %H:%M"),
                sale.location.name,
                sale.location.city,
                sale.product.name,
                sale.product.sku,
                sale.product.price,
                sale.quantity,
                sale.total_price,
                sale.get_payment_method_display(),
                sale.receipt_number,
                sale.sold_by.get_username() if sale.sold_by else "",
            ]
        )
    return response