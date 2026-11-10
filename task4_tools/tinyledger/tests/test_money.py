import pytest

from tinyledger.money import format_cents, parse_amount


@pytest.mark.parametrize(
    "text, cents",
    [("12,50", 1250), ("12.50", 1250), ("1.234,56", 123456), ("7 €", 700), ("0,05", 5), ("-3,20", -320), ("19,9", 1990)],
)
def test_parse_amount(text, cents):
    assert parse_amount(text) == cents


@pytest.mark.parametrize("text", ["", "abc", "12,x0"])
def test_parse_amount_invalid(text):
    with pytest.raises(ValueError):
        parse_amount(text)


@pytest.mark.parametrize("cents, text", [(0, "0,00 €"), (5, "0,05 €"), (123456, "1234,56 €"), (-320, "-3,20 €")])
def test_format_cents(cents, text):
    assert format_cents(cents) == text
