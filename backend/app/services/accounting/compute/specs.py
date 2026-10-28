"""Titles, item labels and ledger columns for the workbook, the output viewer and the PDF (pure data)."""

FORM_TITLES = {
    "2550Q": "BIR Form 2550-Q: Quarterly Value-Added Tax Return",
    "2551Q": "BIR Form 2551-Q: Quarterly Percentage Tax Return",
    "1701Q": "BIR Form 1701-Q: Quarterly Income Tax Return (Individuals)",
    "1702Q": "BIR Form 1702-Q: Quarterly Income Tax Return (Non-Individuals)",
    "COGS": "Cost of goods sold",
    "Expenses": "Deductions",
}
WHOLE_PESO_FORMS = frozenset({"1701Q", "1702Q"})
WITHHOLDING_MONTHLY = ("0619E-M1", "0619E-M2", "1601C-M1", "1601C-M2", "1601C-M3")
for _m in (1, 2):
    FORM_TITLES[f"0619E-M{_m}"] = (f"BIR Form 0619-E: Monthly Remittance of Expanded Withholding Tax "
                                   f"(month {_m} of the quarter)")
FORM_TITLES["1601EQ"] = "BIR Form 1601-EQ: Quarterly Remittance Return of Expanded Withholding Tax"
for _m in (1, 2, 3):
    FORM_TITLES[f"1601C-M{_m}"] = (f"BIR Form 1601-C: Monthly Remittance Return of Tax Withheld on Compensation "
                                   f"(month {_m} of the quarter)")

FORM_ORDER = ("2550Q", "2551Q", "1701Q", "1702Q", "0619E-M1", "0619E-M2", "1601EQ", "1601C-M1", "1601C-M2",
              "1601C-M3", "COGS", "Expenses")
PAYABLE_ITEM = {"2550Q": "26", "2551Q": "24", "1701Q": "68", "1702Q": "25", "0619E-M1": "18", "0619E-M2": "18",
                "1601EQ": "31", "1601C-M1": "36", "1601C-M2": "36", "1601C-M3": "36"}
PDF_FORMS = frozenset({"2550Q", "2551Q", "1701Q", "1702Q", "0619E-M1", "0619E-M2", "1601EQ", "1601C-M1",
                       "1601C-M2", "1601C-M3"})

FORM_ITEMS: dict[str, tuple[tuple[str, str], ...]] = {
    "2550Q": (
        ("31A", "31A VATable sales"), ("31B", "31B Output tax on VATable sales"),
        ("32A", "32A Zero-rated sales"), ("33A", "33A Exempt sales"),
        ("34A", "34A Total sales"), ("34B", "34B Total output tax due"),
        ("35B", "35B Less: output VAT on uncollected receivables"),
        ("36B", "36B Add: output VAT on recovered uncollected receivables"),
        ("37B", "37B Total adjusted output tax due"),
        ("38B", "38B Input tax carried over from previous quarter"),
        ("39B", "39B Input tax deferred on capital goods over ₱1M"), ("40B", "40B Transitional input tax"),
        ("41B", "41B Presumptive input tax"), ("42B", "42B Others"), ("43B", "43B Total (38B to 42B)"),
        ("44A", "44A Domestic purchases"), ("44B", "44B Input tax on domestic purchases"),
        ("45A", "45A Services rendered by non-residents"), ("45B", "45B Input tax on services by non-residents"),
        ("46A", "46A Importations"), ("46B", "46B Input tax on importations"),
        ("47A", "47A Others"), ("47B", "47B Input tax on others"),
        ("48A", "48A Domestic purchases with no input tax"), ("49A", "49A VAT-exempt importations"),
        ("50A", "50A Total current purchases"), ("50B", "50B Total current input tax"),
        ("51B", "51B Total available input tax"),
        ("52B", "52B Input tax on capital goods over ₱1M deferred"),
        ("53B", "53B Input tax attributable to VAT-exempt sales"), ("54B", "54B VAT refund/TCC claimed"),
        ("55B", "55B Input VAT on unpaid payables"), ("56B", "56B Others"),
        ("57B", "57B Total deductions from input tax"), ("58B", "58B Add: input VAT on settled unpaid payables"),
        ("59B", "59B Adjusted deductions from input tax"), ("60B", "60B Total allowable input tax"),
        ("61B", "61B Net VAT payable/(excess input tax)"),
        ("15", "15 Net VAT payable/(excess input tax)"), ("16", "16 Creditable VAT withheld"),
        ("17", "17 Advance VAT payments"), ("18", "18 VAT paid in return previously filed"),
        ("19", "19 Other credits/payment"), ("20", "20 Total tax credits/payment"),
        ("21", "21 Tax still payable/(excess credits)"), ("22", "22 Surcharge"), ("23", "23 Interest"),
        ("24", "24 Compromise"), ("25", "25 Total penalties"), ("26", "26 TOTAL AMOUNT PAYABLE/(excess credits)"),
    ),
    "2551Q": (
        ("S1_1_ATC", "Schedule 1 · ATC"), ("S1_1_TAXABLE", "Schedule 1 · taxable amount"),
        ("S1_1_RATE", "Schedule 1 · tax rate (%)"), ("S1_1_DUE", "Schedule 1 · tax due"),
        ("S1_7", "Schedule 1 · 7 Total tax due"), ("14", "14 Total tax due"),
        ("15", "15 Creditable percentage tax withheld (2307)"), ("16", "16 Tax paid in return previously filed"),
        ("17", "17 Other tax credit/payment"), ("18", "18 Total tax credits/payments"),
        ("19", "19 Tax still payable/(overpayment)"), ("20", "20 Surcharge"), ("21", "21 Interest"),
        ("22", "22 Compromise"), ("23", "23 Total penalties"), ("24", "24 TOTAL AMOUNT PAYABLE/(overpayment)"),
    ),
    "1702Q": (
        ("S2_1", "Sched 2 · 1 Sales/receipts/revenues/fees"), ("S2_2", "Sched 2 · 2 Less: cost of sales/services"),
        ("S2_3", "Sched 2 · 3 Gross income from operation"),
        ("S2_4", "Sched 2 · 4 Add: non-operating and other taxable income"),
        ("S2_5", "Sched 2 · 5 Total gross income"), ("S2_6", "Sched 2 · 6 Less: deductions"),
        ("S2_7", "Sched 2 · 7 Taxable income this quarter"),
        ("S2_8", "Sched 2 · 8 Add: taxable income previous quarter/s"),
        ("S2_9", "Sched 2 · 9 Total taxable income to date"), ("S2_10", "Sched 2 · 10 Applicable income tax rate (%)"),
        ("S2_11", "Sched 2 · 11 Income tax due other than MCIT"),
        ("S2_12", "Sched 2 · 12 Minimum corporate income tax (MCIT)"), ("S2_13", "Sched 2 · 13 Total income tax due"),
        ("S3_1", "Sched 3 · 1 Gross income, 1st quarter"), ("S3_2", "Sched 3 · 2 Gross income, 2nd quarter"),
        ("S3_3", "Sched 3 · 3 Gross income, 3rd quarter"), ("S3_4", "Sched 3 · 4 Total gross income"),
        ("S3_5", "Sched 3 · 5 MCIT rate (%)"), ("S3_6", "Sched 3 · 6 Minimum corporate income tax"),
        ("S4_1", "Sched 4 · 1 Prior year's excess credits"),
        ("S4_2", "Sched 4 · 2 Tax payments for previous quarters"),
        ("S4_3", "Sched 4 · 3 MCIT payments for previous quarters"),
        ("S4_4", "Sched 4 · 4 Creditable tax withheld in previous quarters"),
        ("S4_5", "Sched 4 · 5 Creditable tax withheld per 2307 this quarter"),
        ("S4_6", "Sched 4 · 6 Tax paid in return previously filed"), ("S4_7", "Sched 4 · 7 Total tax credits/payments"),
        ("14", "14 Income tax due at the regular rate"), ("15", "15 Less: unexpired excess MCIT"),
        ("16", "16 Balance/income tax still due"), ("17", "17 Add: income tax due at the special rate"),
        ("18", "18 Aggregate income tax due"), ("19", "19 Less: total tax credits/payments"),
        ("20", "20 Net tax payable/(overpayment)"), ("21", "21 Surcharge"), ("22", "22 Interest"),
        ("23", "23 Compromise"), ("24", "24 Total penalties"), ("25", "25 TOTAL AMOUNT PAYABLE/(overpayment)"),
    ),
    "1701Q": (
        ("36", "36 Sales/revenues/receipts/fees"), ("37", "37 Less: cost of sales/services"),
        ("38", "38 Gross income from operation"), ("39", "39 Total allowable itemized deductions"),
        ("40", "40 Optional standard deduction (40% of item 36)"), ("41", "41 Net income this quarter"),
        ("42", "42 Taxable income previous quarter/s"), ("43", "43 Non-operating income"),
        ("44", "44 Share in income from a general professional partnership"),
        ("45", "45 Total taxable income to date"), ("46", "46 TAX DUE (graduated rates)"),
        ("47", "47 Sales/revenues/receipts/fees"), ("48", "48 Add: non-operating income"),
        ("49", "49 Total income for the quarter"), ("50", "50 Add: total taxable income previous quarter"),
        ("51", "51 Cumulative taxable income as of this quarter"),
        ("52", "52 Less: allowable reduction (₱250,000)"), ("53", "53 Taxable income to date"),
        ("54", "54 TAX DUE (8%)"), ("55", "55 Prior year's excess credits"),
        ("56", "56 Tax payments for previous quarters"), ("57", "57 Creditable tax withheld in previous quarters"),
        ("58", "58 Creditable tax withheld per 2307 this quarter"),
        ("59", "59 Tax paid in return previously filed"), ("60", "60 Foreign tax credits"),
        ("61", "61 Other tax credits/payments"), ("62", "62 Total tax credits/payments"),
        ("63", "63 Tax payable/(overpayment)"), ("64", "64 Surcharge"), ("65", "65 Interest"),
        ("66", "66 Compromise"), ("67", "67 Total penalties"), ("68", "68 TOTAL AMOUNT PAYABLE/(overpayment)"),
    ),
    "COGS": (
        ("beginning_inventory", "Beginning inventory"), ("purchases", "Add: purchases (incl. importation costs)"),
        ("goods_available", "Cost of goods available for sale"), ("ending_inventory", "Less: ending inventory"),
        ("cost_of_sales", "Cost of goods sold"),
    ),
}
_0619E_ITEMS = (
    ("14", "14 Amount of remittance"), ("15", "15 Less: amount remitted from previously filed form"),
    ("16", "16 Net amount of remittance"), ("17A", "17A Surcharge"), ("17B", "17B Interest"),
    ("17C", "17C Compromise"), ("17D", "17D Total penalties"), ("18", "18 TOTAL AMOUNT OF REMITTANCE"),
)
_1601EQ_SCHEDULE = tuple(
    (f"S{i}_{part}", f"Row {i} · {label}")
    for i in range(1, 31)
    for part, label in (("ATC", "ATC"), ("BASE", "tax base"), ("RATE", "tax rate (%)"), ("TAX", "tax withheld"))
)
_1601EQ_ITEMS = _1601EQ_SCHEDULE + (
    ("19", "19 Total taxes withheld for the quarter"), ("20", "20 Less: remittance made in the 1st month"),
    ("21", "21 Less: remittance made in the 2nd month"), ("22", "22 Tax remitted in return previously filed"),
    ("23", "23 Over-remittance from previous quarter"), ("24", "24 Other payments made"),
    ("25", "25 Total remittances made"), ("26", "26 Tax still due/(over-remittance)"), ("27", "27 Surcharge"),
    ("28", "28 Interest"), ("29", "29 Compromise"), ("30", "30 Total penalties"),
    ("31", "31 TOTAL AMOUNT STILL DUE/(over-remittance)"),
)
_1601C_ITEMS = (
    ("14", "14 Total amount of compensation"), ("15", "15 Statutory minimum wage (MWEs)"),
    ("16", "16 Holiday, overtime, night shift and hazard pay (MWEs)"), ("17", "17 13th month pay and other benefits"),
    ("18", "18 De minimis benefits"), ("19", "19 SSS, GSIS, PHIC, HDMF contributions and union dues (employee share)"),
    ("20", "20 Other non-taxable compensation"), ("21", "21 Total non-taxable compensation"),
    ("22", "22 Total taxable compensation"), ("23", "23 Less: taxable compensation not subject to withholding"),
    ("24", "24 Net taxable compensation"), ("25", "25 Total taxes withheld"),
    ("26", "26 Add/(less): adjustment from previous months"), ("27", "27 Taxes withheld for remittance"),
    ("28", "28 Less: tax remitted in return previously filed"), ("29", "29 Other remittances made"),
    ("30", "30 Total tax remittances made"), ("31", "31 Tax still due/(over-remittance)"), ("32", "32 Surcharge"),
    ("33", "33 Interest"), ("34", "34 Compromise"), ("35", "35 Total penalties"),
    ("36", "36 TOTAL AMOUNT STILL DUE/(over-remittance)"),
)
for _m in (1, 2):
    FORM_ITEMS[f"0619E-M{_m}"] = _0619E_ITEMS
FORM_ITEMS["1601EQ"] = _1601EQ_ITEMS
for _m in (1, 2, 3):
    FORM_ITEMS[f"1601C-M{_m}"] = _1601C_ITEMS

FORM_NOTES: dict[str, dict[str, str]] = {
    "2550Q": {
        "31B": "12% × 31A", "34A": "31A + 32A + 33A", "37B": "34B − 35B + 36B", "43B": "Sum of 38B to 42B",
        "50A": "Sum of 44A to 49A", "50B": "Sum of 44B to 47B", "51B": "43B + 50B", "53B": "50B × 33A ÷ 34A",
        "57B": "Sum of 52B to 56B", "59B": "57B − 58B", "60B": "51B − 59B", "61B": "37B − 60B",
        "15": "Item 61B", "20": "Sum of 16 to 19", "21": "15 − 20", "26": "21 + 25",
    },
    "2551Q": {"S1_1_DUE": "3% × taxable amount", "18": "Sum of 15 to 17", "19": "14 − 18", "24": "19 + 23"},
    "1702Q": {
        "S2_3": "1 − 2", "S2_5": "3 + 4", "S2_7": "5 − 6", "S2_9": "7 + 8", "S2_11": "9 × 10",
        "S3_6": "2% × total gross income", "S2_13": "Higher of 11 and 12", "S4_7": "Sum of 1 to 6",
        "20": "18 − 19", "25": "20 + 24",
    },
    "1701Q": {
        "38": "36 − 37", "41": "38 − 39 (or 38 − 40 with OSD)", "45": "Sum of 41 to 44", "46": "Graduated table on 45",
        "49": "47 + 48", "51": "49 + 50", "53": "51 − 52", "54": "8% × 53", "62": "Sum of 55 to 61",
        "63": "46 or 54, less 62", "68": "63 + 67",
    },
    "COGS": {"goods_available": "Beginning + purchases", "cost_of_sales": "Available − ending inventory"},
}
for _m in (1, 2):
    FORM_NOTES[f"0619E-M{_m}"] = {"14": "EWT on this month's payments (base × ATC rate)", "16": "14 − 15",
                                  "17D": "Sum of 17A to 17C", "18": "16 + 17D"}
FORM_NOTES["1601EQ"] = {"19": "Sum of the schedule's tax withheld", "20": "0619-E month 1 (or the amount remitted)",
                        "21": "0619-E month 2 (or the amount remitted)", "25": "Sum of 20 to 24", "26": "19 − 25",
                        "31": "26 + 30"}
for _m in (1, 2, 3):
    FORM_NOTES[f"1601C-M{_m}"] = {"14": "Gross pay on this month's payroll documents", "21": "Sum of 15 to 20",
                                  "22": "14 − 21", "24": "22 − 23", "25": "Tax withheld on the payroll documents",
                                  "27": "25 + 26", "30": "28 + 29", "31": "27 − 30", "36": "31 + 35"}

EXPENSE_LABELS = {
    "purchases": "Purchases", "raw_materials": "Raw materials", "importation": "Importation",
    "capital_goods": "Capital goods", "salaries": "Salaries and wages", "rent": "Rent", "utilities": "Utilities",
    "professional_fees": "Professional fees", "office_supplies": "Office supplies",
    "transportation": "Transportation", "repairs": "Repairs and maintenance", "taxes_licenses": "Taxes and licenses",
    "other": "Other expenses", "payroll": "Salaries and wages (payroll)",
    "contributions": "SSS, PhilHealth and Pag-IBIG (employer share)",
    "representation": "Representation, total this quarter",
    "representation_allowed": "Representation deductible this quarter",
    "representation_disallowed_ytd": "Representation above the cap, year to date (not deductible)",
    "capital_goods_not_expensed": "Capital goods bought (in the asset register, depreciated, not expensed)",
    "depreciation": "Depreciation (asset register)",
    "total_deductions": "Total deductions this quarter",
}

LEDGER_ORDER = ("SLS", "SLP", "SAWT", "QAP", "Transactions")
LEDGER_TITLES = {
    "SLS": "Summary List of Sales", "SLP": "Summary List of Purchases",
    "SAWT": "SAWT: certificates (2307) received", "Transactions": "Transactions",
    "QAP": "QAP: alphalist of payees (expanded withholding)",
}
LEDGER_COLUMNS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "SLS": (("tin", "TIN", "text"), ("name", "Registered name", "text"), ("address", "Address", "text"),
            ("exempt", "Exempt sales", "money"), ("zero_rated", "Zero-rated sales", "money"),
            ("taxable", "Taxable sales", "money"), ("gross_sales", "Gross sales", "money"),
            ("output_tax", "Output tax", "money")),
    "SLP": (("tin", "TIN", "text"), ("name", "Registered name", "text"), ("address", "Address", "text"),
            ("exempt", "Exempt / no input tax", "money"), ("zero_rated", "Zero-rated", "money"),
            ("services", "Services", "money"), ("capital_goods", "Capital goods", "money"),
            ("other_goods", "Goods other than capital goods", "money"),
            ("gross_purchases", "Gross purchases", "money"), ("input_tax", "Input tax", "money")),
    "SAWT": (("doc_date", "Date", "text"), ("tin", "Payor TIN", "text"), ("name", "Payor name", "text"),
             ("income_payment", "Income payment", "money"), ("tax_withheld", "Tax withheld", "money")),
    "QAP": (("tin", "TIN", "text"), ("name", "Payee", "text"), ("atc", "ATC", "text"),
            ("nature", "Nature of income payment", "text"), ("m1", "Month 1 tax base", "money"),
            ("m2", "Month 2 tax base", "money"), ("m3", "Month 3 tax base", "money"),
            ("base", "Total tax base", "money"), ("rate", "Rate (%)", "text"), ("tax", "Tax withheld", "money")),
    "Transactions": (("doc_date", "Date", "text"), ("doc_number", "Document no.", "text"),
                     ("counterparty", "Counterparty", "text"), ("tin", "TIN", "text"),
                     ("category", "Folder", "text"), ("account", "Account", "text"), ("gross", "Total", "money"),
                     ("vatable", "VATable", "money"), ("vat", "VAT", "money"), ("exempt", "Exempt", "money"),
                     ("zero_rated", "Zero-rated", "money"), ("withholding", "Tax withheld", "money"),
                     ("ewt_atc", "EWT ATC", "text"), ("ewt_due", "EWT required", "money"),
                     ("input_vat_claimed", "Input VAT claimed", "text"), ("needs_review", "Needs review", "text")),
}


def form_items(form: str, values: dict) -> list[tuple[str, str]]:
    """(key, label) pairs in the form's own order, for keys present in ``values``."""
    if form in FORM_ITEMS:
        return [(key, label) for key, label in FORM_ITEMS[form] if key in values]
    return [(key, EXPENSE_LABELS.get(key, key)) for key in values]


# --- Annual returns (Phase 4a) ---------------------------------------------------------------

FORM_TITLES.update({
    "1702RT": "BIR Form 1702-RT: Annual Income Tax Return (Corporations and Partnerships, Regular Rate)",
    "1701": "BIR Form 1701: Annual Income Tax Return (Individuals)",
    "1701A": "BIR Form 1701-A: Annual Income Tax Return (Individuals Earning Purely from Business/Profession)",
    "BalanceSheet": "Balance sheet (from the annual inputs; not on the January 2018 return)",
})
FORM_ORDER = ("2550Q", "2551Q", "1701Q", "1702Q", "1702RT", "1701", "1701A", "0619E-M1", "0619E-M2", "1601EQ",
              "1601C-M1", "1601C-M2", "1601C-M3", "COGS", "Expenses", "BalanceSheet")
WHOLE_PESO_FORMS = frozenset({"1701Q", "1702Q", "1702RT", "1701", "1701A"})
PAYABLE_ITEM.update({"1702RT": "21", "1701": "31", "1701A": "29"})
PDF_FORMS = PDF_FORMS | {"1702RT", "1701", "1701A"}
ANNUAL_FORMS = ("1702RT", "1701", "1701A")

_ORDINARY = (("5", "Depreciation"), ("6", "Entertainment, amusement and recreation"), ("11", "Rental"),
             ("13", "Salaries, wages and allowances"), ("14", "SSS, GSIS, PhilHealth, HDMF and other contributions"),
             ("15", "Taxes and licenses"),
             ("16", "Transportation and travel"), ("17B", "Others: professional fees"),
             ("17D", "Others: utilities, supplies, repairs and other expenses"),
             ("18", "Total ordinary allowable itemized deductions"))


def _ordinary(prefix: str, label: str) -> tuple[tuple[str, str], ...]:
    return tuple((f"{prefix}_{key}", f"{label} · {key} {text}") for key, text in _ORDINARY)


def _nolco_rows(prefix: str, label: str) -> tuple[tuple[str, str], ...]:
    rows: list[tuple[str, str]] = []
    for n in (4, 5, 6, 7):
        rows.append((f"{prefix}_{n}_YEAR", f"{label} · {n} Year incurred"))
        for column, text in (("A", "Net operating loss"), ("B", "NOLCO applied previous years"),
                             ("C", "NOLCO expired"), ("D", "NOLCO applied this year"), ("E", "Unapplied")):
            rows.append((f"{prefix}_{n}_{column}", f"{label} · {n}{column} {text}"))
    rows.append((f"{prefix}_8", f"{label} · 8 Total NOLCO applied"))
    return tuple(rows)


_MCIT_ROWS = tuple(
    item for n in (1, 2, 3) for item in (
        (f"S4_{n}_YEAR", f"Sched IV · {n} Year"), (f"S4_{n}_A", f"Sched IV · {n}A Normal income tax"),
        (f"S4_{n}_B", f"Sched IV · {n}B MCIT"), (f"S4_{n}_C", f"Sched IV · {n}C Excess MCIT"),
        (f"S4_{n}_D", f"Sched IV · {n}D Used in previous years"), (f"S4_{n}_E", f"Sched IV · {n}E Expired"),
        (f"S4_{n}_F", f"Sched IV · {n}F Applied this year"), (f"S4_{n}_G", f"Sched IV · {n}G Balance"))
) + (("S4_4", "Sched IV · 4 Total excess MCIT applied"),)

FORM_ITEMS["1702RT"] = (
    ("14", "14 Tax due"), ("15", "15 Less: total tax credits/payments"),
    ("16", "16 Net tax payable/(overpayment)"), ("17", "17 Surcharge"), ("18", "18 Interest"),
    ("19", "19 Compromise"), ("20", "20 Total penalties"), ("21", "21 TOTAL AMOUNT PAYABLE/(overpayment)"),
    ("27", "27 Sales/receipts/revenues/fees"), ("28", "28 Less: sales returns, allowances and discounts"),
    ("29", "29 Net sales/receipts/revenues/fees"), ("30", "30 Less: cost of sales/services"),
    ("31", "31 Gross income from operation"), ("32", "32 Add: other taxable income not subjected to final tax"),
    ("33", "33 Total taxable income"), ("34", "34 Ordinary allowable itemized deductions"),
    ("35", "35 Special allowable itemized deductions"), ("36", "36 NOLCO"), ("37", "37 Total deductions"),
    ("38", "38 Optional standard deduction (40% of item 33)"), ("39", "39 Net taxable income/(loss)"),
    ("40", "40 Applicable income tax rate (%)"), ("41", "41 Income tax due other than MCIT"),
    ("42", "42 MCIT due (MCIT rate × item 33)"), ("43", "43 Tax due (higher of 41 and 42)"),
    ("44", "44 Prior year's excess credits other than MCIT"),
    ("45", "45 Income tax payments under MCIT in previous quarters"),
    ("46", "46 Income tax payments under regular rate in previous quarters"),
    ("47", "47 Excess MCIT applied this year"), ("48", "48 Creditable tax withheld in previous quarters (2307)"),
    ("49", "49 Creditable tax withheld in the 4th quarter (2307)"), ("50", "50 Foreign tax credits"),
    ("51", "51 Tax paid in return previously filed"), ("52", "52 Special tax credits"),
    ("53", "53 Other tax credits/payments"), ("54", "54 Other tax credits/payments"),
    ("55", "55 Total tax credits/payments"), ("56", "56 Net tax payable/(overpayment)"),
) + _ordinary("S1", "Sched I") + (
    ("S3_1", "Sched III · 1 Gross income"), ("S3_2", "Sched III · 2 Ordinary allowable itemized deductions"),
    ("S3_3", "Sched III · 3 Net operating loss"),
) + _nolco_rows("S3", "Sched IIIA") + _MCIT_ROWS + (
    ("S5_1", "Sched V · 1 Net income/(loss) per books"), ("S5_2", "Sched V · 2 Non-deductible expenses"),
    ("S5_3", "Sched V · 3 Other reconciling items (add)"), ("S5_4", "Sched V · 4 Total"),
    ("S5_5", "Sched V · 5 Non-taxable income and income subjected to final tax"),
    ("S5_7", "Sched V · 7 Other reconciling items (less)"), ("S5_9", "Sched V · 9 Total"),
    ("S5_10", "Sched V · 10 Net taxable income/(loss)"),
)
FORM_ITEMS["1701"] = (
    ("22", "22 Tax due"), ("23", "23 Less: total tax credits/payments"), ("24", "24 Tax payable/(overpayment)"),
    ("25", "25 Less: portion allowed for 2nd installment"), ("26", "26 Amount of tax payable/(overpayment)"),
    ("27", "27 Interest"), ("28", "28 Surcharge"), ("29", "29 Compromise"), ("30", "30 Total penalties"),
    ("31", "31 TOTAL AMOUNT PAYABLE/(overpayment)"), ("32", "32 Aggregate amount payable/(overpayment)"),
    ("S2_4", "Sched 2 · 4 Gross compensation income (2316)"), ("S2_5", "Sched 2 · 5 Less: non-taxable/exempt compensation"),
    ("S2_6", "Sched 2 · 6 Taxable compensation income"), ("S2_7", "Sched 2 · 7 Tax due on compensation income"),
    ("S3_8", "Sched 3.A · 8 Sales/revenues/receipts/fees"), ("S3_9", "Sched 3.A · 9 Less: sales returns"),
    ("S3_10", "Sched 3.A · 10 Net sales/revenues/receipts/fees"), ("S3_11", "Sched 3.A · 11 Less: cost of sales"),
    ("S3_12", "Sched 3.A · 12 Gross income/(loss) from operation"),
    ("S3_13", "Sched 3.A · 13 Ordinary allowable itemized deductions"),
    ("S3_14", "Sched 3.A · 14 Special allowable itemized deductions"), ("S3_15", "Sched 3.A · 15 NOLCO"),
    ("S3_16", "Sched 3.A · 16 Total allowable itemized deductions"), ("S3_17", "Sched 3.A · 17 OSD"),
    ("S3_18", "Sched 3.A · 18 Net income/(loss)"), ("S3_19", "Sched 3.A · 19 Other non-operating income"),
    ("S3_20", "Sched 3.A · 20 Other non-operating income"), ("S3_21", "Sched 3.A · 21 Share in GPP income"),
    ("S3_22", "Sched 3.A · 22 Total other non-operating income"), ("S3_23", "Sched 3.A · 23 Taxable income from business"),
    ("S3_24", "Sched 3.A · 24 Total taxable income"), ("S3_25", "Sched 3.A · 25 Tax due (graduated rates)"),
    ("S3_26", "Sched 3.B · 26 Sales/revenues/receipts/fees"), ("S3_27", "Sched 3.B · 27 Other non-operating income"),
    ("S3_28", "Sched 3.B · 28 Total income"),
    ("S3_29", "Sched 3.B · 29 Less: ₱250,000 (not if with compensation income)"),
    ("S3_30", "Sched 3.B · 30 Taxable income"), ("S3_31", "Sched 3.B · 31 Tax due on business (8%)"),
    ("S3_32", "Sched 3.B · 32 Total tax due on compensation and business"),
) + _ordinary("S4", "Sched 4") + (
    ("S6_1", "Sched 6.A · 1 Gross income"), ("S6_2", "Sched 6.A · 2 Ordinary allowable itemized deductions"),
    ("S6_3", "Sched 6.A · 3 Net operating loss"),
) + _nolco_rows("S6", "Sched 6.A.1") + (
    ("P6_1", "Part VI · 1 Regular rate income tax due"), ("P6_2", "Part VI · 2 Special rate income tax due"),
    ("P6_3", "Part VI · 3 Share of other government agency"), ("P6_4", "Part VI · 4 Net special rate tax due"),
    ("P6_5", "Part VI · 5 Total income tax due"), ("P7_1", "Part VII · 1 Prior year's excess credits"),
    ("P7_2", "Part VII · 2 Tax payments for the first three quarters"),
    ("P7_3", "Part VII · 3 Creditable tax withheld in the first three quarters"),
    ("P7_4", "Part VII · 4 Creditable tax withheld in the 4th quarter (2307)"),
    ("P7_5", "Part VII · 5 Creditable tax withheld per 2316"), ("P7_6", "Part VII · 6 Tax paid in return previously filed"),
    ("P7_7", "Part VII · 7 Foreign tax credits"), ("P7_8", "Part VII · 8 Special tax credits"),
    ("P7_9", "Part VII · 9 Other tax credits/payments"), ("P7_10", "Part VII · 10 Total tax credits/payments"),
    ("P9_1", "Part IX · 1 Net income/(loss) per books"), ("P9_2", "Part IX · 2 Non-deductible expenses"),
    ("P9_3", "Part IX · 3 Other reconciling items (add)"), ("P9_5", "Part IX · 5 Total"),
    ("P9_6", "Part IX · 6 Non-taxable income and income subjected to final tax"),
    ("P9_8", "Part IX · 8 Other reconciling items (less)"), ("P9_10", "Part IX · 10 Total"),
    ("P9_11", "Part IX · 11 Net taxable income/(loss)"),
)
FORM_ITEMS["1701A"] = (
    ("20", "20 Tax due"), ("21", "21 Less: total tax credits/payments"), ("22", "22 Net tax payable/(overpayment)"),
    ("23", "23 Less: portion allowed for 2nd installment"), ("24", "24 Amount of tax payable/(overpayment)"),
    ("25", "25 Surcharge"), ("26", "26 Interest"), ("27", "27 Compromise"), ("28", "28 Total penalties"),
    ("29", "29 TOTAL AMOUNT PAYABLE/(overpayment)"), ("30", "30 Aggregate amount payable/(overpayment)"),
    ("36", "36 Sales/revenues/receipts/fees"), ("37", "37 Less: sales returns, allowances and discounts"),
    ("38", "38 Net sales/revenues/receipts/fees"), ("39", "39 Less: OSD (40% of item 38)"),
    ("40", "40 Net income"), ("41", "41 Other non-operating income"), ("42", "42 Other non-operating income"),
    ("43", "43 Share in GPP income"), ("44", "44 Total other income"), ("45", "45 Total taxable income"),
    ("46", "46 TAX DUE (graduated rates)"), ("47", "47 Sales/revenues/receipts/fees"),
    ("48", "48 Less: sales returns, allowances and discounts"), ("49", "49 Net sales/revenues/receipts/fees"),
    ("50", "50 Other non-operating income"), ("51", "51 Other non-operating income"),
    ("52", "52 Total other non-operating income"), ("53", "53 Total taxable income"),
    ("54", "54 Less: allowable reduction (₱250,000)"), ("55", "55 Taxable income/(loss)"),
    ("56", "56 TAX DUE (8%)"), ("57", "57 Prior year's excess credits"),
    ("58", "58 Tax payments for the first three quarters"),
    ("59", "59 Creditable tax withheld in the first three quarters"),
    ("60", "60 Creditable tax withheld in the 4th quarter (2307)"), ("61", "61 Tax paid in return previously filed"),
    ("62", "62 Foreign tax credits"), ("63", "63 Other tax credits/payments"),
    ("64", "64 Total tax credits/payments"), ("65", "65 Net tax payable/(overpayment)"),
)
FORM_ITEMS["BalanceSheet"] = (
    ("current_assets", "Current assets"), ("ppe_net", "Property, plant and equipment, net"),
    ("other_noncurrent_assets", "Other non-current assets"), ("total_assets", "Total assets"),
    ("current_liabilities", "Current liabilities"), ("noncurrent_liabilities", "Non-current liabilities"),
    ("total_liabilities", "Total liabilities"), ("equity", "Equity"),
    ("total_liabilities_equity", "Total liabilities and equity"),
)
FORM_NOTES["1702RT"] = {
    "29": "27 − 28", "31": "29 − 30", "33": "31 + 32", "34": "Schedule I item 18", "36": "Schedule IIIA item 8",
    "37": "Sum of 34 to 36", "38": "40% × 33", "39": "33 − 37 (or 33 − 38 with OSD)", "41": "39 × 40",
    "42": "MCIT rate × 33 (2%; 1% Jul 2020–Jun 2023)", "43": "Higher of 41 and 42", "46": "Tax paid on the Q1–Q3 1702-Q (QuarterCredits tab)",
    "47": "Schedule IV item 4, up to 41 − 42", "55": "Sum of 44 to 54", "56": "43 − 55", "14": "Item 43",
    "15": "Item 55", "16": "Item 56", "21": "16 + 20", "S1_5": "Depreciation tab", "S1_18": "Sum of items 1 to 17",
}
FORM_NOTES["1701"] = {
    "S2_6": "4 − 5", "S2_7": "Graduated table on item 6", "S3_17": "40% × 10", "S3_24": "Schedule 2 item 6 + 23",
    "S3_28": "26 + 27", "S3_30": "28 − 29", "S3_31": "8% × 30", "S3_32": "Schedule 2 item 7 + 31",
    "P7_5": "Tax withheld per the 2316 (annual inputs)",
    "S3_12": "10 − 11", "S3_13": "Schedule 4 item 18", "S3_15": "Schedule 6.A.1 item 8", "S3_16": "Sum of 13 to 15",
    "S3_18": "12 − 16", "S3_23": "18 + 22", "S3_25": "Graduated table on item 24", "P7_2": "QuarterCredits tab",
    "P7_10": "Sum of 1 to 9", "22": "Part VI item 5", "23": "Part VII item 10", "24": "22 − 23", "31": "26 + 30",
}
FORM_NOTES["1701A"] = {
    "38": "36 − 37", "39": "40% × 38", "40": "38 − 39", "45": "40 + 44", "46": "Graduated table on item 45",
    "53": "49 + 52", "55": "53 − 54", "56": "8% × 55", "58": "QuarterCredits tab", "64": "Sum of 57 to 63",
    "65": "46 or 56, less 64", "20": "Item 46 or 56", "29": "24 + 28",
}
FORM_NOTES["BalanceSheet"] = {"ppe_net": "Asset register net book value unless entered",
                              "total_liabilities_equity": "Should equal total assets"}

LEDGER_ORDER = ("SLS", "SLP", "SAWT", "QAP", "Depreciation", "NOLCO", "ExcessMCIT", "QuarterCredits", "Transactions",
                "SJ", "PJ", "CRJ", "CDJ", "GJ", "GL", "AR", "AP", "TB", "PCTB", "SFP", "IS", "SCE", "SCF", "ARAging", "APAging")
LEDGER_TITLES.update({"Depreciation": "Asset register and depreciation", "NOLCO": "Net operating loss carry-over",
                      "ExcessMCIT": "Excess MCIT carry-over", "QuarterCredits": "Income tax paid and withheld by quarter"})
_CARRY_COLUMNS = (("year", "Year incurred", "text"), ("amount", "Amount", "money"),
                  ("used_before", "Used before", "money"), ("used_this_year", "Used this year", "money"),
                  ("expired_this_year", "Expired this year", "money"), ("remaining", "Remaining", "money"),
                  ("expiry_year", "Last year usable", "text"))
LEDGER_COLUMNS.update({
    "Depreciation": (("description", "Asset", "text"), ("doc_number", "Document", "text"),
                     ("in_service", "In service", "text"), ("cost", "Cost", "money"),
                     ("life_months", "Life (months)", "text"), ("end_date", "Retired", "text"),
                     ("accumulated_start", "Accumulated at start of year", "money"),
                     ("this_year", "This year", "money"), ("accumulated_end", "Accumulated at year end", "money"),
                     ("net_book_value", "Net book value", "money")),
    "NOLCO": _CARRY_COLUMNS,
    "ExcessMCIT": _CARRY_COLUMNS[:1] + (("normal_tax", "Normal income tax", "money"), ("mcit", "MCIT", "money"))
    + _CARRY_COLUMNS[1:],
    "QuarterCredits": (("quarter", "Quarter", "text"), ("source", "Source", "text"),
                       ("tax_paid", "Income tax paid", "money"), ("cwt", "Tax withheld (2307)", "money")),
})

# --- Books of accounts ------------------------------------------------------------------------

_JOURNAL_HEAD = (("date", "Date", "text"), ("entry_no", "Entry no.", "text"), ("reference", "Reference", "text"),
                 ("party", "Name", "text"), ("tin", "TIN", "text"), ("particulars", "Particulars", "text"))
_SUNDRY = (("sundry_account", "Sundry account", "text"), ("sundry_dr", "Sundry Dr", "money"),
           ("sundry_cr", "Sundry Cr", "money"))
_RUNNING = (("debit", "Debit", "money"), ("credit", "Credit", "money"), ("balance", "Balance", "money"),
            ("side", "Dr/Cr", "text"))
LEDGER_TITLES.update({
    "SJ": "Sales Journal", "PJ": "Purchase Journal", "CRJ": "Cash Receipts Journal",
    "CDJ": "Cash Disbursements Journal", "GJ": "General Journal", "GL": "General Ledger",
    "AR": "Accounts receivable ledger", "AP": "Accounts payable ledger", "TB": "Trial balance",
    "PCTB": "Post-closing trial balance", "SFP": "Statement of financial position", "IS": "Income statement",
    "SCE": "Statement of changes in equity", "SCF": "Statement of cash flows",
})
LEDGER_COLUMNS.update({
    "SJ": _JOURNAL_HEAD + (("ar", "Accounts receivable Dr", "money"), ("vatable", "VATable sales", "money"),
                           ("zero_rated", "Zero-rated sales", "money"), ("exempt", "Exempt sales", "money"),
                           ("output_vat", "Output VAT Cr", "money")),
    "PJ": _JOURNAL_HEAD + (("account", "Account", "text"), ("expense", "Purchases / expense Dr", "money"),
                           ("input_vat", "Input VAT Dr", "money"), ("ewt", "EWT payable Cr", "money"),
                           ("ap", "Accounts payable Cr", "money")),
    "CRJ": _JOURNAL_HEAD + (("cash", "Cash on hand Dr", "money"), ("bank", "Cash in bank Dr", "money"),
                            ("cwt", "CWT Dr", "money"), ("ar", "Accounts receivable Cr", "money")) + _SUNDRY,
    "CDJ": _JOURNAL_HEAD + (("cash", "Cash on hand Cr", "money"), ("bank", "Cash in bank Cr", "money"),
                            ("ap", "Accounts payable Dr", "money"), ("input_vat", "Input VAT Dr", "money"),
                            ("ewt", "EWT payable Cr", "money")) + _SUNDRY,
    "GJ": (("date", "Date", "text"), ("entry_no", "Entry no.", "text"), ("code", "Account code", "text"),
           ("account", "Account title", "text"), ("particulars", "Particulars", "text"), ("debit", "Debit", "money"),
           ("credit", "Credit", "money")),
    "GL": (("code", "Account code", "text"), ("account", "Account title", "text"), ("date", "Date", "text"),
           ("reference", "Entry no.", "text"), ("particulars", "Particulars", "text")) + _RUNNING,
    "AR": (("party", "Customer", "text"), ("tin", "TIN", "text"), ("date", "Date", "text"),
           ("reference", "Entry no.", "text"), ("particulars", "Particulars", "text")) + _RUNNING,
    "AP": (("party", "Supplier", "text"), ("tin", "TIN", "text"), ("date", "Date", "text"),
           ("reference", "Entry no.", "text"), ("particulars", "Particulars", "text")) + _RUNNING,
    "TB": (("code", "Account code", "text"), ("account", "Account title", "text"), ("debit", "Debit", "money"),
           ("credit", "Credit", "money")),
})
_STATEMENT = (("line", "", "text"), ("amount", "Amount", "money"))
LEDGER_COLUMNS.update({"PCTB": LEDGER_COLUMNS["TB"], "SFP": _STATEMENT, "IS": _STATEMENT, "SCE": _STATEMENT,
                       "SCF": _STATEMENT})

# Aging of open items as of the quarter's end (compute/subledger.py): one row per open sale / bill.
_AGING = (("party", "Name", "text"), ("tin", "TIN", "text"), ("doc_number", "Document", "text"), ("date", "Date", "text"),
          ("due", "Due", "text"), ("days", "Days past due", "text"), ("total_amount", "Total", "money"),
          ("withheld", "Tax withheld", "money"), ("paid", "Paid", "money"), ("current", "Current", "money"),
          ("1-30", "1–30 days", "money"), ("31-60", "31–60 days", "money"), ("61-90", "61–90 days", "money"),
          ("90+", "Over 90 days", "money"), ("open", "Open", "money"))
LEDGER_TITLES.update({"ARAging": "Accounts receivable aging", "APAging": "Accounts payable aging"})
LEDGER_COLUMNS.update({"ARAging": (("party", "Customer", "text"),) + _AGING[1:],
                       "APAging": (("party", "Supplier", "text"),) + _AGING[1:] + (("unverified", "Payment unverified", "text"),)})
