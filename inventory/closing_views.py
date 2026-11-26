from datetime import date, timedelta

from django.contrib import messages
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.shortcuts import redirect, render
from django.utils import timezone

from .forms import ClosingForm
from .models import DailyClosing, Location
from .permissions import sales_required, staff_required, visible_locations


def _parse_date(value, default):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return default


@sales_required
def closing_create(request):
    form = ClosingForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        closing = form.save(commit=False)
        closing.closed_by = request.user
        try:
            with transaction.atomic():
                closing.save()
        except IntegrityError:
            form.add_error(None, "This day is already closed for that shop.")
        else:
            messages.success(
                request, f"{closing.location.name}: {closing.date} is now closed."
            )
            return redirect("closing_list")
    return render(request, "inventory/closing_form.html", {"form": form})


@staff_required
def closing_list(request):
    today = timezone.localdate()
    shops = visible_locations(request.user).filter(kind=Location.SHOP)
    start = _parse_date(request.GET.get("start"), today - timedelta(days=29))
    end = _parse_date(request.GET.get("end"), today)
    if start > end:
        start, end = end, start

    closings = DailyClosing.objects.filter(
        location__in=shops, date__gte=start, date__lte=end
    ).select_related("location", "closed_by")
    selected = request.GET.get("location", "")
    if selected.isdigit() and shops.filter(pk=int(selected)).exists():
        closings = closings.filter(location_id=int(selected))
    else:
        selected = ""

    totals = closings.aggregate(
        expected=Sum("expected_cash"),
        counted=Sum("counted_cash"),
        net=Sum("difference"),
    )
    shortage_total = (
        closings.filter(difference__lt=0).aggregate(total=Sum("difference"))["total"]
        or 0
    )
    context = {
        "closings": closings,
        "start": start,
        "end": end,
        "totals": totals,
        "shortage_total": shortage_total,
        "unclosed": shops.exclude(closings__date=today),
        "locations": shops,
        "selected": selected,
    }
    return render(request, "inventory/closings.html", context)