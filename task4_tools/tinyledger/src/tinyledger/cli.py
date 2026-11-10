from __future__ import annotations

import argparse
import sys

from .io_csv import load_expenses
from .ledger import Ledger
from .money import format_cents
from .settle import settle


def _load(args) -> Ledger:
    ledger = Ledger(load_expenses(args.csv_file))
    if args.month:
        year, month = (int(x) for x in args.month.split("-"))
        ledger = ledger.for_month(year, month)
    return ledger


def cmd_report(args) -> int:
    ledger = _load(args)
    title = f"Expenses {args.month}" if args.month else "All expenses"
    print(title)
    print("=" * len(title))
    for expense in sorted(ledger.expenses, key=lambda e: e.day):
        print(f"{expense.day.isoformat()}  {expense.payer:<6} {format_cents(expense.amount_cents):>12}  {expense.description}")
    print()
    print(f"Total: {format_cents(ledger.total_cents())}")
    for payer, total in ledger.totals_by_payer().items():
        print(f"  paid by {payer}: {format_cents(total)}")
    return 0


def cmd_balances(args) -> int:
    for person, balance in sorted(_load(args).balances().items()):
        print(f"{person:<8} {format_cents(balance):>12}")
    return 0


def cmd_settle(args) -> int:
    for transfer in settle(_load(args).balances()):
        print(f"{transfer.sender} -> {transfer.receiver}: {format_cents(transfer.amount_cents)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tinyledger", description="Split group expenses.")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, func, help_text in [
        ("report", cmd_report, "list expenses and totals"),
        ("balances", cmd_balances, "show who owes how much"),
        ("settle", cmd_settle, "compute transfers to settle all debts"),
    ]:
        p = sub.add_parser(name, help=help_text)
        p.add_argument("csv_file")
        p.add_argument("--month", help="only expenses of this month, format YYYY-MM")
        p.set_defaults(func=func)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
