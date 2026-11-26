"""Role-based access control helpers and data scoping for Super Admin / Manager / Staff."""
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied

from .models import User

SUPER_ADMIN = User.Role.SUPER_ADMIN
MANAGER = User.Role.MANAGER
STAFF = User.Role.STAFF


def user_role(user):
    if not user.is_authenticated:
        return None
    return SUPER_ADMIN if user.is_super_admin else user.role


def has_role(user, *roles):
    return user.is_authenticated and user.is_active and user_role(user) in roles


def role_required(*roles):
    """Decorator for function views. Super Admin is always allowed."""
    allowed = set(roles) | {SUPER_ADMIN}

    def decorator(view):
        @wraps(view)
        @login_required
        def wrapper(request, *args, **kwargs):
            if not has_role(request.user, *allowed):
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return wrapper

    return decorator


class RoleRequiredMixin(LoginRequiredMixin):
    allowed_roles = ()

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not has_role(request.user, SUPER_ADMIN, *self.allowed_roles):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


# --- Data scoping -------------------------------------------------------------

def scope_stations(qs, user):
    if user.is_super_admin or user.is_manager:
        return qs
    return qs.none()


def scope_leads(qs, user):
    if user.is_super_admin or user.is_manager:
        return qs
    return qs.filter(assigned_to=user)


def scope_scans(qs, user):
    if user.is_super_admin or user.is_manager:
        return qs
    return qs.none()


def can_manage_master_data(user):
    """Manage the QR code and system settings."""
    return user.is_authenticated and user.is_super_admin


def can_assign_leads(user):
    return user.is_authenticated and (user.is_super_admin or user.is_manager)


def assignable_users(user):
    qs = User.objects.filter(is_active=True)
    if user.is_super_admin:
        return qs
    if user.is_manager:
        # Managers assign to staff (and themselves).
        return qs.filter(role__in=[STAFF, MANAGER]).filter(pk__in=_team_ids(user))
    return qs.none()


def _team_ids(manager):
    ids = set(User.objects.filter(role=STAFF, is_active=True).values_list("pk", flat=True))
    ids.add(manager.pk)
    return ids


__all__ = [
    "login_required", "role_required", "RoleRequiredMixin", "has_role",
    "scope_stations", "scope_leads", "scope_scans", "can_manage_master_data", "can_assign_leads",
    "assignable_users", "SUPER_ADMIN", "MANAGER", "STAFF",
]
