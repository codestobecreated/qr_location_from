import io
import shutil
import tempfile
import zipfile

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.leads.models import Lead, LeadStatus
from apps.locations.models import Location
from apps.qrcodes.models import QRCodeMapping, QRScanEvent, QRTokenHistory
from apps.stations.models import ChargingStation

MOBILE_UA = ("Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) "
             "Chrome/126.0 Mobile Safari/537.36")

TEMP_MEDIA = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=TEMP_MEDIA, QR_BASE_URL="https://leads.example.com")
class BaseCase(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEMP_MEDIA, ignore_errors=True)

    def setUp(self):
        self.admin = User.objects.create_user("boss", "boss@example.com", "Str0ng-Passw0rd!", role=User.Role.SUPER_ADMIN)
        self.loc = Location.objects.create(name="Chennai Hub", address="GST Road", city="Chennai", state="Tamil Nadu", pincode="600045")
        self.loc2 = Location.objects.create(name="Pune Hub", address="FC Road", city="Pune", state="Maharashtra", pincode="411004")
        self.station = ChargingStation.objects.create(location=self.loc, name="RELUX Tambaram Station", address="GST Road")
        self.station2 = ChargingStation.objects.create(location=self.loc2, name="RELUX Pune Station", address="FC Road")
        self.mapping = self.station.qr_mapping
        self.mapping2 = self.station2.qr_mapping

    def enquiry(self, token, **overrides):
        url = reverse("public:qr_landing", args=[token])
        r = self.client.get(url, HTTP_USER_AGENT=MOBILE_UA)
        key = r.context["form"]["submission_key"].value() if r.context and r.context.get("form") else ""
        data = {"full_name": "Arun Kumar", "mobile": "9876543210", "email": "arun@example.com",
                "category": "franchise", "message": "Interested", "consent": "on", "submission_key": key}
        data.update(overrides)
        return self.client.post(url, data, HTTP_USER_AGENT=MOBILE_UA), key


class QRMappingTests(BaseCase):
    def test_station_gets_unique_permanent_qr(self):
        self.assertTrue(self.mapping.token)
        self.assertNotEqual(self.mapping.token, self.mapping2.token)
        self.assertEqual(self.mapping.public_url, f"https://leads.example.com/q/{self.mapping.token}/")
        self.assertGreaterEqual(len(self.mapping.token), 20)

    def test_printed_card_rendered_with_station_id(self):
        from apps.qrcodes.services import ensure_image

        m = QRCodeMapping.objects.get(pk=self.mapping.pk)
        ensure_image(m)
        self.assertTrue(m.image)
        self.assertFalse(m.image_is_stale)
        self.assertTrue(self.station.station_id.startswith("STN-"))

    def test_editing_station_keeps_token(self):
        token = self.mapping.token
        self.station.name = "Renamed Station"
        self.station.save()
        self.station.refresh_from_db()
        self.assertEqual(self.station.qr_mapping.token, token)

    def test_token_and_station_cannot_be_changed_or_deleted(self):
        self.mapping.token = "hijacked"
        with self.assertRaises(ValidationError):
            self.mapping.save()
        m = QRCodeMapping.objects.get(pk=self.mapping.pk)
        m.station = self.station2
        with self.assertRaises(ValidationError):
            m.save()
        with self.assertRaises(ValidationError):
            QRCodeMapping.objects.get(pk=self.mapping.pk).delete()

    def test_regenerate_preserves_history_and_retires_old_token(self):
        old = self.mapping.token
        new_mapping = self.mapping.regenerate(self.admin, "Sticker damaged")
        self.assertNotEqual(new_mapping.token, old)
        self.assertTrue(QRTokenHistory.objects.filter(token=old, station=self.station).exists())
        r = self.client.get(reverse("public:qr_landing", args=[old]), HTTP_USER_AGENT=MOBILE_UA)
        self.assertEqual(r.status_code, 410)
        r = self.client.get(reverse("public:qr_landing", args=[new_mapping.token]), HTTP_USER_AGENT=MOBILE_UA)
        self.assertContains(r, "RELUX Tambaram Station")


class PublicFlowTests(BaseCase):
    def test_scan_shows_station_and_records_event(self):
        r = self.client.get(reverse("public:qr_landing", args=[self.mapping.token]), HTTP_USER_AGENT=MOBILE_UA)
        self.assertContains(r, "RELUX Tambaram Station")
        self.assertContains(r, "Chennai Hub")
        ev = QRScanEvent.objects.get()
        self.assertEqual(ev.station, self.station)
        self.assertFalse(ev.is_bot)
        self.assertEqual(ev.device_type, "Mobile")

    def test_bot_scan_flagged(self):
        self.client.get(reverse("public:qr_landing", args=[self.mapping.token]), HTTP_USER_AGENT="WhatsApp/2.23.20.0 A")
        self.assertTrue(QRScanEvent.objects.get().is_bot)

    def test_invalid_token_404(self):
        r = self.client.get("/q/not-a-real-token/", HTTP_USER_AGENT=MOBILE_UA)
        self.assertEqual(r.status_code, 404)

    def test_submission_creates_lead_bound_to_token_station(self):
        # Attempt to inject another station – must be ignored.
        r, _ = self.enquiry(self.mapping.token, station=self.station2.pk, station_id=self.station2.pk,
                            location=self.loc2.pk)
        self.assertRedirects(r, reverse("public:thank_you", args=[self.mapping.token]))
        lead = Lead.objects.get()
        self.assertEqual(lead.station, self.station)
        self.assertEqual(lead.location, self.loc)
        self.assertEqual(lead.qr_token, self.mapping.token)
        self.assertEqual(lead.station_code, self.station.station_id)
        self.assertEqual(lead.status, LeadStatus.NEW)
        self.assertTrue(lead.status_history.exists())
        self.assertTrue(QRScanEvent.objects.get().submitted)
        r = self.client.get(reverse("public:thank_you", args=[self.mapping.token]))
        self.assertContains(r, lead.lead_id)

    def test_double_submit_same_form_creates_one_lead(self):
        url = reverse("public:qr_landing", args=[self.mapping.token])
        r, key = self.enquiry(self.mapping.token)
        data = {"full_name": "Arun Kumar", "mobile": "9876543210", "category": "franchise", "consent": "on",
                "submission_key": key}
        self.client.post(url, data, HTTP_USER_AGENT=MOBILE_UA)
        self.assertEqual(Lead.objects.count(), 1)

    def test_repeat_enquiry_in_window_flagged_duplicate(self):
        self.enquiry(self.mapping.token)
        self.enquiry(self.mapping.token)
        self.assertEqual(Lead.objects.count(), 2)
        self.assertEqual(Lead.objects.filter(is_duplicate=False).count(), 1)

    def test_validation_errors(self):
        r, _ = self.enquiry(self.mapping.token, mobile="12345", consent="")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Lead.objects.count(), 0)

    def test_inactive_station_does_not_accept_or_redirect(self):
        ChargingStation.objects.filter(pk=self.station.pk).update(status="inactive")
        r = self.client.get(reverse("public:qr_landing", args=[self.mapping.token]), HTTP_USER_AGENT=MOBILE_UA)
        self.assertContains(r, "not accepting enquiries")
        self.assertNotContains(r, "RELUX Pune Station")
        self.client.post(reverse("public:qr_landing", args=[self.mapping.token]),
                         {"full_name": "A B", "mobile": "9876543210", "category": "general", "consent": "on"})
        self.assertEqual(Lead.objects.count(), 0)

    def test_honeypot_drops_submission(self):
        self.enquiry(self.mapping.token, website="http://spam")
        self.assertEqual(Lead.objects.count(), 0)

    def test_lead_source_is_immutable(self):
        self.enquiry(self.mapping.token)
        lead = Lead.objects.get()
        lead.station = self.station2
        with self.assertRaises(ValidationError):
            lead.save()
        lead = Lead.objects.get()
        lead.status = LeadStatus.CONTACTED
        lead.save()  # workflow fields may change


class AdminAndPermissionTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.manager = User.objects.create_user("mgr", "m@example.com", "Str0ng-Passw0rd!", role=User.Role.MANAGER)
        self.manager.assigned_locations.add(self.loc)
        self.staff = User.objects.create_user("stf", "s@example.com", "Str0ng-Passw0rd!", role=User.Role.STAFF)
        self.enquiry(self.mapping.token)
        self.client.logout()
        self.enquiry(self.mapping2.token, mobile="9123456780")
        self.client.logout()

    def test_login_required(self):
        r = self.client.get(reverse("dashboard:home"))
        self.assertEqual(r.status_code, 302)
        self.assertIn(reverse("accounts:login"), r["Location"])

    def test_admin_pages_render(self):
        self.client.force_login(self.admin)
        lead = Lead.objects.first()
        urls = [
            reverse("dashboard:home"), reverse("locations:list"), reverse("locations:detail", args=[self.loc.pk]),
            reverse("locations:create"), reverse("stations:list"), reverse("stations:detail", args=[self.station.pk]),
            reverse("stations:create"), reverse("qrcodes:list"), reverse("qrcodes:detail", args=[self.mapping.pk]),
            reverse("qrcodes:regenerate", args=[self.mapping.pk]), reverse("leads:list"),
            reverse("leads:detail", args=[lead.pk]), reverse("analytics:overview"),
            reverse("analytics:overview") + "?tab=stations&period=weekly&range=all",
            reverse("analytics:overview") + "?period=monthly&range=365d",
            reverse("analytics:location", args=[self.loc.pk]), reverse("analytics:station", args=[self.station.pk]),
            reverse("reports:index"), reverse("accounts:user_list"), reverse("accounts:settings"),
            reverse("accounts:audit_log"), reverse("locations:import"), reverse("stations:import"),
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_staff_scope(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse("locations:list")).status_code, 403)
        self.assertEqual(self.client.get(reverse("analytics:overview")).status_code, 403)
        r = self.client.get(reverse("leads:list"))
        self.assertEqual(len(r.context["page"].object_list), 0)
        lead = Lead.objects.first()
        self.assertEqual(self.client.get(reverse("leads:detail", args=[lead.pk])).status_code, 404)
        lead.assigned_to = self.staff
        lead.save()
        self.assertEqual(self.client.get(reverse("leads:detail", args=[lead.pk])).status_code, 200)
        r = self.client.post(reverse("leads:update_status", args=[lead.pk]), {"status": "contacted"})
        lead.refresh_from_db()
        self.assertEqual(lead.status, "contacted")
        self.assertEqual(lead.status_history.count(), 2)

    def test_manager_sees_only_assigned_locations(self):
        self.client.force_login(self.manager)
        r = self.client.get(reverse("leads:list"))
        stations = {l.station_id for l in r.context["page"].object_list}
        self.assertEqual(stations, {self.station.pk})
        self.assertEqual(self.client.get(reverse("locations:create")).status_code, 403)
        self.assertEqual(self.client.get(reverse("locations:detail", args=[self.loc2.pk])).status_code, 404)

    def test_exports_and_downloads(self):
        self.client.force_login(self.admin)
        for name in ("leads:export", "locations:export", "stations:export"):
            for fmt in ("csv", "xlsx"):
                r = self.client.get(reverse(name) + f"?format={fmt}")
                self.assertEqual(r.status_code, 200, name)
                body = b"".join(r.streaming_content) if r.streaming else r.content
                self.assertTrue(body)
        for report in ("full", "station_performance", "location_performance", "daily", "weekly", "monthly",
                       "city", "state", "category", "scans", "leads"):
            r = self.client.get(reverse("reports:index") + f"?report={report}&range=all")
            self.assertEqual(r.status_code, 200, report)
        r = self.client.get(reverse("qrcodes:png", args=[self.mapping.pk]))
        self.assertEqual(r["Content-Type"], "image/png")
        r = self.client.get(reverse("qrcodes:pdf", args=[self.mapping.pk]))
        pdf = b"".join(r.streaming_content)
        self.assertTrue(pdf.startswith(b"%PDF"))
        r = self.client.post(reverse("qrcodes:bulk_download"), {"scope": "filtered", "format": "zip"})
        data = b"".join(r.streaming_content)
        names = zipfile.ZipFile(io.BytesIO(data)).namelist()
        self.assertIn("manifest.csv", names)
        self.assertEqual(len([n for n in names if n.endswith(".png")]), 2)
        r = self.client.post(reverse("qrcodes:bulk_download"), {"scope": "filtered", "format": "pdf", "per_page": "4"})
        self.assertTrue(b"".join(r.streaming_content).startswith(b"%PDF"))

    def test_location_delete_blocked_when_in_use(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("locations:delete", args=[self.loc.pk]))
        self.assertTrue(Location.objects.filter(pk=self.loc.pk).exists())
        empty = Location.objects.create(name="Empty", address="x", city="X", state="Y", pincode="123456")
        self.client.post(reverse("locations:delete", args=[empty.pk]))
        self.assertFalse(Location.objects.filter(pk=empty.pk).exists())

    def test_regenerate_requires_confirmation(self):
        self.client.force_login(self.admin)
        token = self.mapping.token
        self.client.post(reverse("qrcodes:regenerate", args=[self.mapping.pk]),
                         {"confirm_station_id": "WRONG", "reason": "Testing the flow", "acknowledge": "on"})
        self.assertEqual(QRCodeMapping.objects.get(pk=self.mapping.pk).token, token)
        self.client.post(reverse("qrcodes:regenerate", args=[self.mapping.pk]),
                         {"confirm_station_id": self.station.station_id, "reason": "Testing the flow", "acknowledge": "on"})
        self.assertNotEqual(QRCodeMapping.objects.get(pk=self.mapping.pk).token, token)


class ImportTests(BaseCase):
    def test_location_and_station_csv_import(self):
        self.client.force_login(self.admin)
        csv = ("Location ID,Location Name,Address,City,District,State,PIN Code,Latitude,Longitude,Contact Person,Contact Number,Status\n"
               ",Coimbatore Hub,Avinashi Road,Coimbatore,Coimbatore,Tamil Nadu,641014,11.01,76.95,Ravi,9876543210,Active\n"
               "CUST-01,Madurai Hub,Bypass Road,Madurai,Madurai,Tamil Nadu,625010,,,,,Inactive\n"
               ",Bad Row,,Madurai,,Tamil Nadu,12,,,,,Active\n")
        r = self.client.post(reverse("locations:import"), {
            "file": SimpleUploadedFile("locs.csv", csv.encode()), "update_existing": "on"})
        result = r.context["result"]
        self.assertEqual(result["created"], 2)
        self.assertEqual(len(result["errors"]), 1)
        self.assertTrue(Location.objects.filter(location_id="CUST-01", status="inactive").exists())

        csv2 = ("Location ID,Station Name,Station Address,Charger Type,Charger Capacity,Status\n"
                "CUST-01,Madurai Station A,Bypass Road,DC – CCS2,60,Active\n"
                "CUST-01,Madurai Station B,Bypass Road,type 2,22 kW,Active\n"
                "NOPE,Ghost,Somewhere,,,Active\n")
        r = self.client.post(reverse("stations:import"), {"file": SimpleUploadedFile("st.csv", csv2.encode())})
        result = r.context["result"]
        self.assertEqual(result["created"], 2)
        self.assertEqual(len(result["errors"]), 1)
        tokens = set(QRCodeMapping.objects.values_list("token", flat=True))
        self.assertEqual(len(tokens), ChargingStation.objects.count())
