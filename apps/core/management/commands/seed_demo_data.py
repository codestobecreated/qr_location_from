"""
DEVELOPMENT / TRAINING ONLY – creates sample locations, stations (with real permanent QR mappings),
and optionally simulated scans and leads so every screen can be tried out.

    python manage.py seed_demo_data --locations 25 --leads 300

Refuses to run when DEBUG is off unless --force is given. Never run it on the production database.
"""
import random
import secrets
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.leads.models import EnquiryCategory, Lead, LeadStatus, LeadStatusHistory
from apps.locations.models import Location
from apps.qrcodes.models import QRScanEvent
from apps.stations.models import ChargingStation

CITIES = [
    ("Chennai", "Chennai", "Tamil Nadu", "600"), ("Coimbatore", "Coimbatore", "Tamil Nadu", "641"),
    ("Madurai", "Madurai", "Tamil Nadu", "625"), ("Bengaluru", "Bengaluru Urban", "Karnataka", "560"),
    ("Hyderabad", "Hyderabad", "Telangana", "500"), ("Kochi", "Ernakulam", "Kerala", "682"),
    ("Pune", "Pune", "Maharashtra", "411"), ("Mumbai", "Mumbai", "Maharashtra", "400"),
    ("Ahmedabad", "Ahmedabad", "Gujarat", "380"), ("Delhi", "New Delhi", "Delhi", "110"),
]
AREAS = ["Tambaram", "Velachery", "Anna Nagar", "OMR", "Guindy", "Airport Road", "Ring Road", "Highway Plaza",
         "Tech Park", "Mall", "Bus Terminus", "Metro Station", "City Centre", "Industrial Estate"]
FIRST = ["Arun", "Priya", "Karthik", "Divya", "Rahul", "Sneha", "Vijay", "Meena", "Suresh", "Anitha", "Ravi", "Lakshmi"]
LAST = ["Kumar", "Raman", "Sharma", "Reddy", "Nair", "Iyer", "Patel", "Singh", "Das", "Menon"]
UAS = [
    "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) GSA/15.0 Chrome/125.0 Mobile Safari/537.36",
]


class Command(BaseCommand):
    help = "Create sample data for development/training (never use in production)."

    def add_arguments(self, parser):
        parser.add_argument("--locations", type=int, default=20)
        parser.add_argument("--stations-per-location", type=int, default=2)
        parser.add_argument("--leads", type=int, default=0, help="Also simulate this many scans→leads.")
        parser.add_argument("--force", action="store_true", help="Allow running with DEBUG off.")

    def handle(self, *args, **opts):
        if not settings.DEBUG and not opts["force"]:
            raise CommandError("Refusing to seed sample data with DEBUG off. Use --force only on a test database.")
        from apps.core.utils import parse_user_agent

        rng = random.Random()
        with transaction.atomic():
            stations = []
            for i in range(opts["locations"]):
                city, district, state, pin = rng.choice(CITIES)
                area = rng.choice(AREAS)
                loc = Location.objects.create(
                    name=f"RELUX {area} {city} {i + 1}", address=f"{rng.randint(1, 300)}, {area} Main Road, {city}",
                    city=city, district=district, state=state, pincode=f"{pin}{rng.randint(1, 120):03d}",
                    contact_person=f"{rng.choice(FIRST)} {rng.choice(LAST)}",
                    contact_number=f"9{rng.randint(100000000, 999999999)}",
                )
                for j in range(opts["stations_per_location"]):
                    st = ChargingStation(
                        location=loc, name=f"RELUX {area} Station {chr(65 + j)}", address=loc.address,
                        city=city, state=state, charger_type=rng.choice(ChargingStation.ChargerType.values[:6]),
                        charger_capacity_kw=rng.choice([7.4, 22, 30, 60, 120]),
                    )
                    st._skip_qr_image = True
                    st.save()
                    stations.append(st)
            self.stdout.write(self.style.SUCCESS(f"Created {opts['locations']} locations and {len(stations)} stations with permanent QR mappings."))

            if opts["leads"] and stations:
                now = timezone.now()
                for _ in range(opts["leads"]):
                    st = rng.choice(stations)
                    mapping = st.qr_mapping
                    when = now - timedelta(days=rng.randint(0, 120), minutes=rng.randint(0, 1440))
                    ua = rng.choice(UAS)
                    meta = parse_user_agent(ua)
                    for _scan in range(rng.randint(1, 4)):
                        QRScanEvent.objects.create(mapping=mapping, station=st, location=st.location, token=mapping.token,
                                                   scanned_at=when, user_agent=ua, form_viewed=rng.random() < 0.7, **meta)
                    if rng.random() < 0.45:
                        status = rng.choices(LeadStatus.values, weights=[30, 20, 12, 12, 12, 8, 6])[0]
                        lead = Lead.objects.create(
                            full_name=f"{rng.choice(FIRST)} {rng.choice(LAST)}", mobile=f"9{rng.randint(100000000, 999999999)}",
                            category=rng.choice(EnquiryCategory.values), message="Sample enquiry (demo data)", consent=True,
                            consent_at=when, location=st.location, station=st, qr_mapping=mapping, qr_token=mapping.token,
                            location_code=st.location.location_id, location_name=st.location.name, station_code=st.station_id,
                            station_name=st.name, source_city=st.city, source_state=st.state, submitted_at=when,
                            submission_key=secrets.token_urlsafe(24), status=status, user_agent=ua, **meta,
                        )
                        LeadStatusHistory.objects.create(lead=lead, from_status="", to_status=LeadStatus.NEW, note="Demo data")
                        if status != LeadStatus.NEW:
                            LeadStatusHistory.objects.create(lead=lead, from_status=LeadStatus.NEW, to_status=status, note="Demo data")
                self.stdout.write(self.style.SUCCESS(f"Simulated scans and {Lead.objects.count()} total leads."))
