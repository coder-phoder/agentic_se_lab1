"""Reading expenses from CSV files exported by the group's spreadsheet.

Format (semicolon-separated, German number format):
    date;payer;amount;participants;description
    05.03.2026;Anna;42,00;Anna,Ben,Cem;Groceries
"""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from .models import Expense
from .money import parse_amount

REQUIRED_COLUMNS = ["date", "payer", "amount", "participants", "description"]


def parse_date(text: str) -> date:
    """Parse a date like '05.03.2026'. ISO dates ('2026-03-05') are accepted too."""
    text = text.strip()
    if "-" in text:
        return date.fromisoformat(text)
    first, second, year = (int(part) for part in text.split("."))
    month, day = first, second
    if month > 12:
        # clearly the other way round
        month, day = second, first
    return date(year, month, day)


def load_expenses(path: str | Path) -> list[Expense]:
    with Path(path).open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        missing = [c for c in REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"missing columns: {', '.join(missing)}")
        expenses = []
        for line_number, row in enumerate(reader, start=2):
            try:
                expenses.append(
                    Expense(
                        day=parse_date(row["date"]),
                        payer=row["payer"].strip(),
                        amount_cents=parse_amount(row["amount"]),
                        participants=[p.strip() for p in row["participants"].split(",") if p.strip()],
                        description=row["description"].strip(),
                    )
                )
            except ValueError as exc:
                raise ValueError(f"line {line_number}: {exc}") from exc
    return expenses
