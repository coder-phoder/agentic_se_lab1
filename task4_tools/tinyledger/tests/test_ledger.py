from datetime import date

from tinyledger import Expense, Ledger


def make_ledger():
    return Ledger(
        [
            Expense(date(2026, 3, 14), "Anna", 3000, ["Anna", "Ben", "Cem"], "Pizza"),
            Expense(date(2026, 3, 20), "Ben", 1500, ["Anna", "Ben", "Cem"], "Cinema"),
            Expense(date(2026, 4, 2), "Cem", 900, ["Anna", "Ben", "Cem"], "Coffee"),
        ]
    )


def test_people():
    assert make_ledger().people() == ["Anna", "Ben", "Cem"]


def test_totals():
    ledger = make_ledger()
    assert ledger.total_cents() == 5400
    assert ledger.totals_by_payer() == {"Anna": 3000, "Ben": 1500, "Cem": 900}


def test_for_month():
    march = make_ledger().for_month(2026, 3)
    assert [e.description for e in march.expenses] == ["Pizza", "Cinema"]


def test_balances_everyone_paid():
    assert make_ledger().balances() == {"Anna": 1200, "Ben": -300, "Cem": -900}


def test_balances_participant_who_never_paid():
    ledger = Ledger(
        [
            Expense(date(2026, 3, 14), "Anna", 2000, ["Anna", "Dana"], "Train tickets"),
        ]
    )
    assert ledger.balances() == {"Anna": 1000, "Dana": -1000}
