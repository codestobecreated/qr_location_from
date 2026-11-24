"""QR image rendering, ZIP bundles and print-ready PDF generation (Pillow + qrcode only)."""
import io
import re
import zlib
from functools import lru_cache
from pathlib import Path

import qrcode
from django.conf import settings
from django.core.files.base import ContentFile
from PIL import Image, ImageDraw, ImageFont
from qrcode.constants import ERROR_CORRECT_H

BRAND_GREEN = (27, 128, 66)
BRAND_BLUE = (0, 102, 255)
INK = (15, 23, 42)
MUTED = (71, 85, 105)

FONT_CANDIDATES = {
    "bold": [
        "static/fonts/Inter-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
    ],
    "regular": [
        "static/fonts/Inter-Regular.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        "/Library/Fonts/Arial.ttf",
    ],
}


@lru_cache(maxsize=64)
def get_font(size, weight="regular"):
    for candidate in FONT_CANDIDATES[weight]:
        path = Path(candidate)
        if not path.is_absolute():
            path = Path(settings.BASE_DIR) / path
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size)
            except OSError:
                continue
    return ImageFont.load_default(size=size)


@lru_cache(maxsize=1)
def get_logo():
    path = Path(settings.BASE_DIR) / "static" / "images" / "relux-logo.png"
    if not path.exists():
        return None
    logo = Image.open(path).convert("RGBA")
    bbox = logo.getbbox()
    return logo.crop(bbox) if bbox else logo


def safe_filename(text):
    return re.sub(r"[^A-Za-z0-9_-]+", "-", text).strip("-")[:80] or "station"


def qr_matrix_image(url, box_size=12, border=4):
    qr = qrcode.QRCode(version=None, error_correction=ERROR_CORRECT_H, box_size=box_size, border=border)
    qr.add_data(url)
    qr.make(fit=True)
    return qr.make_image(fill_color="black", back_color="white").convert("RGB")


def _fit_text(draw, text, max_width, size, weight, min_size=14):
    while size > min_size:
        font = get_font(size, weight)
        if draw.textlength(text, font=font) <= max_width:
            return font, text
        size -= 2
    font = get_font(min_size, weight)
    while text and draw.textlength(text + "…", font=font) > max_width:
        text = text[:-1]
    return font, text + "…"


def render_labelled_qr(mapping, width=900):
    """A branded card: logo, 'Scan to enquire', QR code, station + location details."""
    station = mapping.station
    location = station.location
    pad = int(width * 0.06)
    qr_size = width - 2 * pad
    qr_img = qr_matrix_image(mapping.public_url).resize((qr_size, qr_size), Image.NEAREST)

    header_h = int(width * 0.22)
    footer_h = int(width * 0.36)
    height = header_h + qr_size + footer_h
    card = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(card)

    # Header: logo + call to action
    logo = get_logo()
    if logo:
        target_h = int(header_h * 0.55)
        ratio = target_h / logo.height
        lg = logo.resize((int(logo.width * ratio), target_h), Image.LANCZOS)
        card.paste(lg, ((width - lg.width) // 2, int(header_h * 0.08)), lg)
        cta_y = int(header_h * 0.08) + target_h + int(width * 0.012)
    else:
        font = get_font(int(width * 0.07), "bold")
        draw.text((width // 2, int(header_h * 0.35)), "RELUX ELECTRIC", font=font, fill=BRAND_GREEN, anchor="mm")
        cta_y = int(header_h * 0.6)
    cta_font = get_font(int(width * 0.042), "bold")
    draw.text((width // 2, cta_y), "SCAN TO ENQUIRE", font=cta_font, fill=BRAND_BLUE, anchor="ma")

    card.paste(qr_img, (pad, header_h))

    # Footer: station details
    y = header_h + qr_size + int(width * 0.015)
    max_w = width - 2 * pad
    font, text = _fit_text(draw, station.name, max_w, int(width * 0.055), "bold")
    draw.text((width // 2, y), text, font=font, fill=INK, anchor="ma")
    y += int(width * 0.075)
    font, text = _fit_text(draw, location.name, max_w, int(width * 0.038), "regular")
    draw.text((width // 2, y), text, font=font, fill=MUTED, anchor="ma")
    y += int(width * 0.055)
    font, text = _fit_text(draw, f"{station.city}, {station.state}", max_w, int(width * 0.034), "regular")
    draw.text((width // 2, y), text, font=font, fill=MUTED, anchor="ma")
    y += int(width * 0.065)
    id_font = get_font(int(width * 0.03), "bold")
    draw.text((width // 2, y), f"Station ID: {station.station_id}", font=id_font, fill=BRAND_GREEN, anchor="ma")

    # Thin brand border
    bw = max(3, width // 150)
    draw.rectangle([bw // 2, bw // 2, width - bw // 2 - 1, height - bw // 2 - 1], outline=BRAND_GREEN, width=bw)
    return card


def build_qr_image(mapping, save=True):
    """(Re)generate and store the PNG for a mapping. The token/URL are never changed here."""
    img = render_labelled_qr(mapping)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True, dpi=(300, 300))
    filename = f"{safe_filename(mapping.station.station_id or str(mapping.station_id))}_{mapping.token[:8]}.png"
    old_name = mapping.image.name if mapping.image else None
    mapping.image.save(filename, ContentFile(buf.getvalue()), save=False)
    mapping.encoded_url = mapping.public_url
    if save:
        type(mapping).objects.filter(pk=mapping.pk).update(image=mapping.image.name, encoded_url=mapping.encoded_url)
    if old_name and old_name != mapping.image.name:
        try:
            mapping.image.storage.delete(old_name)
        except OSError:
            pass
    return mapping


def ensure_image(mapping):
    if mapping.image_is_stale or not mapping.image.storage.exists(mapping.image.name):
        build_qr_image(mapping)
    return mapping


def png_bytes(mapping):
    ensure_image(mapping)
    with mapping.image.open("rb") as fh:
        return fh.read()


def png_download_name(mapping):
    return f"RELUX_{safe_filename(mapping.station.station_id)}_{safe_filename(mapping.station.name)}.png"


# ---------------------------------------------------------------------------
# Print-ready PDF (A4) – a tiny streaming PDF writer so 1,000+ pages never sit in memory.
# ---------------------------------------------------------------------------
A4_MM = (210, 297)


class PDFWriter:
    """Writes one full-page lossless grayscale image per PDF page."""

    def __init__(self, fh, dpi=200):
        self.fh = fh
        self.dpi = dpi
        self.offsets = []
        self.page_ids = []
        self.pos = 0
        self._write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        # Objects 1 (catalog) and 2 (pages) are written at the end.
        self.next_id = 3
        self.offsets = [0, 0, 0]

    def _write(self, data):
        self.fh.write(data)
        self.pos += len(data)

    def _obj(self, body):
        oid = self.next_id
        self.next_id += 1
        self.offsets.append(self.pos)
        self._write(f"{oid} 0 obj\n".encode() + body + b"\nendobj\n")
        return oid

    def _stream_obj(self, header, data):
        oid = self.next_id
        self.next_id += 1
        self.offsets.append(self.pos)
        self._write(f"{oid} 0 obj\n<<{header} /Length {len(data)}>>\nstream\n".encode())
        self._write(data)
        self._write(b"\nendstream\nendobj\n")
        return oid

    def add_page(self, image):
        img = image.convert("L")
        w_pt = A4_MM[0] / 25.4 * 72
        h_pt = A4_MM[1] / 25.4 * 72
        data = zlib.compress(img.tobytes(), 6)
        img_id = self._stream_obj(
            f"/Type /XObject /Subtype /Image /Width {img.width} /Height {img.height} "
            f"/ColorSpace /DeviceGray /BitsPerComponent 8 /Filter /FlateDecode",
            data,
        )
        content = f"q {w_pt:.2f} 0 0 {h_pt:.2f} 0 0 cm /Im0 Do Q".encode()
        content_id = self._stream_obj("", content)
        page_id = self._obj(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {w_pt:.2f} {h_pt:.2f}] "
            f"/Resources << /XObject << /Im0 {img_id} 0 R >> >> /Contents {content_id} 0 R >>".encode()
        )
        self.page_ids.append(page_id)

    def close(self):
        self.offsets[1] = self.pos
        self._write(b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n")
        self.offsets[2] = self.pos
        kids = " ".join(f"{pid} 0 R" for pid in self.page_ids)
        self._write(f"2 0 obj\n<< /Type /Pages /Kids [{kids}] /Count {len(self.page_ids)} >>\nendobj\n".encode())
        xref_pos = self.pos
        count = self.next_id
        lines = [f"xref\n0 {count}\n", "0000000000 65535 f \n"]
        for oid in range(1, count):
            lines.append(f"{self.offsets[oid]:010d} 00000 n \n")
        self._write("".join(lines).encode())
        self._write(f"trailer\n<< /Size {count} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode())


def a4_canvas(dpi):
    return Image.new("L", (round(A4_MM[0] / 25.4 * dpi), round(A4_MM[1] / 25.4 * dpi)), 255)


def write_qr_pdf(mappings, fh, per_page=1, dpi=200):
    """per_page: 1 (poster), 2, 4 (2x2) or 6 (2x3) QR cards per A4 sheet, with cut margins."""
    layouts = {1: (1, 1), 2: (1, 2), 4: (2, 2), 6: (2, 3)}
    cols, rows = layouts.get(per_page, (1, 1))
    writer = PDFWriter(fh, dpi=dpi)
    page = None
    slot = 0
    margin = round(12 / 25.4 * dpi)
    gap = round(8 / 25.4 * dpi)
    for mapping in mappings:
        if page is None:
            page = a4_canvas(dpi)
            slot = 0
        cell_w = (page.width - 2 * margin - (cols - 1) * gap) // cols
        cell_h = (page.height - 2 * margin - (rows - 1) * gap) // rows
        card = render_labelled_qr(mapping, width=900)
        scale = min(cell_w / card.width, cell_h / card.height)
        card = card.resize((int(card.width * scale), int(card.height * scale)), Image.LANCZOS)
        col, row = slot % cols, slot // cols
        x = margin + col * (cell_w + gap) + (cell_w - card.width) // 2
        y = margin + row * (cell_h + gap) + (cell_h - card.height) // 2
        page.paste(card.convert("L"), (x, y))
        slot += 1
        if slot >= cols * rows:
            writer.add_page(page)
            page = None
    if page is not None:
        writer.add_page(page)
    writer.close()
