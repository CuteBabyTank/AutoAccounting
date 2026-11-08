"""Bound shared-string expansion before per-cell whitespace copies."""
import io
import zipfile

import pytest

from app.services.accounting import payroll_import as sheets


def _shared_sheet(text: str, rows: int = 4) -> bytes:
    members = {
        '[Content_Types].xml': '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/></Types>',
        '_rels/.rels': '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        'xl/workbook.xml': '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Sheet" sheetId="1" r:id="rId1"/></sheets></workbook>',
        'xl/_rels/workbook.xml.rels': '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/></Relationships>',
        'xl/sharedStrings.xml': f'<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><si><t xml:space="preserve">{text}</t></si></sst>',
        'xl/worksheets/sheet1.xml': '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>' + '<row><c t="s"><v>0</v></c><c t="s"><v>0</v></c><c t="s"><v>0</v></c></row>' * rows + '</sheetData></worksheet>',
    }
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, value in members.items():
            archive.writestr(name, value)
    return data.getvalue()


def test_reject_long_shared_string_before_strip():
    with pytest.raises(ValueError, match="cell.*too long"):
        sheets.parse_sheet(_shared_sheet('A' * 2000 + ' '), 'payroll.xlsx')


def test_repeated_shared_string_counts_each_reference(monkeypatch):
    # Small bound exercises the exact expansion rule without allocating a large sheet.
    monkeypatch.setattr(sheets, 'MAX_SHEET_CHARS', 1000, raising=False)
    with pytest.raises(ValueError, match="too much text"):
        sheets.parse_sheet(_shared_sheet('A' * 100 + ' ', rows=5), 'payroll.xlsx')


def test_csv_cells_have_the_same_limit():
    with pytest.raises(ValueError, match="cell.*too long"):
        sheets.parse_sheet(('Name,TIN,Address\nA,123,' + 'B' * 2001).encode(), 'payroll.csv')
