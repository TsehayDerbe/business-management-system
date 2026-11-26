from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from .forms import TransferForm, TransferItemFormSet
from .models import StockTransfer
from .permissions import (
    can_manage_stock,
    can_receive_transfer,
    staff_required,
    stock_manager_required,
    visible_locations,
)


def _can_view(user, transfer):
    return (
        visible_locations(user)
        .filter(pk__in=[transfer.from_location_id, transfer.to_location_id])
        .exists()
    )


@staff_required
def transfer_list(request):
    locations = visible_locations(request.user)
    transfers = (
        StockTransfer.objects.filter(
            Q(from_location__in=locations) | Q(to_location__in=locations)
        )
        .select_related("from_location", "to_location")
        .order_by("-created_at")
    )
    if not can_manage_stock(request.user):
        transfers = transfers.exclude(status=StockTransfer.DRAFT)
    status = request.GET.get("status", "")
    if status in dict(StockTransfer.STATUS_CHOICES):
        transfers = transfers.filter(status=status)
    else:
        status = ""
    return render(
        request,
        "inventory/transfers.html",
        {
            "transfers": transfers,
            "status": status,
            "status_choices": StockTransfer.STATUS_CHOICES,
        },
    )


@stock_manager_required
def transfer_create(request):
    form = TransferForm(request.POST or None)
    formset = TransferItemFormSet(request.POST or None, instance=StockTransfer())
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        if not any(item_form.has_changed() for item_form in formset.forms):
            messages.error(request, "Add at least one item.")
        else:
            with transaction.atomic():
                transfer = form.save(commit=False)
                transfer.created_by = request.user
                transfer.save()
                formset.instance = transfer
                formset.save()
            messages.success(
                request,
                f"{transfer.reference} saved as a draft. Check it, then dispatch.",
            )
            return redirect("transfer_detail", pk=transfer.pk)
    return render(
        request,
        "inventory/transfer_form.html",
        {"form": form, "formset": formset},
    )


@staff_required
def transfer_detail(request, pk):
    transfer = get_object_or_404(
        StockTransfer.objects.select_related(
            "from_location", "to_location", "created_by", "received_by"
        ),
        pk=pk,
    )
    user = request.user
    if not _can_view(user, transfer):
        raise PermissionDenied
    if transfer.status == StockTransfer.DRAFT and not can_manage_stock(user):
        raise PermissionDenied

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "dispatch" and not can_manage_stock(user):
            raise PermissionDenied
        if action == "receive" and not can_receive_transfer(user, transfer):
            raise PermissionDenied
        try:
            with transaction.atomic():
                locked = StockTransfer.objects.select_for_update().get(pk=transfer.pk)
                if action == "dispatch":
                    locked.dispatch(user)
                    done = f"{locked.reference} dispatched."
                elif action == "receive":
                    if locked.status != StockTransfer.DISPATCHED:
                        raise ValueError("Only dispatched transfers can be received.")
                    for item in locked.items.select_related("product"):
                        raw = request.POST.get(f"received_{item.pk}", "").strip()
                        if not raw.isdigit():
                            raise ValueError(
                                f"Enter the received quantity for {item.product.name}."
                            )
                        item.quantity_received = int(raw)
                        item.save(update_fields=["quantity_received"])
                    locked.receive(user)
                    done = f"{locked.reference}: {locked.get_status_display()}."
                else:
                    raise ValueError("Unknown action.")
        except ValueError as error:
            messages.error(request, str(error))
        else:
            messages.success(request, done)
        return redirect("transfer_detail", pk=transfer.pk)

    context = {
        "transfer": transfer,
        "items": transfer.items.select_related("product"),
        "can_dispatch": can_manage_stock(user)
        and transfer.status == StockTransfer.DRAFT,
        "can_receive": can_receive_transfer(user, transfer)
        and transfer.status == StockTransfer.DISPATCHED,
    }
    return render(request, "inventory/transfer_detail.html", context)