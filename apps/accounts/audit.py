from apps.core.utils import get_client_ip

from .models import AuditLog


def log_action(request, action, obj=None, description="", object_type=None):
    user = getattr(request, "user", None) if request else None
    AuditLog.objects.create(
        user=user if user is not None and user.is_authenticated else None,
        action=action,
        object_type=object_type or (obj._meta.verbose_name.title() if obj is not None else ""),
        object_id=str(getattr(obj, "pk", "") or ""),
        object_repr=str(obj)[:255] if obj is not None else "",
        description=description[:5000],
        ip_address=get_client_ip(request) if request else None,
    )
