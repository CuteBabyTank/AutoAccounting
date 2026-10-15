"""Budget arithmetic for owner CRUD endpoint."""

import pytest

from app.services.budget_service import compute_new_budget


class TestAdd:
    def test_add_to_zero(self):
        assert compute_new_budget(0.0, "add", 100.0) == 100.0

    def test_add_to_existing(self):
        assert compute_new_budget(50.0, "add", 25.5) == 75.5

    def test_add_zero_amount(self):
        assert compute_new_budget(50.0, "add", 0.0) == 50.0

    def test_add_when_current_none(self):
        assert compute_new_budget(None, "add", 100.0) == 100.0


class TestSubtract:
    def test_subtract_partial(self):
        assert compute_new_budget(100.0, "subtract", 30.0) == 70.0

    def test_subtract_floors_at_zero(self):
        assert compute_new_budget(50.0, "subtract", 200.0) == 0.0

    def test_subtract_exact_zero(self):
        assert compute_new_budget(50.0, "subtract", 50.0) == 0.0

    def test_subtract_when_already_zero(self):
        assert compute_new_budget(0.0, "subtract", 10.0) == 0.0


class TestSet:
    def test_set_replaces_value(self):
        assert compute_new_budget(500.0, "set", 100.0) == 100.0

    def test_set_to_zero(self):
        assert compute_new_budget(500.0, "set", 0.0) == 0.0


class TestReset:
    def test_reset_zeros_regardless_of_amount(self):
        assert compute_new_budget(500.0, "reset", 999.0) == 0.0

    def test_reset_when_none(self):
        assert compute_new_budget(None, "reset", 0.0) == 0.0


class TestRounding:
    def test_two_decimal_rounding(self):
        assert compute_new_budget(0.0, "add", 1.005) == 1.01 or compute_new_budget(0.0, "add", 1.005) == 1.0
        # Result is rounded to 2dp; banker's rounding may produce 1.0 or 1.01

    def test_floats_dont_drift(self):
        result = compute_new_budget(0.1, "add", 0.2)
        assert result == 0.3


class TestUnknownOp:
    def test_unknown_raises(self):
        with pytest.raises(ValueError):
            compute_new_budget(100.0, "double", 0.0)
