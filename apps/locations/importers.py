"""Bulk Excel/CSV import of locations (1,000+ rows)."""
import re

from django.db import transaction

from apps.core.models import Status

from .forms import LocationForm
from .models import Location

LOCATION_COLUMNS = [
    ("location_id", "Location ID (optional – leave blank to auto-generate)"),
    ("location_name", "Location Name *"),
    ("address", "Address *"),
    ("city", "City *"),
    ("district", "District"),
    ("state", "State *"),
    ("pin_code", "PIN Code *"),
    ("latitude", "Latitude"),
    ("longitude", "Longitude"),
    ("contact_person", "Contact Person"),
    ("contact_number", "Contact Number"),
    ("status", "Status (Active/Inactive)"),
]

ALIASES = {
    "name": "location_name", "location": "location_name", "pincode": "pin_code", "pin": "pin_code",
    "zip": "pin_code", "lat": "latitude", "lng": "longitude", "long": "longitude", "phone": "contact_number",
    "mobile": "contact_number", "contact": "contact_person", "id": "location_id", "location_code": "location_id",
}
CODE_RE = re.compile(r"^[A-Za-z0-9_-]{2,30}$")


def _canon(row):
    out = {}
    for key, value in row.items():
        key = re.split(r"_\(|_\*|\*", key)[0].strip("_")
        key = ALIASES.get(key, key)
        out[key] = value
    return out


def _status(value):
    v = str(value or "").strip().lower()
    if v in ("", "active", "yes", "1", "true", "enabled"):
        return Status.ACTIVE
    if v in ("inactive", "no", "0", "false", "disabled"):
        return Status.INACTIVE
    return None


def import_locations(rows, update_existing=True):
    """Validate and save rows. Returns a result dict with per-row errors."""
    result = {"created": 0, "updated": 0, "skipped": 0, "errors": [], "total": len(rows)}
    seen_codes, seen_names = set(), set()
    with transaction.atomic():
        for idx, raw in enumerate(rows, start=2):  # row 1 = header
            row = _canon(raw)
            code = str(row.get("location_id", "")).strip()
            status = _status(row.get("status"))
            if status is None:
                result["errors"].append((idx, f"Invalid status “{row.get('status')}”. Use Active or Inactive."))
                continue
            pincode = re.sub(r"\D", "", str(row.get("pin_code", "")))
            data = {
                "name": row.get("location_name", ""), "address": row.get("address", ""),
                "city": row.get("city", ""), "district": row.get("district", ""), "state": row.get("state", ""),
                "pincode": pincode, "latitude": row.get("latitude", "") or None,
                "longitude": row.get("longitude", "") or None, "contact_person": row.get("contact_person", ""),
                "contact_number": str(row.get("contact_number", "")).strip(), "status": status,
            }
            name_key = (str(data["name"]).strip().lower(), pincode)
            if code and code in seen_codes or name_key in seen_names:
                result["errors"].append((idx, "Duplicate row in file (same Location ID or name + PIN code)."))
                continue
            if code and not CODE_RE.match(code):
                result["errors"].append((idx, f"Invalid Location ID “{code}”. Use letters, numbers, - or _."))
                continue

            instance = None
            if code:
                instance = Location.objects.filter(location_id=code).first()
            if instance is None and data["name"] and pincode:
                instance = Location.objects.filter(name__iexact=str(data["name"]).strip(), pincode=pincode).first()
                if instance is not None and code and instance.location_id != code:
                    result["errors"].append(
                        (idx, f"“{data['name']}” ({pincode}) already exists as {instance.location_id}, not {code}.")
                    )
                    continue
            if instance is not None and not update_existing:
                result["skipped"] += 1
                continue

            form = LocationForm(data=data, instance=instance)
            if not form.is_valid():
                msgs = []
                for field, errs in form.errors.items():
                    label = "Row" if field == "__all__" else form.fields[field].label
                    msgs.append(f"{label}: {' '.join(errs)}")
                result["errors"].append((idx, "; ".join(msgs)))
                continue
            obj = form.save(commit=False)
            if instance is None and code:
                obj.location_id = code
            obj.save()
            seen_names.add(name_key)
            if code:
                seen_codes.add(code)
            result["updated" if instance else "created"] += 1
    return result
