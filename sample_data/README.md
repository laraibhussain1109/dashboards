# Explicit example datasets

These are synthetic business examples, not real company records. Import them manually through the upload interface. The application never silently seeds or publishes them.

`example_sales.csv` and the **Sales** worksheet in `example_business.xlsx` contain the same 12 records from January–March 2026.

Known results without filters:

- Revenue: 154,600
- Cost: 84,600
- Profit (`SUM([Revenue]) - SUM([Cost])`): 70,000
- Units: 540
- Distinct customer IDs: 12
- North revenue: 45,400

The **Operations** worksheet contains 4 records. Produced totals 3,950; accepted totals 3,835; rejected totals 115. Rejection percentage is `SUM([Rejected]) / SUM([Produced]) * 100` = 2.911392%.

Use these figures to check KPI formulas, grouping, category/date filters, template selection, and publishing against known values.
