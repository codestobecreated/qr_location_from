import shutil
import tempfile
from datetime import timedelta

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.leads.models import Lead, LeadStatus
from apps.qrcodes.models import QRCodeMapping, QRScanEvent, get_main_qr
from apps.qrcodes.services import ensure_image
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
        cache.clear()  # independent per-IP rate-limit counters for every test
        self.admin = User.objects.create_user("boss", "boss@example.com", "Str0ng-Passw0rd!", role=User.Role.SUPER_ADMIN)
        self.qr = get_main_qr()

    def enquiry(self, path="/qr", **overrides):
        r = self.client.get(path, HTTP_USER_AGENT=MOBILE_UA)
        key = r.context["form"]["submission_key"].value() if r.context and r.context.get("form") else ""
        data = {"full_name": "Arun Kumar", "mobile": "9876543210", "email": "arun@example.com",
                "category": "franchise", "message": "Interested", "consent": "on", "submission_key": key}
        data.update(overrides)
        return self.client.post(path, data, HTTP_USER_AGENT=MOBILE_UA), key


class OneQRTests(BaseCase):
    """There is exactly one QR; its URL is <site>/qr and it never changes."""

    def test_single_main_qr_with_fixed_url(self):
        self.assertEqual(self.qr.qr_url, "https://leads.example.com/qr")
        self.assertEqual(reverse("public:main_qr"), "/qr")
        self.assertEqual(get_main_qr().pk, self.qr.pk)                 # never a second one
        self.assertEqual(QRCodeMapping.objects.filter(is_main=True).count(), 1)

    def test_url_survives_setting_changes_and_rename(self):
        url = self.qr.qr_url
        with override_settings(QR_BASE_URL="https://some-other-domain.example"):
            m = get_main_qr()
            self.assertEqual(m.qr_url, url)
            ensure_image(m)
            self.assertEqual(m.encoded_url, url)                       # printed QR still encodes /qr
        station = self.qr.station
        station.name = "Renamed"
        station.save()
        self.assertEqual(QRCodeMapping.objects.get(pk=self.qr.pk).qr_url, url)

    def test_qr_cannot_be_changed_or_deleted(self):
        for field, value in (("token", "x"), ("qr_url", "https://evil.example/qr"), ("is_main", False)):
            m = QRCodeMapping.objects.get(pk=self.qr.pk)
            setattr(m, field, value)
            with self.assertRaises(ValidationError, msg=field):
                m.save()
        with self.assertRaises(ValidationError):
            QRCodeMapping.objects.get(pk=self.qr.pk).delete()

    def test_no_create_import_regenerate_location_or_station_pages(self):
        self.client.force_login(self.admin)
        for path in ("/qr-codes/create/", "/qr-codes/import/", "/qr-codes/1/regenerate/", "/locations/", "/stations/"):
            self.assertEqual(self.client.get(path).status_code, 404, path)
        for name in ("qrcodes:create", "qrcodes:import", "qrcodes:regenerate", "locations:list", "stations:list"):
            with self.assertRaises(NoReverseMatch):
                reverse(name)

    def test_qr_page_png_pdf(self):
        self.client.force_login(self.admin)
        r = self.client.get(reverse("qrcodes:list"))
        self.assertContains(r, "https://leads.example.com/qr")
        self.assertEqual(self.client.get(reverse("qrcodes:png", args=[self.qr.pk]))["Content-Type"], "image/png")
        pdf = b"".join(self.client.get(reverse("qrcodes:pdf", args=[self.qr.pk]) + "?per_page=4").streaming_content)
        self.assertTrue(pdf.startswith(b"%PDF"))

    def test_pausing_keeps_url(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("qrcodes:toggle", args=[self.qr.pk]))
        m = QRCodeMapping.objects.get(pk=self.qr.pk)
        self.assertFalse(m.is_active)
        self.assertEqual(m.qr_url, "https://leads.example.com/qr")


class PublicFormTests(BaseCase):
    def test_scan_shows_only_the_form_and_records_scan(self):
        for path in ("/qr", "/qr/"):
            r = self.client.get(path, HTTP_USER_AGENT=MOBILE_UA)
            self.assertEqual(r.status_code, 200)
            self.assertContains(r, 'name="full_name"')
            # Ignore the enquiry-type option "EV Charging Station Installation" – it is not location data.
            page = r.content.decode().replace("EV Charging Station Installation", "")
            for text in ("Station", "Location", "City", "Address", "You are at"):
                self.assertNotIn(text, page)
        self.assertEqual(QRScanEvent.objects.filter(mapping=self.qr, is_bot=False).count(), 2)

    def test_bot_scan_flagged(self):
        self.client.get("/qr", HTTP_USER_AGENT="WhatsApp/2.23.20.0 A")
        self.assertTrue(QRScanEvent.objects.get().is_bot)

    def test_submit_stores_lead(self):
        r, _ = self.enquiry()
        self.assertRedirects(r, "/qr/thank-you/")
        lead = Lead.objects.get()
        self.assertEqual(lead.qr_mapping, self.qr)
        self.assertEqual((lead.full_name, lead.mobile, lead.category), ("Arun Kumar", "9876543210", "franchise"))
        self.assertEqual(lead.status, LeadStatus.NEW)
        self.assertTrue(QRScanEvent.objects.get().submitted)
        self.assertContains(self.client.get("/qr/thank-you/"), lead.lead_id)

    def test_double_submit_same_form_creates_one_lead(self):
        r, key = self.enquiry()
        self.client.post("/qr", {"full_name": "Arun Kumar", "mobile": "9876543210", "category": "franchise",
                                 "consent": "on", "submission_key": key}, HTTP_USER_AGENT=MOBILE_UA)
        self.assertEqual(Lead.objects.count(), 1)

    def test_repeat_enquiry_flagged_duplicate(self):
        self.enquiry()
        self.enquiry()
        self.assertEqual(Lead.objects.count(), 2)
        self.assertEqual(Lead.objects.filter(is_duplicate=False).count(), 1)

    def test_validation_errors(self):
        r, _ = self.enquiry(mobile="12345", consent="")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Lead.objects.count(), 0)

    def test_paused_qr_does_not_accept(self):
        QRCodeMapping.objects.filter(pk=self.qr.pk).update(is_active=False)
        self.assertContains(self.client.get("/qr", HTTP_USER_AGENT=MOBILE_UA), "not accepting enquiries")
        self.client.post("/qr", {"full_name": "A B", "mobile": "9876543210", "category": "general", "consent": "on"})
        self.assertEqual(Lead.objects.count(), 0)

    def test_honeypot_drops_submission(self):
        self.enquiry(website="http://spam")
        self.assertEqual(Lead.objects.count(), 0)

    def test_lead_source_is_immutable(self):
        self.enquiry()
        lead = Lead.objects.get()
        lead.full_name = "Changed"
        with self.assertRaises(ValidationError):
            lead.save()
        lead = Lead.objects.get()
        lead.status = LeadStatus.CONTACTED
        lead.save()

    def test_older_q_token_links_still_work(self):
        old = ChargingStation.objects.create(name="Old sticker").qr_mapping
        r = self.client.get(f"/q/{old.token}/", HTTP_USER_AGENT=MOBILE_UA)
        self.assertContains(r, 'name="full_name"')


class AdminTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.manager = User.objects.create_user("mgr", "m@example.com", "Str0ng-Passw0rd!", role=User.Role.MANAGER)
        self.staff = User.objects.create_user("stf", "s@example.com", "Str0ng-Passw0rd!", role=User.Role.STAFF)
        self.enquiry()
        self.client.logout()
        self.enquiry(mobile="9123456780")
        self.client.logout()

    def test_login_required(self):
        r = self.client.get(reverse("dashboard:home"))
        self.assertEqual(r.status_code, 302)
        self.assertIn(reverse("accounts:login"), r["Location"])

    def test_admin_pages_render(self):
        self.client.force_login(self.admin)
        lead = Lead.objects.first()
        urls = [
            reverse("dashboard:home"), reverse("qrcodes:list"), reverse("leads:list"),
            reverse("leads:detail", args=[lead.pk]), reverse("analytics:overview"),
            reverse("analytics:overview") + "?period=weekly&range=all",
            reverse("analytics:overview") + "?period=monthly&range=365d",
            reverse("analytics:overview") + "?period=yearly&range=all",
            reverse("analytics:station", args=[self.qr.station.pk]),
            reverse("reports:index"), reverse("accounts:user_list"), reverse("accounts:user_create"),
            reverse("accounts:settings"), reverse("accounts:audit_log"),
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_staff_scope(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse("qrcodes:list")).status_code, 403)
        self.assertEqual(self.client.get(reverse("analytics:overview")).status_code, 403)
        self.assertEqual(len(self.client.get(reverse("leads:list")).context["page"].object_list), 0)
        lead = Lead.objects.first()
        lead.assigned_to = self.staff
        lead.save()
        self.assertEqual(self.client.get(reverse("leads:detail", args=[lead.pk])).status_code, 200)
        self.client.post(reverse("leads:update_status", args=[lead.pk]), {"status": "contacted"})
        lead.refresh_from_db()
        self.assertEqual(lead.status, "contacted")
        self.assertEqual(lead.status_history.count(), 2)

    def test_manager_sees_all_leads(self):
        self.client.force_login(self.manager)
        self.assertEqual(len(self.client.get(reverse("leads:list")).context["page"].object_list), 2)
        self.assertEqual(self.client.get(reverse("qrcodes:list")).status_code, 200)

    def test_exports_and_reports(self):
        self.client.force_login(self.admin)
        for fmt in ("csv", "xlsx"):
            r = self.client.get(reverse("leads:export") + f"?format={fmt}")
            self.assertEqual(r.status_code, 200)
            self.assertTrue(b"".join(r.streaming_content) if r.streaming else r.content)
        for report in ("full", "daily", "weekly", "monthly", "yearly", "category", "scans", "leads"):
            r = self.client.get(reverse("reports:index") + f"?report={report}&range=all")
            self.assertEqual(r.status_code, 200, report)


class DashboardCountTests(BaseCase):
    def test_today_month_year_counts(self):
        self.enquiry()                                    # today
        self.client.logout()
        self.enquiry(mobile="9123456780")                 # moved to more than a year ago below
        old = Lead.objects.get(mobile="9123456780")
        Lead.objects.filter(pk=old.pk).update(submitted_at=timezone.now() - timedelta(days=400))
        self.client.force_login(self.admin)
        ctx = self.client.get(reverse("dashboard:home")).context
        stats = ctx["stats"]
        self.assertEqual((stats["today"], stats["month"], stats["year"], stats["total"]), (1, 1, 1, 2))
        self.assertEqual(sum(ctx["yearly_chart"]["leads"]), 2)
        self.assertEqual(ctx["daily_chart"]["leads"][-1], 1)
