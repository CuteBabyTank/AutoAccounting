"""Form edits must stay literal in both downloadable workbook variants."""
import pytest
from openpyxl import Workbook, load_workbook

from app.services.accounting import render_xlsx
from app.services.accounting.form_edits import apply_edits


@pytest.mark.parametrize('clean', [False, True])
def test_form_text_edits_are_literal_and_amounts_stay_numeric(tmp_path, clean):
    values = {'S1_ATC': 'WI010', 'S1_BASE': '1000.00', 'S1_RATE': '5', 'S1_TAX': '50.00', '31': '50.00'}
    edits = apply_edits(values, {'S1_ATC': '=1+1'})
    values.update(edits)
    path = tmp_path / 'return.xlsx'
    render_xlsx.write_workbook(
        path, header={'company': 'Dummy', 'tin': '123456789', 'period': '2026 Q1', 'generated': 'now'},
        snapshot={'forms': {'1601EQ': values}, 'ledgers': {}}, warnings=[], review_open=0,
        due={}, version=2, parent_version=1, clean=clean,
        diff={'forms': {'1601EQ': {'S1_ATC': ['WI010', '=1+1']}}, 'ledgers': {}},
    )
    book = load_workbook(path, data_only=False)
    cells = {row[0].value: row[2] for row in book['1601EQ'].iter_rows(min_row=4)}
    assert cells['S1_ATC'].data_type == 's'
    assert cells['S1_ATC'].value == "'=1+1"
    assert cells['S1_BASE'].data_type == 'n'
    assert cells['S1_BASE'].value == 1000
    book.close()


def test_year_branch_also_keeps_text_literal(monkeypatch):
    monkeypatch.setattr(render_xlsx, 'form_items', lambda form, values: [('TEST_YEAR', 'Year')])
    book = Workbook()
    render_xlsx._form_sheet(book, '1601EQ', {'TEST_YEAR': '=1+1'}, {}, 1, None)
    assert book['1601EQ']['C4'].data_type == 's'
    assert book['1601EQ']['C4'].value == "'=1+1"
