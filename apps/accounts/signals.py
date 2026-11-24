from django.contrib.auth.models import Group, Permission
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.db.models.signals import post_migrate, post_save
from django.dispatch import receiver

from apps.core.utils import get_client_ip

from .models import AuditLog, User

ROLE_GROUPS = {
    User.Role.SUPER_ADMIN: "Super Admin",
    User.Role.MANAGER: "Manager",
    User.Role.STAFF: "Staff",
}

# Django model permissions granted to each group (mirrors the in-app role rules).
GROUP_PERMISSIONS = {
    "Super Admin": "__all__",
    "Manager": [
        "locations.view_location", "stations.view_chargingstation", "qrcodes.view_qrcodemapping",
        "qrcodes.view_qrscanevent", "leads.view_lead", "leads.change_lead", "leads.add_leadnote",
        "leads.view_leadnote", "leads.add_leadassignment", "leads.view_leadstatushistory",
    ],
    "Staff": ["leads.view_lead", "leads.change_lead", "leads.add_leadnote", "leads.view_leadnote"],
}


def ensure_role_groups():
    app_labels = ["accounts", "locations", "stations", "qrcodes", "leads", "core"]
    for name, perms in GROUP_PERMISSIONS.items():
        group, _ = Group.objects.get_or_create(name=name)
        if perms == "__all__":
            qs = Permission.objects.filter(content_type__app_label__in=app_labels)
        else:
            q = Permission.objects.none()
            for perm in perms:
                app, codename = perm.split(".")
                q = q | Permission.objects.filter(content_type__app_label=app, codename=codename)
            qs = q
        group.permissions.set(qs)


@receiver(post_migrate)
def create_role_groups(sender, **kwargs):
    if sender.name == "apps.accounts":
        ensure_role_groups()


@receiver(post_save, sender=User)
def sync_role_group(sender, instance, **kwargs):
    group_name = ROLE_GROUPS.get(instance.role)
    target = Group.objects.filter(name=group_name).first()
    role_groups = Group.objects.filter(name__in=ROLE_GROUPS.values())
    if target is None:
        return
    current = set(instance.groups.filter(pk__in=role_groups).values_list("pk", flat=True))
    if current != {target.pk}:
        instance.groups.remove(*role_groups)
        instance.groups.add(target)


@receiver(user_logged_in)
def on_login(sender, request, user, **kwargs):
    AuditLog.objects.create(user=user, action=AuditLog.Action.LOGIN, object_type="User",
                            object_id=str(user.pk), object_repr=str(user), ip_address=get_client_ip(request))


@receiver(user_logged_out)
def on_logout(sender, request, user, **kwargs):
    if user is not None:
        AuditLog.objects.create(user=user, action=AuditLog.Action.LOGOUT, object_type="User",
                                object_id=str(user.pk), object_repr=str(user), ip_address=get_client_ip(request))


@receiver(user_login_failed)
def on_login_failed(sender, credentials, request=None, **kwargs):
    AuditLog.objects.create(action=AuditLog.Action.LOGIN_FAILED, object_type="User",
                            object_repr=str(credentials.get("username", ""))[:150],
                            ip_address=get_client_ip(request) if request else None)
