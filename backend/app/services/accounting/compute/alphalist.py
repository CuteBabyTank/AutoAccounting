"""Year-end compensation: the 1604-C alphalist (Schedules 1 and 2), each employee's BIR 2316, and checks against
the 1601-C returns (pure).

Columns follow BIR's "Alphabetical List of Employees/Payees from Whom Taxes Were Withheld" format (Schedule 1:
employees, Schedule 2: minimum wage earners), item numbers in the keys (``7a``, ``12j``, ``17a``…). The 2316 items
follow the September 2021 ENCS form. Year-end adjustment (RR 2-98 Sec. 2.79): tax due on the year's taxable
compensation from the present and previous employers less taxes withheld Jan–Nov; the difference is withheld in
December (17a) or refunded (17b).
"""

from dataclasses import dataclass, field, fields
from datetime import date
from decimal import Decimal

from app.services.accounting.compute.itr import graduated_tax
from app.services.accounting.compute.money import ZERO, c2, total

THIRTEENTH_CEILING = Decimal("90000")      # RA 10963 (TRAIN): 13th month pay and other benefits
EXEMPT_CEILING = Decimal("250000")         # taxable compensation exempt under the graduated table
STATUSES = ("R", "C", "CP", "S", "P", "AL")
SEPARATIONS = ("", "T", "TR", "R", "D")

# 2316 items 29–37 (non-taxable, present employer) and 39–51 (taxable)
NON_TAXABLE = ("nt_basic", "nt_holiday", "nt_overtime", "nt_night", "nt_hazard", "nt_13th", "nt_deminimis",
               "nt_contributions", "nt_other")
TAXABLE = ("t_basic", "t_representation", "t_transportation", "t_cola", "t_housing", "t_others", "t_commission",
           "t_profit_sharing", "t_fees", "t_13th", "t_hazard", "t_overtime", "t_supp_others")
PREVIOUS = ("prev_13th", "prev_deminimis", "prev_contributions", "prev_nt_other", "prev_t_basic", "prev_t_13th",
            "prev_t_other")
TAXES = ("tax_withheld_prev", "tax_withheld_jan_nov", "pera_credit")
MONEY = NON_TAXABLE + TAXABLE + PREVIOUS + TAXES + ("smw_day", "smw_month", "smw_year")

FIELD_LABELS = {
    "tin": "TIN", "last_name": "Last name", "first_name": "First name", "middle_name": "Middle name",
    "nationality": "Nationality (foreigners only)", "status": "Employment status (R/C/CP/S/P/AL)",
    "employed_from": "Employed from", "employed_to": "Employed to", "separation": "Reason of separation (T/TR/R/D)",
    "mwe": "Minimum wage earner", "region": "Region where assigned (MWE)", "smw_day": "Statutory minimum wage per day",
    "smw_month": "Statutory minimum wage per month", "smw_year": "Statutory minimum wage per year",
    "factor": "Factor used (days/year)", "birth_date": "Date of birth", "address": "Registered address",
    "zip_code": "ZIP code", "contact": "Contact number",
    "nt_basic": "Basic salary / SMW (non-taxable)", "nt_holiday": "Holiday pay (MWE)", "nt_overtime": "Overtime pay (MWE)",
    "nt_night": "Night shift differential (MWE)", "nt_hazard": "Hazard pay (MWE)",
    "nt_13th": "13th month pay and other benefits (non-taxable)", "nt_deminimis": "De minimis benefits",
    "nt_contributions": "SSS/PhilHealth/Pag-IBIG and union dues (employee share)",
    "nt_other": "Salaries and other forms of compensation (non-taxable)",
    "t_basic": "Taxable basic salary", "t_representation": "Representation", "t_transportation": "Transportation",
    "t_cola": "Cost of living allowance", "t_housing": "Fixed housing allowance", "t_others": "Other taxable allowances",
    "t_commission": "Commission", "t_profit_sharing": "Profit sharing", "t_fees": "Fees incl. director's fees",
    "t_13th": "Taxable 13th month (excess)", "t_hazard": "Hazard pay (taxable)", "t_overtime": "Overtime pay (taxable)",
    "t_supp_others": "Other supplementary compensation",
    "prev_tin": "Previous employer TIN", "prev_name": "Previous employer name",
    "prev_from": "Previous employment from", "prev_to": "Previous employment to",
    "prev_13th": "Previous employer: 13th month (non-taxable)", "prev_deminimis": "Previous employer: de minimis",
    "prev_contributions": "Previous employer: contributions", "prev_nt_other": "Previous employer: other non-taxable",
    "prev_t_basic": "Previous employer: taxable basic salary", "prev_t_13th": "Previous employer: taxable 13th month",
    "prev_t_other": "Previous employer: other taxable", "tax_withheld_prev": "Tax withheld by previous employer",
    "tax_withheld_jan_nov": "Tax withheld Jan–Nov (present employer)", "pera_credit": "5% PERA tax credit",
    "tax_withheld_dec": "Tax withheld in December (if already known)", "substituted_filing": "Substituted filing (Y/N)",
}


@dataclass(frozen=True)
class Employee:
    id: str
    tin: str = ""
    last_name: str = ""
    first_name: str = ""
    middle_name: str = ""
    nationality: str = ""
    status: str = "R"
    employed_from: date | None = None
    employed_to: date | None = None
    separation: str = ""
    mwe: bool = False
    region: str = ""
    factor: str = ""
    birth_date: date | None = None
    address: str = ""
    zip_code: str = ""
    contact: str = ""
    prev_tin: str = ""
    prev_name: str = ""
    prev_from: date | None = None
    prev_to: date | None = None
    tax_withheld_dec: Decimal | None = None      # when the December adjustment was already made
    substituted_filing: bool | None = None       # None = decide from the rules
    amounts: dict[str, Decimal] = field(default_factory=dict)

    def a(self, key: str) -> Decimal:
        return c2(self.amounts.get(key, ZERO))


@dataclass(frozen=True)
class Computed:
    employee: Employee
    schedule: int                     # 1 employees, 2 minimum wage earners
    alpha: dict                       # alphalist columns by item number
    form: dict                        # 2316 items
    warnings: tuple[str, ...]


def _tin(raw: str) -> str:
    digits = "".join(ch for ch in raw if ch.isdigit())
    return digits[:9] + (digits[9:] or "0000").ljust(4, "0")[:4] if len(digits) >= 9 else digits


def tin_text(raw: str) -> str:
    t = _tin(raw)
    return f"{t[:3]}-{t[3:6]}-{t[6:9]}-{t[9:]}" if len(t) == 13 else raw


def _md(d: date | None) -> str:
    return f"{d:%m/%d}" if d else ""


def compute_employee(e: Employee, year: int) -> Computed:
    warnings: list[str] = []
    who = ", ".join(x for x in (e.last_name, e.first_name) if x) or "(no name)"
    nt = {k: e.a(k) for k in NON_TAXABLE}
    tx = {k: e.a(k) for k in TAXABLE}
    prev_taxable = total(e.a(k) for k in ("prev_t_basic", "prev_t_13th", "prev_t_other"))
    if not e.mwe and 0 < total(tx.values()) and total(tx.values()) + prev_taxable <= EXEMPT_CEILING:
        # Compensation of ₱250,000 or less for the year is exempt: reported as non-taxable (2316 items 29 and 37,
        # alphalist 7e), with the 13th month excess staying in 13th month benefits.
        nt["nt_basic"] = c2(nt["nt_basic"] + tx["t_basic"])
        nt["nt_13th"] = c2(nt["nt_13th"] + tx["t_13th"])
        nt["nt_other"] = c2(nt["nt_other"] + total(v for k, v in tx.items() if k not in ("t_basic", "t_13th")))
        tx = {k: ZERO for k in TAXABLE}
    nt_total, tx_total = total(nt.values()), total(tx.values())
    gross = c2(nt_total + tx_total)
    prev_nt = total(e.a(k) for k in ("prev_13th", "prev_deminimis", "prev_contributions", "prev_nt_other"))
    prev_tx = total(e.a(k) for k in ("prev_t_basic", "prev_t_13th", "prev_t_other"))
    taxable_all = c2(tx_total + prev_tx)
    due = graduated_tax(max(taxable_all, ZERO), year)
    w_prev, w_present, pera = e.a("tax_withheld_prev"), e.a("tax_withheld_jan_nov"), e.a("pera_credit")
    under = max(c2(due - (w_prev + w_present) - pera), ZERO)      # 17a
    over = max(c2((w_prev + w_present + pera) - due), ZERO)       # 17b
    adjusted = c2(w_prev + w_present + pera + under - over)       # 18
    if e.tax_withheld_dec is not None and c2(e.tax_withheld_dec) != under:
        warnings.append(f"{who}: December withholding entered is ₱{e.tax_withheld_dec:,.2f} but the year-end "
                        f"adjustment needs ₱{under:,.2f}" + (f" (₱{over:,.2f} to refund)" if over else "") + ".")
    if len("".join(ch for ch in e.tin if ch.isdigit())) < 9:
        warnings.append(f"{who}: no valid TIN.")
    if not e.last_name or not e.first_name:
        warnings.append(f"{who}: last and first names are required.")
    if nt["nt_13th"] + e.a("prev_13th") > THIRTEENTH_CEILING:
        warnings.append(f"{who}: non-taxable 13th month and other benefits are above ₱90,000; the excess belongs in "
                        "taxable 13th month benefits.")
    if e.mwe and nt["nt_basic"] == 0:
        warnings.append(f"{who}: marked minimum wage earner but no statutory minimum wage was entered.")
    if e.status not in STATUSES:
        warnings.append(f"{who}: employment status '{e.status}' isn't one of R, C, CP, S, P, AL.")
    separated = bool(e.separation) or (e.employed_to is not None and e.employed_to < date(year, 12, 31))
    previous = bool(e.prev_tin.strip()) or prev_tx > 0 or prev_nt > 0 or w_prev > 0
    substituted = e.substituted_filing if e.substituted_filing is not None else (not previous and not separated)
    common = {
        "seq": "", "last": e.last_name.upper(), "first": e.first_name.upper(), "middle": e.middle_name.upper(),
        "tin": tin_text(e.tin),
        "8": tin_text(e.prev_tin) if e.prev_tin else "", "9": "", "10a": _md(e.prev_from), "10b": _md(e.prev_to),
        "11": "",
        "13": taxable_all, "14": due, "15a": w_prev, "15b": w_present, "16": pera, "17a": under, "17b": over,
        "18": adjusted, "19": "Y" if substituted else "N",
    }
    if not e.mwe:
        alpha = {**common, "3": e.nationality, "4": e.status, "5a": _md(e.employed_from), "5b": _md(e.employed_to),
                 "6": e.separation,
                 "7b": nt["nt_13th"], "7c": nt["nt_deminimis"], "7d": nt["nt_contributions"],
                 "7e": c2(nt["nt_basic"] + nt["nt_other"] + nt["nt_holiday"] + nt["nt_overtime"] + nt["nt_night"]
                          + nt["nt_hazard"]),
                 "7f": nt_total, "7g": tx["t_basic"], "7h": tx["t_13th"],
                 "7i": c2(tx_total - tx["t_basic"] - tx["t_13th"]), "7j": tx_total, "7a": gross,
                 "12b": e.a("prev_13th"), "12c": e.a("prev_deminimis"), "12d": e.a("prev_contributions"),
                 "12e": e.a("prev_nt_other"), "12f": prev_nt, "12g": e.a("prev_t_basic"), "12h": e.a("prev_t_13th"),
                 "12i": e.a("prev_t_other"), "12j": prev_tx, "12a": c2(prev_nt + prev_tx)}
        schedule = 1
    else:
        alpha = {**common, "3": e.status, "4": e.region, "5a": _md(e.employed_from), "5b": _md(e.employed_to),
                 "6": e.separation,
                 "7b": e.a("smw_day"), "7c": e.a("smw_month"), "7d": e.a("smw_year"), "7e": e.factor,
                 "7f": nt["nt_basic"], "7g": nt["nt_holiday"], "7h": nt["nt_overtime"], "7i": nt["nt_night"],
                 "7j": nt["nt_hazard"], "7k": nt["nt_13th"], "7l": nt["nt_deminimis"], "7m": nt["nt_contributions"],
                 "7n": nt["nt_other"], "7o": nt_total, "7p": tx["t_13th"], "7q": c2(tx_total - tx["t_13th"]),
                 "7r": tx_total, "7a": gross,
                 "12b": ZERO, "12c": ZERO, "12d": ZERO, "12e": ZERO, "12f": ZERO, "12g": e.a("prev_13th"),
                 "12h": e.a("prev_deminimis"), "12i": e.a("prev_contributions"), "12j": e.a("prev_nt_other"),
                 "12k": prev_nt, "12l": e.a("prev_t_13th"), "12m": c2(e.a("prev_t_basic") + e.a("prev_t_other")),
                 "12n": prev_tx, "12a": c2(prev_nt + prev_tx)}
        schedule = 2
    present_withheld = c2(w_present + under - over)
    form = {
        "1": str(year), "2_from": _md(e.employed_from or date(year, 1, 1)), "2_to": _md(e.employed_to or date(year, 12, 31)),
        "3": _tin(e.tin), "4": ", ".join(x for x in (e.last_name, e.first_name) if x) + (f" {e.middle_name}" if e.middle_name else ""),
        "6": e.address, "6A": e.zip_code, "7": f"{e.birth_date:%m/%d/%Y}" if e.birth_date else "", "8": e.contact,
        "9": e.a("smw_day") if e.mwe else "", "10": e.a("smw_month") if e.mwe else "", "11": e.mwe,
        "16": _tin(e.prev_tin) if e.prev_tin else "", "17": e.prev_name,
        "19": gross, "20": nt_total, "21": tx_total, "22": prev_tx, "23": taxable_all, "24": due,
        "25A": present_withheld, "25B": w_prev, "26": c2(present_withheld + w_prev), "27": pera,
        "28": c2(present_withheld + w_prev + pera),
        "38": nt_total, "52": tx_total, "substituted": substituted,
    }
    for n, key in zip(range(29, 38), NON_TAXABLE):
        form[str(n)] = nt[key]
    for n, key in zip(("39", "40", "41", "42", "43", "44A", "45", "46", "47", "48", "49", "50", "51A"), TAXABLE):
        form[n] = tx[key]
    return Computed(e, schedule, alpha, form, tuple(warnings))


def _money_sum(rows, key) -> Decimal:
    return total(r.alpha.get(key, ZERO) for r in rows if isinstance(r.alpha.get(key), Decimal))


@dataclass(frozen=True)
class MonthRemittance:
    month: int                 # calendar month 1–12
    remitted_on: str           # date filed / paid, "" if not filed
    compensation: Decimal      # 1601-C item 14
    withheld: Decimal          # item 25
    adjustment: Decimal        # item 26
    penalties: Decimal         # item 35
    total: Decimal             # item 36 (still due) when filed on time
    source: str                # filed | latest | missing


def build_alphalist(employees: list[Employee], year: int,
                    remittances: list[MonthRemittance]) -> tuple[dict[str, list[dict]], list[Computed], list[str]]:
    """Tabs Schedule1 / Schedule2 / Remittances / Checks, the computed rows (2316s), and warnings."""
    computed = sorted((compute_employee(e, year) for e in employees),
                      key=lambda c: (c.employee.last_name.upper(), c.employee.first_name.upper()))
    warnings = [w for c in computed for w in c.warnings]
    tabs: dict[str, list[dict]] = {}
    for schedule, name in ((1, "Schedule1"), (2, "Schedule2")):
        rows = [c for c in computed if c.schedule == schedule]
        out = []
        for i, c in enumerate(rows, start=1):
            out.append({"key": c.employee.id, **c.alpha, "seq": str(i)})
        if rows:
            totals = {"key": "~total", "seq": "", "last": "TOTALS"}
            for k, v in rows[0].alpha.items():
                if isinstance(v, Decimal):
                    totals[k] = _money_sum(rows, k)
            out.append(totals)
        tabs[name] = out
    tins = {}
    for c in computed:
        t = _tin(c.employee.tin)[:9]
        if t:
            tins.setdefault(t, []).append(c)
    for t, group in tins.items():
        if len(group) > 1 and len(t) == 9:
            warnings.append(f"TIN {tin_text(t)} appears {len(group)} times in the alphalist.")

    by_month = {r.month: r for r in remittances}
    rem_rows = []
    for m in range(1, 13):
        r = by_month.get(m)
        rem_rows.append({"key": str(m), "month": date(year, m, 1).strftime("%B"),
                         "remitted_on": r.remitted_on if r else "", "withheld": r.withheld if r else ZERO,
                         "adjustment": r.adjustment if r else ZERO, "penalties": r.penalties if r else ZERO,
                         "total": r.total if r else ZERO, "source": r.source if r else "missing"})
    rem_rows.append({"key": "~total", "month": "TOTAL", "remitted_on": "",
                     "withheld": total(r["withheld"] for r in rem_rows), "adjustment": total(r["adjustment"] for r in rem_rows),
                     "penalties": total(r["penalties"] for r in rem_rows), "total": total(r["total"] for r in rem_rows),
                     "source": ""})
    tabs["Remittances"] = rem_rows
    missing = [r["month"] for r in rem_rows[:-1] if r["source"] == "missing"]
    if missing and employees:
        warnings.append(f"No 1601-C on AutoAccounting for {', '.join(missing)}; the remittance summary and checks "
                        "leave those months at zero.")

    present_withheld = total(c.form["25A"] for c in computed)
    gross = total(c.form["19"] for c in computed)
    filed_withheld = total(r.withheld + r.adjustment for r in remittances)
    filed_gross = total(r.compensation for r in remittances)
    checks = [
        {"key": "gross", "check": "Gross compensation: alphalist (present employer) vs 1601-C item 14",
         "alphalist": gross, "returns": filed_gross, "difference": c2(gross - filed_gross)},
        {"key": "withheld", "check": "Tax withheld as adjusted (present employer) vs 1601-C items 25 + 26",
         "alphalist": present_withheld, "returns": filed_withheld, "difference": c2(present_withheld - filed_withheld)},
    ]
    tabs["Checks"] = checks
    for row in checks:
        if row["difference"] and remittances:
            warnings.append(f"{row['check']} differ by ₱{row['difference']:,.2f}.")
    return tabs, computed, warnings


def employee_from_json(row_id: str, data: dict) -> Employee:
    def d(key):
        raw = data.get(key)
        return date.fromisoformat(raw) if raw else None

    amounts = {}
    for key in MONEY:
        raw = data.get(key)
        if raw not in (None, ""):
            amounts[key] = Decimal(str(raw))
    dec = data.get("tax_withheld_dec")
    sub = data.get("substituted_filing")
    names = {f.name for f in fields(Employee)}
    text = {k: str(data.get(k) or "") for k in ("tin", "last_name", "first_name", "middle_name", "nationality",
                                                 "separation", "region", "factor", "address", "zip_code", "contact",
                                                 "prev_tin", "prev_name") if k in names}
    return Employee(id=row_id, status=str(data.get("status") or "R"), employed_from=d("employed_from"),
                    employed_to=d("employed_to"), mwe=bool(data.get("mwe")), birth_date=d("birth_date"),
                    prev_from=d("prev_from"), prev_to=d("prev_to"),
                    tax_withheld_dec=Decimal(str(dec)) if dec not in (None, "") else None,
                    substituted_filing=None if sub in (None, "") else bool(sub), amounts=amounts, **text)
