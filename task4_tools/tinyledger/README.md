# tinyledger

Split group expenses and settle debts. Amounts are stored as integer cents.

## Usage

```bash
PYTHONPATH=src python -m tinyledger report data/sample.csv --month 2026-03
PYTHONPATH=src python -m tinyledger balances data/sample.csv
PYTHONPATH=src python -m tinyledger settle data/sample.csv
```

## Tests

```bash
python -m pytest
```

## Layout

| File | Content |
|---|---|
| `src/tinyledger/models.py` | `Expense` data class |
| `src/tinyledger/money.py` | parsing, formatting and splitting amounts |
| `src/tinyledger/ledger.py` | `Ledger`: totals, monthly filter, balances |
| `src/tinyledger/settle.py` | computing transfers from balances |
| `src/tinyledger/io_csv.py` | loading expenses from CSV |
| `src/tinyledger/cli.py` | command line interface |
