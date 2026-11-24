"""CSV / Excel response helpers built on the csv module and openpyxl."""
import csv
from datetime import date, datetime
from decimal import Decimal

from django.http import HttpResponse, StreamingHttpResponse
from django.utils import timezone
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

HEADER_FILL = PatternFill("solid", fgColor="1B8042")
HEADER_FONT = Font(bold=True, color="FFFFFF")
FORMULA_CHARS = ("=", "+", "-", "@", "\t", "\r")


def _cell(value):
    if isinstance(value, datetime):
        if timezone.is_aware(value):
            value = timezone.localtime(value)
        return value.replace(tzinfo=None)
    if isinstance(value, Decimal):
        return float(value)
    if value is None:
        return ""
    return value


def _is_number(text):
    try:
        float(text)
        return True
    except ValueError:
        return False


def _neutralise(text):
    """Prevent spreadsheet formula injection from customer-entered text."""
    if text and text.startswith(FORMULA_CHARS) and not _is_number(text):
        return "'" + text
    return text


def _csv_value(value):
    value = _cell(value)
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.isoformat()
    return _neutralise(str(value))


class _Echo:
    def write(self, value):
        return value


def csv_response(filename, headers, rows):
    writer = csv.writer(_Echo())

    def stream():
        yield "﻿"  # Excel-friendly UTF-8 BOM
        yield writer.writerow(headers)
        for row in rows:
            yield writer.writerow([_csv_value(v) for v in row])

    response = StreamingHttpResponse(stream(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}.csv"'
    return response


def xlsx_response(filename, sheets):
    """sheets: list of (title, headers, rows)."""
    wb = Workbook()
    wb.remove(wb.active)
    for title, headers, rows in sheets:
        ws = wb.create_sheet(title=title[:31])
        ws.append(headers)
        for cell in ws[1]:
            cell.fill = HEADER_FILL
            cell.font = HEADER_FONT
            cell.alignment = Alignment(vertical="center")
        widths = [len(str(h)) for h in headers]
        for row in rows:
            values = []
            for i, v in enumerate(row):
                v = _cell(v)
                if isinstance(v, str):
                    v = _neutralise(v)
                values.append(v)
                if i < len(widths):
                    widths[i] = min(max(widths[i], len(str(v))), 60)
            ws.append(values)
        for i, w in enumerate(widths, start=1):
            ws.column_dimensions[get_column_letter(i)].width = w + 2
        ws.freeze_panes = "A2"
        if ws.max_row > 1:
            ws.auto_filter.ref = ws.dimensions
    response = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = f'attachment; filename="{filename}.xlsx"'
    wb.save(response)
    return response


def export_response(fmt, filename, headers, rows, sheet_title="Data"):
    stamp = timezone.localtime().strftime("%Y%m%d_%H%M")
    name = f"{filename}_{stamp}"
    if fmt == "csv":
        return csv_response(name, headers, rows)
    return xlsx_response(name, [(sheet_title, headers, list(rows))])


def normalise_header(h):
    return "_".join(str(h or "").strip().lower().replace("/", " ").replace("-", " ").split())


def read_tabular_upload(upload):
    """Return (headers, list of row dicts) from an uploaded .xlsx or .csv file."""
    name = upload.name.lower()
    if name.endswith(".csv"):
        raw = upload.read()
        text = None
        for enc in ("utf-8-sig", "cp1252", "latin-1"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        rows = list(csv.reader(text.splitlines()))
    elif name.endswith((".xlsx", ".xlsm")):
        wb = load_workbook(upload, read_only=True, data_only=True)
        ws = wb.worksheets[0]
        rows = [["" if c is None else c for c in r] for r in ws.iter_rows(values_only=True)]
        wb.close()
    else:
        raise ValueError("Unsupported file type. Upload an .xlsx or .csv file.")
    rows = [r for r in rows if any(str(c).strip() for c in r)]
    if not rows:
        raise ValueError("The file is empty.")
    headers = [normalise_header(h) for h in rows[0]]
    data = []
    for r in rows[1:]:
        r = list(r) + [""] * (len(headers) - len(r))
        item = {}
        for i, header in enumerate(headers):
            if not header:
                continue
            v = r[i]
            if isinstance(v, float) and v.is_integer():
                v = int(v)
            item[header] = str(v).strip()
        data.append(item)
    return headers, data
