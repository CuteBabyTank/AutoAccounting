"""OCR field normalisation. Pure functions, no I/O."""

from app.ocr import (
    clean_amount,
    clean_atc,
    clean_date,
    clean_text,
    clean_tin,
    clean_zip,
)


class TestCleanTin:
    def test_dashed_9_digit(self):
        assert clean_tin("123-456-789") == "123-456-789"

    def test_12_digit_branch_code(self):
        assert clean_tin("123456789000") == "123-456-789-000"

    def test_14_digit_extended(self):
        assert clean_tin("12345678900012") == "123-456-789-00012"

    def test_strips_letters_and_spaces(self):
        assert clean_tin("TIN: 123 456 789 000 ") == "123-456-789-000"

    def test_short_returns_digits(self):
        assert clean_tin("12345") == "12345"

    def test_empty(self):
        assert clean_tin("") == ""


class TestCleanDate:
    def test_compact_8_digit(self):
        assert clean_date("12312024") == "12/31/2024"

    def test_already_formatted(self):
        assert clean_date("12/31/2024") == "12/31/2024"

    def test_partial_falls_back_to_collapsed_text(self):
        assert clean_date("Q1  2024") == "Q1 2024"


class TestCleanAmount:
    def test_strips_peso_sign(self):
        assert clean_amount("PHP 1,234.56") == "1,234.56"

    def test_letter_o_inside_digits(self):
        assert clean_amount("1O0.00") == "100.00"

    def test_leading_o(self):
        assert clean_amount("O.50") == "0.50"

    def test_negative_preserved(self):
        assert clean_amount("-1,234.56") == "-1,234.56"


class TestCleanAtc:
    def test_uppercases_and_caps_at_6(self):
        assert clean_atc("wi010") == "WI010"
        assert clean_atc("ABCDEFGHIJ") == "ABCDEF"

    def test_strips_punct(self):
        assert clean_atc("WI-010") == "WI010"


class TestCleanZip:
    def test_4_digit(self):
        assert clean_zip("1234") == "1234"

    def test_truncates_excess(self):
        assert clean_zip("123456") == "1234"

    def test_strips_letters(self):
        assert clean_zip("Manila 1000") == "1000"


class TestCleanText:
    def test_collapses_whitespace(self):
        assert clean_text("  hello   world  ") == "hello world"

    def test_strips_border_chars(self):
        assert clean_text("|_-: text :-_|") == "text"
