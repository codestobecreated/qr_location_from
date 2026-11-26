from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.decorators.http import require_POST

from apps.core.models import SystemSetting
from apps.core.pagination import paginate
from apps.core.utils import safe_next
from apps.core.utils import get_client_ip

from .audit import log_action
from .forms import AdminSetPasswordForm, LoginForm, ProfileForm, StyledPasswordChangeForm, SystemSettingForm, UserForm
from .models import AuditLog, User
from .permissions import role_required


MAX_LOGIN_FAILURES = 5
LOCKOUT_SECONDS = 15 * 60


class LoginView(auth_views.LoginView):
    """Django's login view with a simple per-IP lockout after repeated failures."""

    template_name = "accounts/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def _key(self):
        return f"login-fail:{get_client_ip(self.request)}"

    def post(self, request, *args, **kwargs):
        if cache.get(self._key(), 0) >= MAX_LOGIN_FAILURES:
            form = self.get_form_class()(request)
            return self.render_to_response(
                self.get_context_data(
                    form=form, lockout_message="Too many failed attempts. Please wait 15 minutes and try again."
                ),
                status=429,
            )
        return super().post(request, *args, **kwargs)

    def form_invalid(self, form):
        key = self._key()
        cache.set(key, cache.get(key, 0) + 1, LOCKOUT_SECONDS)
        return super().form_invalid(form)

    def form_valid(self, form):
        cache.delete(self._key())
        return super().form_valid(form)


class PasswordChangeView(auth_views.PasswordChangeView):
    template_name = "accounts/password_change.html"
    form_class = StyledPasswordChangeForm
    success_url = reverse_lazy("accounts:settings")

    def form_valid(self, form):
        messages.success(self.request, "Your password has been changed.")
        return super().form_valid(form)


# ---------------------------------------------------------------------------
# User management (Super Admin only)
# ---------------------------------------------------------------------------
@role_required()
def user_list(request):
    qs = User.objects.annotate(
        lead_count=Count("assigned_leads", distinct=True),
    ).order_by("-is_active", "first_name", "username")
    q = request.GET.get("q", "").strip()
    role = request.GET.get("role", "")
    status = request.GET.get("status", "")
    if q:
        qs = qs.filter(Q(username__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(email__icontains=q))
    if role in User.Role.values:
        qs = qs.filter(role=role)
    if status == "active":
        qs = qs.filter(is_active=True)
    elif status == "inactive":
        qs = qs.filter(is_active=False)
    page = paginate(request, qs)
    return render(request, "accounts/user_list.html", {
        "page": page, "roles": User.Role.choices, "q": q, "role": role, "status": status,
        "counts": User.objects.aggregate(
            total=Count("id"),
            admins=Count("id", filter=Q(role=User.Role.SUPER_ADMIN)),
            managers=Count("id", filter=Q(role=User.Role.MANAGER)),
            staff=Count("id", filter=Q(role=User.Role.STAFF)),
        ),
    })


@role_required()
def user_create(request):
    form = UserForm(request.POST or None, request_user=request.user)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        log_action(request, AuditLog.Action.CREATE, user, f"Created user with role {user.get_role_display()}")
        messages.success(request, f"User “{user.username}” created.")
        return redirect("accounts:user_list")
    return render(request, "accounts/user_form.html", {"form": form, "is_create": True})


@role_required()
def user_edit(request, pk):
    obj = get_object_or_404(User, pk=pk)
    form = UserForm(request.POST or None, instance=obj, request_user=request.user)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        if user.pk == request.user.pk and form.cleaned_data.get("password1"):
            update_session_auth_hash(request, user)
        log_action(request, AuditLog.Action.UPDATE, user, f"Updated user; role {user.get_role_display()}, active={user.is_active}")
        messages.success(request, f"User “{user.username}” updated.")
        return redirect("accounts:user_list")
    return render(request, "accounts/user_form.html", {"form": form, "obj": obj, "is_create": False})


@role_required()
@require_POST
def user_toggle(request, pk):
    obj = get_object_or_404(User, pk=pk)
    if obj.pk == request.user.pk:
        messages.error(request, "You cannot deactivate your own account.")
        return redirect("accounts:user_list")
    obj.is_active = not obj.is_active
    obj.save(update_fields=["is_active"])
    log_action(request, AuditLog.Action.STATUS, obj, f"User {'activated' if obj.is_active else 'deactivated'}")
    messages.success(request, f"User “{obj.username}” {'activated' if obj.is_active else 'deactivated'}.")
    return redirect(safe_next(request, "accounts:user_list"))


@role_required()
def user_set_password(request, pk):
    obj = get_object_or_404(User, pk=pk)
    form = AdminSetPasswordForm(obj, request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        if obj.pk == request.user.pk:
            update_session_auth_hash(request, obj)
        log_action(request, AuditLog.Action.UPDATE, obj, "Password reset by administrator")
        messages.success(request, f"Password updated for “{obj.username}”.")
        return redirect("accounts:user_list")
    return render(request, "accounts/user_password.html", {"form": form, "obj": obj})


# ---------------------------------------------------------------------------
# Settings: everyone manages their own profile; Super Admin also edits system settings.
# ---------------------------------------------------------------------------
@login_required
def settings_view(request):
    profile_form = ProfileForm(instance=request.user, prefix="profile")
    system_form = SystemSettingForm(instance=SystemSetting.load(), prefix="system") if request.user.is_super_admin else None

    if request.method == "POST":
        section = request.POST.get("section")
        if section == "profile":
            profile_form = ProfileForm(request.POST, instance=request.user, prefix="profile")
            if profile_form.is_valid():
                profile_form.save()
                messages.success(request, "Your profile has been updated.")
                return redirect("accounts:settings")
        elif section == "system" and request.user.is_super_admin:
            system_form = SystemSettingForm(request.POST, instance=SystemSetting.load(), prefix="system")
            if system_form.is_valid():
                obj = system_form.save()
                log_action(request, AuditLog.Action.UPDATE, obj, "System settings updated", object_type="Settings")
                messages.success(request, "System settings saved.")
                return redirect("accounts:settings")
    from django.conf import settings as dj_settings

    return render(request, "accounts/settings.html", {
        "profile_form": profile_form,
        "system_form": system_form,
        "qr_base_url": dj_settings.QR_BASE_URL,
        "debug": dj_settings.DEBUG,
    })


@role_required()
def audit_log(request):
    qs = AuditLog.objects.select_related("user")
    action = request.GET.get("action", "")
    q = request.GET.get("q", "").strip()
    if action in AuditLog.Action.values:
        qs = qs.filter(action=action)
    if q:
        qs = qs.filter(Q(object_repr__icontains=q) | Q(description__icontains=q) | Q(user__username__icontains=q))
    page = paginate(request, qs, default=50)
    return render(request, "accounts/audit_log.html", {"page": page, "actions": AuditLog.Action.choices, "action": action, "q": q})
