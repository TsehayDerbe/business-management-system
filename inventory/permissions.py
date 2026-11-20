from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

MANAGER_GROUP = "Manager"


def is_manager(user):
    return user.is_authenticated and (
        user.is_superuser or user.groups.filter(name=MANAGER_GROUP).exists()
    )


def manager_required(view):
    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not is_manager(request.user):
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return wrapper