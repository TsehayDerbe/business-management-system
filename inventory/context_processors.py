from .models import UserProfile
from .permissions import can_manage_stock, can_record_sales, get_role, is_head_office


def roles(request):
    user = request.user
    role = get_role(user)
    return {
        "user_role": role,
        "user_role_label": dict(UserProfile.ROLE_CHOICES).get(role),
        "is_head_office": is_head_office(user),
        "can_manage_stock": can_manage_stock(user),
        "can_record_sales": can_record_sales(user),
    }