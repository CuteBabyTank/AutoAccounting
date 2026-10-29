import pytest
from pydantic import ValidationError
from app.schemas.accounting_bank import BankRuleIn


def test_rule_normalizes_narration_and_payee_tin():
    r = BankRuleIn(pattern='  E2E RENT  ', direction='out', kind='payee', payee_name=' E2E Landlord ',
                   payee_tin='123-456-789')
    assert r.pattern == 'e2e rent' and r.payee_name == 'E2E Landlord' and r.payee_tin == '123456789'


@pytest.mark.parametrize('values', [
    {'pattern': '  ', 'kind': 'posting', 'account_code': '1000'},
    {'pattern': 'RENT', 'kind': 'payee'},
    {'pattern': 'RENT', 'kind': 'posting'},
    {'pattern': 'RENT', 'kind': 'payee', 'payee_name': 'X', 'payee_tin': '123'},
])
def test_incomplete_rule_is_rejected(values):
    with pytest.raises(ValidationError):
        BankRuleIn(**values)
