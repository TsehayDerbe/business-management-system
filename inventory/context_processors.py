from .permissions import is_manager


def roles(request):
    return {"is_manager": is_manager(request.user)}