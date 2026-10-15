"""Spreadsheet formula-injection guard shared by every XLSX/CSV writer."""

# A cell starting with one of these is evaluated as a formula by Excel/Sheets;
# prefixing an apostrophe makes the spreadsheet treat it as literal text.
_FORMULA_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(value):
    """Neutralize spreadsheet formula triggers in cell values.
    Pass-through for non-string types (numbers, dates) so numeric formatting works."""
    if not isinstance(value, str) or not value:
        return value
    if value[0] in _FORMULA_TRIGGERS:
        return "'" + value
    return value
