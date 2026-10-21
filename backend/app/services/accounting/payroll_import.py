"""Import a client's annual payroll summary (Excel or CSV, one row per employee) into alphalist rows.

Every client's sheet is laid out differently: the firm maps each column to a field once and the mapping is
remembered per company. ``suggest_mapping`` guesses from the headers (a saved mapping wins).
"""

import csv
import io
import re
import zipfile
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from openpyxl import load_workbook

from app.services.accounting.compute.alphalist import FIELD_LABELS, MONEY

MAX_ROWS = 5000
MAX_READ_ROWS = MAX_ROWS * 4 + 50     # physical rows read (blank ones included) before giving up on a sheet
MAX_COLUMNS = 120
MAX_UNZIPPED = 60 * 1024 * 1024     # an .xlsx is a zip: refuse ones that inflate past this (zip bombs)
# Extra pseudo-field: one "Last, First Middle" column.
IMPORT_FIELDS = {"full_name": "Full name (Last, First Middle)", **FIELD_LABELS}
DATES = ("employed_from", "employed_to", "birth_date", "prev_from", "prev_to")

# Normalised header fragments → field, checked in order (more specific first).
_SYNONYMS: tuple[tuple[str, str], ...] = (
    (r"prev.*tin|tin.*prev", "prev_tin"), (r"prev.*(employer|company).*name", "prev_name"),
    (r"prev.*tax|tax.*prev", "tax_withheld_prev"), (r"prev.*13", "prev_t_13th"),
    (r"prev.*(taxable|basic)", "prev_t_basic"),
    (r"^tin|tin no|taxpayer id", "tin"), (r"last ?name|surname|family", "last_name"),
    (r"first ?name|given", "first_name"), (r"middle", "middle_name"),
    (r"^(employee )?name$|full ?name|employee name|^employees?$", "full_name"),
    (r"nationality|citizenship", "nationality"), (r"status", "status"),
    (r"(date )?(hired|start|from)", "employed_from"), (r"(date )?(resign|separat|end|to)\b", "employed_to"),
    (r"reason", "separation"), (r"\bmwe\b|minimum wage earner", "mwe"), (r"region", "region"),
    (r"(smw|minimum wage).*day|daily rate", "smw_day"), (r"(smw|minimum wage).*month", "smw_month"),
    (r"(smw|minimum wage).*year", "smw_year"), (r"factor", "factor"),
    (r"birth", "birth_date"), (r"zip", "zip_code"), (r"address", "address"), (r"contact|phone|mobile", "contact"),
    (r"holiday", "nt_holiday"), (r"night", "nt_night"),
    (r"taxable 13|13.*excess|excess.*13", "t_13th"), (r"13|thirteenth|bonus", "nt_13th"),
    (r"de ?minimis", "nt_deminimis"), (r"sss|phil ?health|phic|pag.?ibig|hdmf|contribution|union", "nt_contributions"),
    (r"non.?taxable.*(salar|other)|other non.?taxable|exempt", "nt_other"),
    (r"representation", "t_representation"), (r"transportation", "t_transportation"), (r"cola|living", "t_cola"),
    (r"housing", "t_housing"), (r"commission", "t_commission"), (r"profit", "t_profit_sharing"),
    (r"fee|director", "t_fees"), (r"hazard", "t_hazard"), (r"overtime|\bot\b", "t_overtime"),
    (r"allowance", "t_others"),
    (r"(tax|wtax|withholding).*(dec|december)", "tax_withheld_dec"),
    (r"(tax|wtax|withholding).*(jan|nov)|tax withheld|withholding tax|\bwtax\b", "tax_withheld_jan_nov"),
    (r"pera", "pera_credit"), (r"substitut", "substituted_filing"),
    (r"(taxable )?basic|basic (salary|pay)|salary", "t_basic"),
)


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", str(text).lower()).strip()


def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _decode(data: bytes) -> str:
    """CSV text: UTF-8 (with or without a BOM), else Windows-1252 (Excel's "CSV" on Windows keeps ñ that way)."""
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def parse_sheet(data: bytes, filename: str) -> tuple[list[str], list[list[str]]]:
    """Headers and data rows of the first sheet. The header row is the first with three or more text cells.

    A sheet with more than ``MAX_ROWS`` data rows is refused (never cut short: a cut-off trial balance or journal
    file would still look whole)."""
    if filename.lower().endswith((".xlsx", ".xlsm")):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                if sum(i.file_size for i in z.infolist()) > MAX_UNZIPPED:
                    raise ValueError("That workbook is too large once unpacked; save just the payroll sheet.")
        except zipfile.BadZipFile:
            raise ValueError("Couldn't read that file as an Excel workbook.") from None
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        ws = wb.worksheets[0]
        raw = [[_cell(v) for v in row]
               for row in ws.iter_rows(values_only=True, max_row=MAX_READ_ROWS, max_col=MAX_COLUMNS)]
        wb.close()
    elif filename.lower().endswith((".csv", ".txt")):
        text = _decode(data)
        raw = [[c.strip() for c in row[:MAX_COLUMNS]]
               for _, row in zip(range(MAX_READ_ROWS), csv.reader(io.StringIO(text)))]
    else:
        raise ValueError("Upload an Excel (.xlsx) or CSV file.")
    start = next((i for i, row in enumerate(raw)
                  if sum(1 for c in row if c and not _is_number(c)) >= 3), None)
    if start is None:
        raise ValueError("Couldn't find a header row (a row naming the columns).")
    headers = raw[start]
    width = len(headers)
    rows = [(r + [""] * width)[:width] for r in raw[start + 1:] if any(c for c in r)]
    if len(rows) > MAX_ROWS or (len(raw) >= MAX_READ_ROWS and any(c for c in raw[-1])):
        raise ValueError(f"The sheet has more than {MAX_ROWS:,} rows; split it into smaller files.")
    return headers, rows


def _is_number(text: str) -> bool:
    try:
        Decimal(text.replace(",", ""))
        return True
    except InvalidOperation:
        return False


def suggest_mapping(headers: list[str], saved: dict[str, str] | None = None) -> dict[str, str]:
    """{header text: field} for the headers we recognise; a saved mapping for the same header wins."""
    saved = saved or {}
    out: dict[str, str] = {}
    taken: set[str] = set()
    for header in headers:
        if not header:
            continue
        if header in saved and saved[header] in IMPORT_FIELDS:
            out[header] = saved[header]
            taken.add(saved[header])
            continue
        norm = _norm(header)
        for pattern, key in _SYNONYMS:
            if key not in taken and re.search(pattern, norm):
                out[header] = key
                taken.add(key)
                break
    return out


def _amount(text: str) -> Decimal | None:
    t = text.replace(",", "").replace("₱", "").replace("PHP", "").strip()
    if not t or t in ("-", "–"):
        return None
    negative = t.startswith("(") and t.endswith(")")
    try:
        value = Decimal(t.strip("()"))
    except InvalidOperation:
        raise ValueError(f"'{text}' isn't an amount") from None
    return -value if negative else value


def _date(text: str) -> str | None:
    t = text.strip()
    if not t:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d-%b-%Y", "%b %d, %Y", "%B %d, %Y", "%m-%d-%Y"):
        try:
            return datetime.strptime(t[:19] if fmt == "%Y-%m-%d" else t, fmt).date().isoformat()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(t).date().isoformat()
    except ValueError:
        raise ValueError(f"'{text}' isn't a date") from None


def _yes(text: str) -> bool | None:
    t = text.strip().lower()
    if not t:
        return None
    return t in ("y", "yes", "1", "true", "x", "mwe", "✓")


def _split_name(text: str) -> tuple[str, str, str]:
    if "," in text:
        last, rest = (p.strip() for p in text.split(",", 1))
        parts = rest.split()
        if len(parts) >= 2 and len(parts[-1].rstrip(".")) <= 2:  # "Juan D." / "Maria Clara P."
            return last, " ".join(parts[:-1]), parts[-1]
        return last, rest, ""
    parts = text.split()
    if len(parts) >= 2:
        return parts[-1], " ".join(parts[:-1]), ""
    return text, "", ""


def apply_mapping(headers: list[str], rows: list[list[str]], mapping: dict[str, str]) -> tuple[list[dict], list[str]]:
    """Rows as employee dicts (JSON-ready) plus row errors. Rows without a name or TIN are skipped (totals lines)."""
    index = {field: headers.index(h) for h, field in mapping.items() if h in headers and field in IMPORT_FIELDS}
    out, errors = [], []
    for n, row in enumerate(rows, start=1):
        get = lambda f: row[index[f]].strip() if f in index else ""  # noqa: E731
        data: dict = {}
        if "full_name" in index and get("full_name"):
            data["last_name"], data["first_name"], data["middle_name"] = _split_name(get("full_name"))
        for f in ("last_name", "first_name", "middle_name"):
            if get(f):
                data[f] = get(f)
        if not (data.get("last_name") or get("tin")):
            continue
        if re.match(r"^(grand )?totals?\b", (data.get("last_name") or "").lower()):
            continue
        try:
            for f in IMPORT_FIELDS:
                if f not in index or f in ("full_name", "last_name", "first_name", "middle_name"):
                    continue
                value = get(f)
                if f in MONEY or f == "tax_withheld_dec":
                    amount = _amount(value)
                    if amount is not None:
                        data[f] = str(amount)
                elif f in DATES:
                    parsed = _date(value)
                    if parsed:
                        data[f] = parsed
                elif f in ("mwe", "substituted_filing"):
                    flag = _yes(value)
                    if flag is not None:
                        data[f] = flag
                elif f == "status":
                    data[f] = value.upper()[:2] or "R"
                elif f == "separation":
                    data[f] = value.upper()[:2]
                else:
                    data[f] = value
        except ValueError as exc:
            errors.append(f"Row {n}: {exc}")
            continue
        if data.get("mwe") and "t_basic" in data and "nt_basic" not in data:  # one "basic pay" column for all
            data["nt_basic"] = data.pop("t_basic")
        out.append(data)
    return out, errors
