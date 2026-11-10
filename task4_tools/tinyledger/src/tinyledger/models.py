from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class Expense:
    """One payment made by `payer` on behalf of `participants` (the payer can be one of them)."""

    day: date
    payer: str
    amount_cents: int
    participants: list[str] = field(default_factory=list)
    description: str = ""

    def __post_init__(self) -> None:
        if self.amount_cents <= 0:
            raise ValueError(f"amount must be positive, got {self.amount_cents}")
        if not self.participants:
            raise ValueError("an expense needs at least one participant")
