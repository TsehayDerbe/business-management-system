from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import F, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .forms import ProductForm, SaleForm
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