"""Folder-tree assembly for the AutoAccounting browser (pure)."""

from dataclasses import dataclass
from datetime import date, datetime

from app.services.accounting.classify import CATEGORIES
from app.services.accounting.periods import quarter_label


@dataclass(frozen=True)
class TreeCompanyInput:
    id: str
    registered_name: str
    tin: str
    pinned: bool
    fiscal_year_end_month: int
    books_start: date | None = None
    has_employees: bool = False


def bank_nodes(rows: list[tuple], reconciled: set[tuple[str, str, date]], accounts: dict[tuple[str, str], tuple[str, str]],
               fye: dict[str, int]) -> dict[tuple[str, int], list[dict]]:
    """Company → fiscal year → bank account → month, from ``(company_id, account_code, month_start, lines, open)``.

    ``accounts`` maps (company, code) to (name, account number); code "" is a statement nobody has assigned yet.
    """
    from app.services.accounting.bank_statement import last4
    from app.services.accounting.periods import period_for

    grouped: dict[tuple[str, int], dict[str, list[dict]]] = {}
    for company_id, code, month_start, count, open_count in rows:
        cid = str(company_id)
        month = month_start.date() if isinstance(month_start, datetime) else month_start
        year = period_for(month, fye.get(cid, 12)).fiscal_year
        grouped.setdefault((cid, year), {}).setdefault(code or "", []).append({
            "month_start": month, "lines": int(count), "open": int(open_count or 0),
            "reconciled": (cid, code, month) in reconciled,
        })
    out: dict[tuple[str, int], list[dict]] = {}
    for key, by_code in grouped.items():
        nodes = []
        for code, months in sorted(by_code.items(), key=lambda kv: (kv[0] == "", kv[0])):
            name, number = accounts.get((key[0], code), ("Account not set" if not code else code, ""))
            nodes.append({"account_code": code, "name": name, "last4": last4(number),
                          "months": sorted(months, key=lambda m: m["month_start"], reverse=True)})
        out[key] = nodes
    return out


def build_tree(companies: list[TreeCompanyInput], rows: list[tuple], status: dict | None = None,
               bank: dict[tuple[str, int], list[dict]] | None = None) -> list[dict]:
    """Nest per-period document counts under each company.

    ``rows`` are ``(company_id, year | None, quarter | None, document_count, review_count)``.
    Company order is preserved; years and quarters are newest first.
    """
    nodes: dict[str, dict] = {
        c.id: {"company": c, "years": {}, "undated_count": 0} for c in companies
    }
    for company_id, year, quarter, count, review in rows:
        node = nodes.get(str(company_id))
        if node is None:
            continue
        if year is None or quarter is None:
            node["undated_count"] += int(count)
            continue
        node["years"].setdefault(year, []).append({
            "year": year,
            "quarter": quarter,
            "label": quarter_label(quarter, node["company"].fiscal_year_end_month),
            "document_count": int(count),
            "review_count": int(review or 0),
            **_status(status, node["company"].id, year, quarter),
        })
    for company_id, year, quarter in (status or {}):  # a period with outputs but no documents still shows
        node = nodes.get(company_id)
        if node is not None:
            node["years"].setdefault(year, [])
    for company_id, year in (bank or {}):  # a year with only a bank statement still shows
        node = nodes.get(company_id)
        if node is not None:
            node["years"].setdefault(year, [])
    for node in nodes.values():  # every quarter of a shown year, so an empty one can still be generated
        for year, quarters in node["years"].items():
            present = {q["quarter"] for q in quarters}
            quarters.extend({
                "year": year, "quarter": q, "label": quarter_label(q, node["company"].fiscal_year_end_month),
                "document_count": 0, "review_count": 0, **_status(status, node["company"].id, year, q),
            } for q in range(1, 5) if q not in present)
    out = []
    for node in nodes.values():
        c = node["company"]
        out.append({
            "id": c.id,
            "registered_name": c.registered_name,
            "tin": c.tin,
            "pinned": c.pinned,
            "fiscal_year_end_month": c.fiscal_year_end_month,
            "books_start": c.books_start,
            "has_employees": c.has_employees,
            "years": [
                {"year": y, "quarters": sorted(qs, key=lambda q: -q["quarter"]),
                 "annual": _status(status, c.id, y, 0), "bank": (bank or {}).get((c.id, y), [])}
                for y, qs in sorted(node["years"].items(), reverse=True)
            ],
            "undated_count": node["undated_count"],
        })
    return out


def folder_counts(items: list[tuple[str, bool, bool, bool]]) -> dict[str, int]:
    """Per-category counts plus open reviews, from ``(category, needs_review, reviewed, excluded)``."""
    counts = {c: 0 for c in CATEGORIES}
    counts["review"] = 0
    for category, needs_review, reviewed, excluded in items:
        if excluded:
            continue
        counts[category] = counts.get(category, 0) + 1
        if needs_review and not reviewed:
            counts["review"] += 1
    return counts


def _status(status: dict | None, company_id: str, year: int, quarter: int) -> dict:
    found = (status or {}).get((company_id, year, quarter), {})
    return {
        "latest_version": found.get("latest_version"),
        "stale": bool(found.get("stale", False)),
        "filed": bool(found.get("filed", False)),
    }


def stale_periods(changes: dict[tuple[int, int], datetime], generated: dict[tuple[int, int], datetime], *,
                  always: datetime | None = None,
                  annual_changes: dict[tuple[int, int], datetime] | None = None) -> set[tuple[int, int]]:
    """Periods whose latest output predates a change that feeds it.

    ``changes`` are document, input and asset changes keyed (year, quarter); quarter 0 is the
    year-level (annual) period. A quarterly output reads that quarter and earlier quarters
    (carry-overs flow forward), never annual inputs. An annual output reads every period of its
    year and earlier years (NOLCO, excess MCIT and credits carry forward), plus ``annual_changes``:
    quarterly versions generated or filed in that year, and the previous year's annual output.
    ``always`` (company facts edited) applies to every output.
    """
    stale: set[tuple[int, int]] = set()
    for period, generated_at in generated.items():
        year, quarter = period
        if always is not None and always > generated_at:
            stale.add(period)
            continue
        if quarter == 0:
            times = [at for (y, _), at in changes.items() if y <= year]
            times += [at for (y, q), at in (annual_changes or {}).items()
                      if (y == year and q != 0) or (y == year - 1 and q == 0)]
        else:
            times = [at for p, at in changes.items() if p[1] != 0 and p <= period]
        if any(at > generated_at for at in times):
            stale.add(period)
    return stale
