"""Bulk Excel/CSV import of charging stations. Each new station gets its permanent QR automatically."""
import re

from django.db import transaction

from apps.locations.importers import _canon
from apps.locations.models import Location

from .forms import StationForm
from .models import ChargingStation

STATION_COLUMNS = [
    ("station_id", "Station ID (optional – only to update an existing station)"),
    ("location_id", "Location ID *"),
    ("station_name", "Station Name *"),
    ("station_address", "Station Address *"),
    ("city", "City"),
    ("state", "State"),
    ("charger_type", "Charger Type"),
    ("charger_capacity", "Charger Capacity (kW)"),
    ("status", "Status (Active/Inactive/Maintenance)"),
]

TYPE_LOOKUP = {}
for value, label in ChargingStation.ChargerType.choices:
    TYPE_LOOKUP[value.lower()] = value
    TYPE_LOOKUP[label.lower()] = value
    TYPE_LOOKUP[re.sub(r"[^a-z0-9]", "", label.lower())] = value
for alias, value in {"ccs2": "dc_ccs2", "ccs": "dc_ccs2", "chademo": "dc_chademo", "type2": "ac_type2",
                     "type 2": "ac_type2", "ac": "ac_type2", "dc": "dc_ccs2", "gbt": "dc_gbt", "gb/t": "dc_gbt",
                     "bharat ac": "ac_bharat_001", "bharat dc": "dc_bharat_001", "lev": "lev"}.items():
    TYPE_LOOKUP[alias] = value

STATUS_LOOKUP = {"": "active", "active": "active", "inactive": "inactive", "maintenance": "maintenance",
                 "under maintenance": "maintenance"}


def import_stations(rows, update_existing=True, user=None):
    result = {"created": 0, "updated": 0, "skipped": 0, "errors": [], "total": len(rows)}
    locations = {l.location_id.lower(): l for l in Location.objects.all() if l.location_id}
    seen = set()
    with transaction.atomic():
        for idx, raw in enumerate(rows, start=2):
            row = _canon(raw)
            loc_code = str(row.get("location_id", "")).strip().lower()
            location = locations.get(loc_code)
            if not location:
                result["errors"].append((idx, f"Unknown Location ID “{row.get('location_id', '')}”."))
                continue
            name = " ".join(str(row.get("station_name", "") or row.get("name", "")).split())
            key = (location.pk, name.lower())
            if key in seen:
                result["errors"].append((idx, "Duplicate station name for this location in file."))
                continue
            ctype_raw = str(row.get("charger_type", "")).strip().lower()
            ctype = TYPE_LOOKUP.get(ctype_raw) or TYPE_LOOKUP.get(re.sub(r"[^a-z0-9]", "", ctype_raw))
            if ctype_raw and not ctype:
                result["errors"].append((idx, f"Unknown charger type “{row.get('charger_type')}”."))
                continue
            status = STATUS_LOOKUP.get(str(row.get("status", "")).strip().lower())
            if status is None:
                result["errors"].append((idx, f"Invalid status “{row.get('status')}”."))
                continue
            capacity = re.sub(r"[^0-9.]", "", str(row.get("charger_capacity", "") or row.get("charger_capacity_kw", "")))
            data = {
                "location": location.pk, "name": name,
                "address": row.get("station_address", "") or row.get("address", "") or location.address,
                "city": row.get("city", ""), "state": row.get("state", ""),
                "charger_type": ctype or ChargingStation.ChargerType.DC_CCS2,
                "charger_capacity_kw": capacity or None, "status": status,
            }
            code = str(row.get("station_id", "")).strip()
            instance = None
            if code:
                instance = ChargingStation.objects.filter(station_id__iexact=code).first()
                if instance is None:
                    result["errors"].append((idx, f"Station ID “{code}” not found (leave blank to create new)."))
                    continue
                if instance.location_id != location.pk:
                    result["errors"].append((idx, "A station cannot be moved to another location by import."))
                    continue
            else:
                instance = ChargingStation.objects.filter(location=location, name__iexact=name).first()
            if instance is not None and not update_existing:
                result["skipped"] += 1
                continue
            form = StationForm(data=data, instance=instance)
            if not form.is_valid():
                msgs = [f"{'Row' if f == '__all__' else form.fields[f].label}: {' '.join(e)}" for f, e in form.errors.items()]
                result["errors"].append((idx, "; ".join(msgs)))
                continue
            obj = form.save(commit=False)
            obj._skip_qr_image = True  # images are rendered lazily on first preview/download
            obj._created_by = user
            obj.save()
            seen.add(key)
            result["updated" if instance else "created"] += 1
    return result
