"""Outgoing BIR 2307s: one certificate per payee for the quarter, built from a version's QAP rows."""

import io
import re
import zipfile
from datetime import date
from decimal import Decimal, InvalidOperation

from app.schemas.form_filler import FilledForm, LineItem, Payee, Payor
from app.services.form_filler_service import MAX_LINE_ITEMS_PER_BLOCK, generate_merged_pdf


def _amount(text) -> float:
    try:
        return float(Decimal(str(text)))
    except (InvalidOperation, TypeError, ValueError):
        return 0.0


def payee_forms(rows: list[dict], company: dict, period_from: date, period_to: date) -> list[tuple[str, FilledForm]]:
    """(payee name, filled 2307) per payee, a payee with more ATCs than the form's rows getting extra copies."""
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(row.get("tin") or f"NAME:{row.get('name', '')}", []).append(row)
    payor = Payor(tin=f"{company.get('tin', '')}{company.get('branch_code') or '00000'}",
                  name=company.get("registered_name", ""), registered_address=company.get("address", ""),
                  zip_code=company.get("zip_code", ""))
    forms: list[tuple[str, FilledForm]] = []
    for party in sorted(groups.values(), key=lambda rs: (rs[0].get("name", "").lower(), rs[0].get("tin", ""))):
        first = party[0]
        payee = Payee(tin=f"{first['tin']}00000" if first.get("tin") else "", name=first.get("name", ""),
                      registered_address=first.get("address", ""), zip_code="")
        items = [LineItem(description=row.get("nature", ""), atc=row.get("atc", ""), m1=_amount(row.get("m1")),
                          m2=_amount(row.get("m2")), m3=_amount(row.get("m3")), total=_amount(row.get("base")),
                          tax_withheld=_amount(row.get("tax")))
                 for row in party]
        for start in range(0, len(items), MAX_LINE_ITEMS_PER_BLOCK):
            forms.append((first.get("name") or first.get("tin") or "payee", FilledForm(
                excel_row=0, payee=payee, payor=payor, period_from=period_from.strftime("%m/%d/%Y"),
                period_to=period_to.strftime("%m/%d/%Y"), ewt=items[start:start + MAX_LINE_ITEMS_PER_BLOCK],
            )))
    return forms


def _file_name(name: str, used: set[str]) -> str:
    stem = re.sub(r"[^A-Za-z0-9 ._-]+", "", name).strip() or "payee"
    candidate, n = f"{stem} 2307.pdf", 2
    while candidate in used:
        candidate, n = f"{stem} 2307 ({n}).pdf", n + 1
    used.add(candidate)
    return candidate


def zip_forms(forms: list[tuple[str, FilledForm]]) -> bytes:
    """One PDF per certificate, zipped."""
    buffer = io.BytesIO()
    used: set[str] = set()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, form in forms:
            archive.writestr(_file_name(name, used), generate_merged_pdf([form]))
    return buffer.getvalue()


def build_zip(rows: list[dict], company: dict, period_from: date, period_to: date) -> bytes:
    return zip_forms(payee_forms(rows, company, period_from, period_to))
