from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Transfer:
    sender: str
    receiver: str
    amount_cents: int


def settle(balances: dict[str, int]) -> list[Transfer]:
    """Compute a short list of transfers that brings every balance to zero.

    Greedy: the person who owes the most pays the person who gets the most back.
    """
    total = sum(balances.values())
    if total != 0:
        raise ValueError(f"balances do not sum to zero (off by {total} cents)")

    debtors = sorted(((-b, p) for p, b in balances.items() if b < 0), reverse=True)
    creditors = sorted(((b, p) for p, b in balances.items() if b > 0), reverse=True)
    debtors = [[amount, person] for amount, person in debtors]
    creditors = [[amount, person] for amount, person in creditors]

    transfers = []
    i = j = 0
    while i < len(debtors) and j < len(creditors):
        amount = min(debtors[i][0], creditors[j][0])
        transfers.append(Transfer(debtors[i][1], creditors[j][1], amount))
        debtors[i][0] -= amount
        creditors[j][0] -= amount
        if debtors[i][0] == 0:
            i += 1
        if creditors[j][0] == 0:
            j += 1
    return transfers
