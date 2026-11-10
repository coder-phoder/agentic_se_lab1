from datetime import date

from tinyledger.io_csv import load_expenses, parse_date

CSV = """date;payer;amount;participants;description
14.02.2026;Anna;42,00;Anna,Ben;Groceries
2026-02-20;Ben;9,90;Ben, Anna ;Parking
23.03.2026;Anna;1.200,00;Anna,Ben;Rent
"""


def test_load_expenses(tmp_path):
    path = tmp_path / "expenses.csv"
    path.write_text(CSV, encoding="utf-8")
    expenses = load_expenses(path)
    assert [e.amount_cents for e in expenses] == [4200, 990, 120000]
    assert expenses[1].participants == ["Ben", "Anna"]
    assert expenses[0].day == date(2026, 2, 14)
    assert expenses[2].day == date(2026, 3, 23)


def test_iso_dates():
    assert parse_date("2026-02-20") == date(2026, 2, 20)
