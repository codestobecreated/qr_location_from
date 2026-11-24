from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def url_replace(context, **kwargs):
    """Current querystring with some keys replaced (empty value removes the key)."""
    query = context["request"].GET.copy()
    for key, value in kwargs.items():
        if value in (None, ""):
            query.pop(key, None)
        else:
            query[key] = value
    return query.urlencode()


@register.simple_tag(takes_context=True)
def sort_link(context, field):
    request = context["request"]
    current = request.GET.get("sort", "")
    query = request.GET.copy()
    query["sort"] = f"-{field}" if current == field else field
    query.pop("page", None)
    return query.urlencode()


@register.simple_tag(takes_context=True)
def sort_icon(context, field):
    current = context["request"].GET.get("sort", "")
    if current == field:
        return "▲"
    if current == f"-{field}":
        return "▼"
    return ""


@register.filter
def percent(numerator, denominator):
    try:
        if not denominator:
            return "0.00%"
        return f"{(float(numerator) / float(denominator)) * 100:.2f}%"
    except (TypeError, ValueError):
        return "0.00%"


@register.simple_tag(takes_context=True)
def nav_active(context, *prefixes):
    path = context["request"].path
    return "is-active" if any(path.startswith(p) for p in prefixes) else ""


BADGES = {
    "blue": "bg-blue-50 text-blue-700 ring-blue-600/20",
    "indigo": "bg-indigo-50 text-indigo-700 ring-indigo-600/20",
    "amber": "bg-amber-50 text-amber-800 ring-amber-600/20",
    "cyan": "bg-cyan-50 text-cyan-700 ring-cyan-600/20",
    "green": "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
    "rose": "bg-rose-50 text-rose-700 ring-rose-600/20",
    "slate": "bg-slate-100 text-slate-700 ring-slate-500/20",
}

STATUS_COLOURS = {
    "active": "green", "inactive": "slate", "maintenance": "amber", "station_inactive": "amber",
    "new": "blue", "contacted": "indigo", "follow_up": "amber", "interested": "cyan",
    "converted": "green", "not_interested": "rose", "closed": "slate",
    "super_admin": "indigo", "manager": "cyan", "staff": "slate",
}


@register.inclusion_tag("partials/badge.html")
def badge(value, label=None, colour=None):
    colour = colour or STATUS_COLOURS.get(str(value), "slate")
    return {
        "classes": BADGES.get(colour, BADGES["slate"]),
        "label": label or str(value).replace("_", " ").title(),
    }


@register.filter
def get_item(mapping, key):
    try:
        return mapping.get(key)
    except AttributeError:
        return None
