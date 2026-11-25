from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

from .models import Location, UserProfile

HEAD_OFFICE_ROLES = {UserProfile.ADMIN, UserProfile.STOCK, UserProfile.OPS}


def get_role(user):
    if not user.is_authenticated:
        return None
    if user.is_superuser:
        return UserProfile.ADMIN
    profile = getattr(user, "profile", None)
    return profile.role if profile else None


def is_head_office(user):
    return get_role(user) in HEAD_OFFICE_ROLES


def can_manage_stock(user):
    return get_role(user) in {UserProfile.ADMIN, UserProfile.STOCK}


def can_record_sales(user):
    return get_role(user) in {UserProfile.ADMIN, UserProfile.SHOP}


def can_receive_transfer(user, transfer):
    """Admins, or the sales manager of the destination shop."""
    role = get_role(user)
    if role == UserProfile.ADMIN:
        return True
    if role == UserProfile.SHOP:
        return user.profile.location_id == transfer.to_location_id
    return False


def has_role(user):
    return get_role(user) is not None


def visible_locations(user):
    """The locations this user is allowed to see."""
    role = get_role(user)
    if role in HEAD_OFFICE_ROLES:
        return Location.objects.filter(is_active=True)
    if role == UserProfile.SHOP and user.profile.location_id:
        return Location.objects.filter(pk=user.profile.location_id)
    return Location.objects.none()


def role_required(check):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapper(request, *args, **kwargs):
            if not check(request.user):
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return wrapper

    return decorator


staff_required = role_required(has_role)
head_office_required = role_required(is_head_office)
stock_manager_required = role_required(can_manage_stock)
sales_required = role_required(can_record_sales)