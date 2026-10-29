"""Maintenance switches: every gated route maps to a feature, and the effective state per firm."""

import re
import uuid

import pytest

from app.services import features as f


def _routes():
    """(method, full route template) for every gated route (FastAPI keeps included routers lazy, so walk them)."""
    from fastapi.routing import APIRoute

    from app.routers import accounting, team

    def walk(router, prefix):
        for r in router.routes:
            if isinstance(r, APIRoute):
                for m in r.methods:
                    yield m, prefix + r.path
            elif hasattr(r, "original_router"):
                yield from walk(r.original_router, prefix + (r.include_context.prefix or ""))

    yield from walk(accounting.router, "/api/accounting")
    yield from walk(team.router, "/api/team")


def _concrete(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "3f0c", path)


def test_walk_finds_the_routes():
    paths = {p for _, p in _routes()}
    assert len(paths) > 100
    assert "/api/accounting/companies/{company_id}/books/close" in paths and "/api/team/members" in paths


def test_every_gated_route_has_a_feature_or_is_always_on():
    missing = sorted({(m, p) for m, p in _routes()
                      if f.feature_for_route(m, p) is None and p not in f.ALWAYS_ON})
    assert missing == [], f"add these to features.ROUTES or ALWAYS_ON: {missing}"


def test_a_real_path_maps_like_its_template():
    # The gate sees the request path, not the template.
    assert [(m, p) for m, p in _routes() if f.feature_for_route(m, _concrete(p)) != f.feature_for_route(m, p)] == []


def test_routes_only_name_known_features():
    assert {key for _, _, key in f.ROUTES} <= set(f.KEYS)
    assert len(f.KEYS) == len(set(f.KEYS))


@pytest.mark.parametrize("method,path,key", [
    ("POST", "/api/accounting/companies/{company_id}/books/close", "close"),
    ("POST", "/api/accounting/companies/{company_id}/books/reopen", "close"),
    ("GET", "/api/accounting/companies/{company_id}/books/{fiscal_year}", "books"),
    ("POST", "/api/accounting/uploads", "upload"),
    ("GET", "/api/accounting/uploads/pending", None),
    ("GET", "/api/accounting/companies", None),
    ("POST", "/api/accounting/companies", "companies"),
    ("DELETE", "/api/accounting/companies/{company_id}", "companies"),
    ("POST", "/api/accounting/companies/{company_id}/restore", "companies"),
    ("POST", "/api/accounting/companies/{company_id}/contacts", "subledgers"),
    ("DELETE", "/api/accounting/contacts/{contact_id}", "subledgers"),
    ("POST", "/api/accounting/contacts/{contact_id}/restore", "subledgers"),
    ("POST", "/api/accounting/companies/{company_id}/bank/rules", "bank"),
    ("PUT", "/api/accounting/bank-rules/{rule_id}", "bank"),
    ("PUT", "/api/accounting/coa-templates/{template_id}", "companies"),
    ("GET", "/api/accounting/companies/{company_id}/accounts", None),
    ("POST", "/api/accounting/companies/{company_id}/accounts", "books"),
    ("PUT", "/api/accounting/documents/{document_id}/cwt-2307", "subledgers"),
    ("PATCH", "/api/accounting/documents/{doc_id}", "documents"),
    ("GET", "/api/accounting/periods/{company_id}/{year}/{quarter}", None),
    ("POST", "/api/accounting/periods/{company_id}/{year}/{quarter}/generate", "filing"),
    ("GET", "/api/accounting/periods/{company_id}/{year}/annual", "annual"),
    ("GET", "/api/accounting/outputs/{output_id}/pdf", "filing"),
    ("POST", "/api/accounting/bank-lines/{line_id}/confirm", "bank"),
    ("GET", "/api/accounting/companies/{company_id}/kpis", "reports"),
    ("GET", "/api/accounting/notifications", "notifications"),
    ("GET", "/api/team/members", "team"),
])
def test_route_mapping(method, path, key):
    assert f.feature_for_route(method, path) == key


def test_firm_override_wins_over_the_global_switch():
    eff = f.resolve({"close": False, "bank": False}, {"bank": True, "reports": False})
    assert eff["close"] is False and eff["bank"] is True and eff["reports"] is False
    assert eff["books"] is True and set(eff) == set(f.KEYS)


def test_firm_of_members_is_their_owner():
    from app.models.user import User, UserRole

    owner = User(id=uuid.uuid4(), email="o@x", role=UserRole.ENTERPRISE)
    staff = User(id=uuid.uuid4(), email="s@x", role=UserRole.EMPLOYEE, enterprise_id=owner.id)
    admin = User(id=uuid.uuid4(), email="a@x", role=UserRole.ADMIN)
    assert f.firm_of(owner) == owner.id and f.firm_of(staff) == owner.id and f.firm_of(admin) is None


def test_off_message_names_the_feature():
    assert f.off_message("close").startswith("Month close is turned off")
