from __future__ import annotations

from .models import Expense
from .money import split_evenly


class Ledger:
    """A list of expenses with helpers to compute who owes whom."""

    def __init__(self, expenses: list[Expense] | None = None) -> None:
        self.expenses: list[Expense] = list(expenses or [])

    def add(self, expense: Expense) -> None:
        self.expenses.append(expense)

    def people(self) -> list[str]:
        names = set()
        for expense in self.expenses:
            names.add(expense.payer)
            names.update(expense.participants)
        return sorted(names)

    def total_cents(self) -> int:
        return sum(expense.amount_cents for expense in self.expenses)

    def totals_by_payer(self) -> dict[str, int]:
        totals: dict[str, int] = {}
        for expense in self.expenses:
            totals[expense.payer] = totals.get(expense.payer, 0) + expense.amount_cents
        return dict(sorted(totals.items()))

    def for_month(self, year: int, month: int) -> "Ledger":
        return Ledger([e for e in self.expenses if e.day.year == year and e.day.month == month])

    def balances(self) -> dict[str, int]:
        """Positive balance: the person gets money back. Negative: the person owes money."""
        balances = {expense.payer: 0 for expense in self.expenses}
        for expense in self.expenses:
            balances[expense.payer] += expense.amount_cents
            shares = split_evenly(expense.amount_cents, len(expense.participants))
            for person, share in zip(expense.participants, shares):
                balances[person] -= share
        return balances
