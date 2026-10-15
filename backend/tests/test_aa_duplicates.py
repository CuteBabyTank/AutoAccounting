import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.services.accounting.duplicates import (
    FLAG, SAME_DETAILS, SAME_NUMBER, DupDoc, Pair, duplicate_pairs, sync_flags,
)


def _d(number="SI-1", party="111222333", day=date(2026, 7, 1), gross="1120.00", role="buyer", cleared=()):
    return DupDoc(id=uuid.uuid4(), role=role, counterparty=party, doc_number=number, doc_date=day,
                  gross=Decimal(gross), not_duplicate_of=frozenset(cleared))


def test_same_counterparty_and_number_pairs_the_later_copy():
    a, b = _d(), _d(gross="999.00")
    assert duplicate_pairs([a, b]) == [Pair(a.id, b.id, SAME_NUMBER)]


def test_same_number_on_different_dates_is_a_series_not_a_copy():
    assert duplicate_pairs([_d(day=date(2026, 9, 30)), _d(day=date(2026, 12, 31))]) == []
    a, b = _d(), _d(day=None)  # an undated copy still pairs
    assert duplicate_pairs([a, b]) == [Pair(a.id, b.id, SAME_NUMBER)]


def test_misread_or_missing_number_still_pairs_on_date_and_total():
    a, b = _d(number="SI-1"), _d(number="")
    assert duplicate_pairs([a, b]) == [Pair(a.id, b.id, SAME_DETAILS)]


def test_two_numbered_papers_with_the_same_total_are_different():
    assert duplicate_pairs([_d(number="SI-1"), _d(number="SI-2")]) == []


def test_other_counterparty_or_side_is_not_a_duplicate():
    assert duplicate_pairs([_d(), _d(party="999888777")]) == []
    assert duplicate_pairs([_d(), _d(role="seller")]) == []
    assert duplicate_pairs([_d(number="", day=None), _d(number="", day=None)]) == []


def test_a_pair_marked_not_duplicate_is_never_offered_again():
    a = _d()
    b = _d(cleared=[str(a.id)])
    assert duplicate_pairs([a, b]) == []
    c = _d()  # a third copy still pairs with the first
    assert duplicate_pairs([a, b, c]) == [Pair(a.id, c.id, SAME_NUMBER)]


def _row(reasons=(), reviewed=False):
    return SimpleNamespace(id=uuid.uuid4(), review_reasons=list(reasons), needs_review=bool(reasons), reviewed=reviewed)


def test_sync_flags_marks_copies_and_clears_resolved_ones():
    original, copy, resolved, done = _row(), _row(), _row([FLAG]), _row(reviewed=True)
    docs = {d.id: d for d in (original, copy, resolved, done)}
    sync_flags([Pair(original.id, copy.id, SAME_NUMBER), Pair(original.id, done.id, SAME_NUMBER)], docs)
    assert copy.review_reasons == [FLAG] and copy.needs_review
    assert original.review_reasons == []
    assert resolved.review_reasons == [] and not resolved.needs_review
    assert done.review_reasons == []  # a reviewed copy isn't sent back to review
