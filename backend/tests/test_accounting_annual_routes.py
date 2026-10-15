from datetime import date

import pytest
from pydantic import ValidationError

from app.schemas.accounting import AnnualInputsModel, AssetPatch


def _endpoint(method: str, path: str):
    """The first route, in the app's matching order, that takes this request."""
    from app.main import app

    path = "/api/accounting" + path

    def walk(routes):
        for route in routes:
            candidates = getattr(route, "effective_candidates", None)
            if candidates is not None:  # an included router (FastAPI ≥ 0.13x): its routes, in order
                found = walk(candidates() if callable(candidates) else candidates)
                if found:
                    return found
                continue
            regex = getattr(route, "path_regex", None)
            if regex is not None and regex.match(path) and method in (getattr(route, "methods", None) or ()):
                return route.endpoint.__name__
        return None

    return walk(app.router.routes)


def test_annual_paths_reach_the_annual_handlers_not_the_quarter_ones():
    cid = "6a1c2f40-0000-4000-8000-000000000000"
    assert _endpoint("GET", f"/periods/{cid}/2026/annual") == "get_annual_period"
    assert _endpoint("PUT", f"/periods/{cid}/2026/annual/inputs") == "save_annual_inputs"
    assert _endpoint("PUT", f"/periods/{cid}/2026/annual/filed") == "set_annual_filed"
    assert _endpoint("POST", f"/periods/{cid}/2026/annual/generate") == "generate_annual"
    assert _endpoint("GET", f"/periods/{cid}/2026/3") == "get_period"
    assert _endpoint("GET", f"/companies/{cid}/assets") == "list_assets"
    assert _endpoint("PATCH", f"/assets/{cid}") == "patch_asset"


def test_annual_inputs_model_validates_opening_rows():
    model = AnnualInputsModel(opening_nolco=[{"year": 2023, "amount": "5000", "used": "0"}], other_reconciling="-5")
    assert model.opening_nolco[0].year == 2023 and str(model.other_reconciling) == "-5"
    with pytest.raises(ValidationError):
        AnnualInputsModel(opening_nolco=[{"year": 1990, "amount": "5"}])
    with pytest.raises(ValidationError):
        AnnualInputsModel(opening_nolco=[{"year": 2023, "amount": "0"}])
    with pytest.raises(ValidationError):
        AnnualInputsModel(q1_paid="-1")


def test_asset_patch_bounds():
    assert AssetPatch(useful_life_months=600).useful_life_months == 600
    with pytest.raises(ValidationError):
        AssetPatch(useful_life_months=0)
    with pytest.raises(ValidationError):
        AssetPatch(in_service=date(2026, 5, 1), end_date=date(2026, 4, 1))
    with pytest.raises(ValidationError):
        AssetPatch(description="x" * 256)
