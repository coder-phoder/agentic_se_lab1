# Issue #17: March report shows wrong total

**Reported by:** Dana

When I run

```
python -m tinyledger report data/sample.csv --month 2026-03
```

the report says `Total: 197,40 €`. But when I add up all rows from March 2026 in `data/sample.csv` by hand, I get `362,30 €`.
Some of the March expenses are missing from the report, and I think I saw some of them in the reports for other months.

The February and April reports look strange too.

**Expected:** the report for a month contains exactly the expenses with a date in that month.
Dates in the CSV use the German format DD.MM.YYYY.
