from datetime import date

from tinyledger import Expense, Ledger, Transfer, settle


def test_two_people():
    assert settle({"Anna": 500, "Ben": -500}) == [Transfer("Ben", "Anna", 500)]


def test_nothing_to_settle():
    assert settle({"Anna": 0, "Ben": 0}) == []


def test_multiple_debtors():
    transfers = settle({"Anna": 1200, "Ben": -300, "Cem": -900})
    assert sorted(transfers, key=lambda t: t.sender) == [Transfer("Ben", "Anna", 300), Transfer("Cem", "Anna", 900)]


def test_settle_uneven_three_way_split():
    ledger = Ledger(
        [
            Expense(date(2026, 3, 1), "Anna", 1000, ["Anna", "Ben", "Cem"], "Snacks"),
            Expense(date(2026, 3, 2), "Ben", 500, ["Anna", "Ben", "Cem"], "Drinks"),
            Expense(date(2026, 3, 3), "Cem", 200, ["Anna", "Ben", "Cem"], "Napkins"),
        ]
    )
    transfers = settle(ledger.balances())
    received = sum(t.amount_cents for t in transfers if t.receiver == "Anna")
    assert 430 <= received <= 434
