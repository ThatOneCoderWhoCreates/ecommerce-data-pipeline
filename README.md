# E-Commerce Customer 360 Data Pipeline

This pipeline combines customer data from three separate systems into one clean customer profile (Customer 360). It checks data quality along the way and shows the results on a Streamlit dashboard.

| Source | System | Format | ID column in the file |
|---|---|---|---|
| `crm_customers.json` | CRM (Customer Relationship Management) | JSON | `customer_id` |
| `orders.csv` | Order Management | CSV | `cust_id` |
| `support_tickets.xml` | Customer Support | XML | `customerId` |

## Quick start

Requires Python 3.10 or newer.

### macOS / Linux

```bash
cd ecommerce-data-pipeline
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m pipeline.run
python -m pytest -v
streamlit run dashboard/app.py
```

### Windows (PowerShell)

```powershell
cd ecommerce-data-pipeline
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m pipeline.run
python -m pytest -v
streamlit run dashboard/app.py
```

The dashboard opens at http://localhost:8501. If the output files are missing, the dashboard runs the pipeline first. You can also re-run it from the sidebar.

## Project structure

```
ecommerce-data-pipeline/
├── config/pipeline_config.json   All settings: sources, column aliases, rules, thresholds
├── data/raw/                     Input files (JSON, CSV, XML)
├── pipeline/
│   ├── config.py                 Loads and checks the config
│   ├── logger.py                 Console and file logging
│   ├── loaders.py                Step 1: load JSON, CSV, XML
│   ├── schema.py                 Step 2: standardize column names
│   ├── quality.py                Step 3: data quality checks, cleaning, quality report
│   ├── merge.py                  Step 4: build Customer 360
│   ├── insights.py               Step 5: segmentation and business insights
│   └── run.py                    Runs all steps and writes outputs
├── dashboard/app.py              Streamlit dashboard
├── tests/                        50 unit and end-to-end tests (pytest)
├── output/                       Generated JSON outputs
└── logs/                         One log file per run
```

## How the pipeline works

### Step 1: Load

The file extension decides which loader to use (`.json`, `.csv`, `.xml`). Every value is loaded as raw text first, so nothing is silently converted before validation. An empty XML element such as `<customerId />` is read as a missing value.

### Step 2: Standardize schemas

Each column name is normalized: it is lowercased and everything except letters and digits is removed. So `customerId`, `cust_id`, `Cust_ID`, `cust-id` and `CUSTOMER ID` all become `customerid`. The normalized name is then matched against the alias list in `column_aliases` in the config, which gives the standard name `customer_id`. The same applies to every field:

| Standard name | Accepted aliases (examples) |
|---|---|
| `customer_id` | customerId, cust_id, C_ID, CID, client_id, customer_number |
| `support_tickets` | tickets, ticket_count, num_tickets |
| `last_ticket_date` | lastTicketDate, last_ticket |
| `lifetime_value` | LTV, CLV (Customer Lifetime Value), revenue, total_spend |

To support a new column name, add it to the config. No code change is needed. Columns that match no alias are kept and logged as a warning.

Values are also standardized:
- IDs are trimmed and uppercased.
- Emails are lowercased.
- City names are title-cased, and old names are mapped to current ones (for example, Bangalore becomes Bengaluru).
- Dates are accepted in several formats and output as `YYYY-MM-DD`.
- Amounts like `₹ 1,200` are converted to numbers.

### Step 3: Data quality checks

Rule: **if a value can be fixed safely, the record is kept, the bad value is set to null, and the record gets a flag. If the whole record can't be trusted, it is removed and saved to `quarantine.json` with the reason.**

| Check | Action |
|---|---|
| Exact duplicate record | Dropped (one copy kept) |
| Same ID with different values | Quarantined (first record kept) |
| Missing or invalid customer ID (pattern `^C\d{4}$`) | Quarantined, because it can't be joined to a customer |
| Invalid email | Email set to null, flagged `invalid_email` |
| Missing mandatory field | Flagged `missing_<field>` |
| Negative revenue or count | Value set to null, flagged `negative_<field>` |
| Unparseable number or date | Value set to null, flagged `invalid_<field>` |
| Future date | Value set to null, flagged `future_<field>` |
| Ticket date with 0 tickets (or order date with 0 orders) | Date set to null, flagged |
| Order or ticket record with no CRM customer | Quarantined as `orphan_record` |
| CRM customer with no order or support record | Kept, flagged `missing_<source>_record` |
| Order or ticket dated before registration | Flagged |

### Step 4: Customer 360

The CRM is the master customer list (`"primary": true` in the config). Orders and support data are left-joined on `customer_id`, so every CRM customer gets a profile even when a source has no record for them. Each profile also gets these derived fields:
- `avg_order_value`
- `days_since_last_order`
- `segment`
- `dq_flags`: lists every data quality issue for that customer.

```json
{
  "customer_id": "C0001",
  "name": "Priya Nair 1",
  "email": "user1@example.com",
  "city": "Mumbai",
  "registration_date": "2024-10-08",
  "total_orders": 12,
  "lifetime_value": 245631,
  "last_order_date": "2026-05-25",
  "support_tickets": 4,
  "last_ticket_date": "2026-07-31",
  "avg_order_value": 20469.25,
  "days_since_last_order": 165,
  "segment": "Gold",
  "dq_flags": []
}
```

### Step 5: Insights

- **Revenue analytics:** top 10 customers by lifetime value.
- **Segmentation:** Gold (above ₹1,00,000), Silver (₹50,000 to ₹1,00,000), Bronze (below ₹50,000). A customer with missing or invalid revenue is placed in **Unknown** instead of being guessed.
- **Support:** customers with more than 5 tickets, plus "Gold customers at risk" (high-value customers with many tickets).
- **Regional:** revenue, customer count and segment mix by city.
- **Customer behavior:** activity status from days since the last order (Active up to 90 days, Cooling 91 to 180, Inactive more than 180), a win-back list of inactive Gold customers, average order value by segment and city, correlations between revenue, orders and tickets, and new registrations by quarter.

Key findings on the provided data:
- 43% of customers have not ordered in more than 180 days. They hold ₹2.77 Cr of lifetime revenue, and 134 of them are Gold (₹2.27 Cr).
- High-value customers spend more per order, not more often. Revenue has a correlation of 0.00 with number of orders and 0.32 with average order value.
- Gold customers spend about ₹19,968 per order, compared with ₹4,126 for Bronze.
- Support tickets are not linked to spending (correlation 0.02).
- 171 Gold customers have more than 5 tickets, holding ₹2.97 Cr of revenue.

## Results on the provided data

```json
{
  "total_records": 1501,
  "duplicates": 1,
  "invalid_customer_ids": 1,
  "invalid_emails": 3,
  "missing_fields": 1,
  "negative_revenue": 1,
  "inconsistent_values": 35,
  "removed_records": 2,
  "repaired_records": 40,
  "successful_records": 1459
}
```

| Issue | Records |
|---|---|
| CRM: `C0105` listed twice (exact copy) | Duplicate dropped |
| CRM: `C0125`, `C0250`, `C0375` emails have no `@` | Email set to null, flagged |
| Orders: `C0310` has a blank `total_orders` | Flagged, average order value not computed |
| Orders: `C0420` has `lifetime_value = -5000` | Set to null, segment "Unknown" |
| Support: record 450 has an empty `<customerId />` | Quarantined |
| Support: 35 customers have 0 tickets but a last ticket date | Date set to null, flagged |
| `C0450` has no support record (its record is the one with the empty ID) | Kept, flagged `missing_support_record` |

`successful_records` counts records that passed every check without changes. `repaired_records` were kept with a flag. `removed_records` were dropped or quarantined. Each record is counted once, even if it has more than one issue.

The empty-ID support record sits between C0449 and C0451, so it is probably C0450. The pipeline still does not assign the ID based on position, because that would be a guess.

## Outputs (`output/`)

| File | Contents |
|---|---|
| `customer_360.json` | One unified profile per customer |
| `data_quality_report.json` | Summary counts, per-source counts, issue breakdown, field completeness, column mappings |
| `data_quality_issues.json` | One entry per issue: source, record number, customer, field, original value, action taken |
| `quarantine.json` | Removed records with the reason and the original values |
| `insights.json` | KPIs (Key Performance Indicators), top customers, segments, support and regional insights |

## Configuration

Everything is set in `config/pipeline_config.json`:

- `input_sources`: files to load. Mark one source as `"primary": true`. Add `xml_record_tag` for XML files.
- `column_aliases`: accepted column names for each standard field.
- `field_types`: how each field is validated (`id`, `email`, `date`, `int`, `money`, `city`, `text`).
- `mandatory_fields`: required fields for each source.
- `validation.customer_id_pattern` and `validation.email_pattern`: regular expressions used for validation.
- `validation.reference_date`: the "today" used for future-date checks and `days_since_last_order`. Set it to `null` to use the current date.
- `segmentation.method`: `fixed` uses the thresholds from the assignment. `percentile` creates tiers by rank instead (for example, top 20% Gold and next 30% Silver).
- `insights.high_ticket_threshold`, `insights.top_n_customers` and `insights.activity_days` (day limits for Active and Cooling).

To use a different config file:

```bash
python -m pipeline.run --config config/pipeline_config.json
```

## Dashboard

| Tab | Shows |
|---|---|
| Overview | KPI tiles, revenue by city, customers by segment |
| Revenue & Segments | Top 10 customers, segment summary, lifetime value distribution with segment cut-offs |
| Customer Behavior | Key findings, activity status, activity by segment, average order value by segment and city, orders vs lifetime value, registrations by quarter, downloadable win-back list |
| Support | Adjustable ticket threshold, ticket distribution, Gold customers at risk, downloadable list |
| Regional | Revenue by city, customer count by city, segment mix by city |
| Data Quality | Quality metrics, per-source counts, issue breakdown, field completeness, column mapping, quarantine, searchable issue log |
| Customer Lookup | The full Customer 360 profile and flags for any customer |

The filter bar at the top has dropdowns for city and segment, each with multiple selections. Amounts are shown in lakh (L, 1,00,000) and crore (Cr, 1,00,00,000).

## Tests

```bash
python -m pytest -v
```

The tests cover:
- Column alias matching
- All three loaders
- Number, date and email parsing
- Each data quality rule
- Segment boundaries (exactly ₹1,00,000 is Silver, ₹1,00,001 is Gold)
- Percentile tiers
- Activity status boundaries
- Two end-to-end runs: one on the provided data, and one on a synthetic dataset with renamed columns, an orphan order and a customer with no orders

## Logging

Each run writes `logs/pipeline_<timestamp>.log` and prints the same lines to the console. The log records:
- Every file loaded
- Every column renamed
- Every removed record
- Join match counts
- The final quality summary
