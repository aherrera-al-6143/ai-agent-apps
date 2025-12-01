# AI Agent Churn Evaluation Report

**Generated:** 2025-11-25 09:02:16

**Total Test Sequences:** 4

**Total Queries:** 6
**Success Rate:** 100.0%
**SQL Generated:** 6/6
**Expected Count Match Rate:** 0/5 (0.0%)


## query_1

**Questions:** 3

### Query 1: How many portfolios churned last month?

**Status:** ✅ Success

**Expected Count:** [84]

**Actual Rows Returned:** 1 ❌ MISMATCH

**SQL Generated:** ✅ Yes

```sql
SELECT COUNT(DISTINCT record_look_up_code) FROM "Operations | Master Property Table KPIs | PROD" WHERE (meas_mo = (SELECT MAX(meas_mo) FROM "Operations | Master Property Table KPIs | PROD")) AND (prop_type_new = 'Loss') AND (meas_mo = DATE_TRUNC('month', CURRENT_DATE - INTERVAL '1 month'))
```

**Data Sample (first 5 rows):**

```json
[
  [
    "record_look_up_code"
  ],
  [
    0
  ]
]
```

**Agent Response:**

There were 0 portfolios that churned last month.

**Execution Time:** 10863ms

---

### Query 2: What are the names of those portfolios?

**Status:** ✅ Success

**Expected Count:** [84]

**Actual Rows Returned:** 0 ❌ MISMATCH

**Expected Answer:** ['Across the Street', 'Alley South Lake Union', 'Allina La Jolla', 'Ansley Murray Hill', 'Arbors, The', 'Arioso', 'Avery At Moorpark']

**Notes:** answer list is truncated

**SQL Generated:** ✅ Yes

```sql
SELECT record_property_name FROM "Operations | Master Property Table KPIs | PROD" WHERE (meas_mo = DATE_TRUNC('month', CURRENT_DATE - INTERVAL '1 month')) AND (prop_type_new ILIKE '%Loss%')
```

**Agent Response:**

There were no portfolios that churned last month, so there are no names to display.

**Execution Time:** 10727ms

---

### Query 3: Which corporate office had the most churn?

**Status:** ✅ Success

**Rows Returned:** 1

**Expected Answer:** West

**SQL Generated:** ✅ Yes

```sql
SELECT record_corporate_operating_office, COUNT(*) AS churn_count FROM "Operations | PDB Property Table | PROD" WHERE (record_loss_reason ILIKE '%Other%') GROUP BY record_corporate_operating_office ORDER BY churn_count DESC LIMIT 1
```

**Data Sample (first 5 rows):**

```json
[
  [
    "record_corporate_operating_office"
  ],
  [
    "Atlanta West",
    76
  ]
]
```

**Agent Response:**

The corporate office with the most churn is Atlanta West, with 76 churned portfolios.

**Execution Time:** 12423ms

---


## query_2

**Questions:** 1

### Query 1: What's the count of the portfolios that churned in August 2025?

**Status:** ✅ Success

**Expected Count:** [58]

**Actual Rows Returned:** 1 ❌ MISMATCH

**SQL Generated:** ✅ Yes

```sql
SELECT COUNT(DISTINCT record_look_up_code) FROM "Operations | Master Property Table KPIs | PROD" WHERE (record_termination_date BETWEEN '2025-08-01' AND '2025-08-31')
```

**Data Sample (first 5 rows):**

```json
[
  [
    "record_look_up_code"
  ],
  [
    58
  ]
]
```

**Agent Response:**

There were 58 portfolios that churned in August 2025.

**Execution Time:** 9793ms

---


## query_3

**Questions:** 1

### Query 1: Total count of properties that were lost in September 2025?

**Status:** ✅ Success

**Expected Count:** [60]

**Actual Rows Returned:** 1 ❌ MISMATCH

**SQL Generated:** ✅ Yes

```sql
SELECT COUNT(DISTINCT record_look_up_code) FROM "Operations | Master Property Table KPIs | PROD" WHERE (EXTRACT(MONTH FROM record_pending_loss_date) = 9) AND (EXTRACT(YEAR FROM record_pending_loss_date) = 2025)
```

**Data Sample (first 5 rows):**

```json
[
  [
    "record_look_up_code"
  ],
  [
    58
  ]
]
```

**Agent Response:**

There were 58 properties lost in September 2025.

**Execution Time:** 9528ms

---


## query_4

**Questions:** 1

### Query 1: What is the year-over-year change in October churn?

**Status:** ✅ Success

**Expected Count:** [0.47]

**Actual Rows Returned:** 4 ❌ MISMATCH

**Notes:** 47.4% increase in churn or 27 more portfolios lost

**SQL Generated:** ✅ Yes

```sql
SELECT meas_year, meas_month, COUNT(DISTINCT record_look_up_code) AS churned_properties FROM "Operations | Master Property Table KPIs | PROD" WHERE (meas_month = 10) AND (record_loss_reason IS NOT NULL) GROUP BY meas_year, meas_month ORDER BY meas_year ASC
```

**Data Sample (first 5 rows):**

```json
[
  [
    "meas_month",
    "meas_mo",
    "record_look_up_code",
    "meas_year"
  ],
  [
    2022,
    10,
    605
  ],
  [
    2023,
    10,
    664
  ],
  [
    2024,
    10,
    526
  ],
  [
    2025,
    10,
    96
  ]
]
```

**Agent Response:**

Here's the year-over-year change in October churn:

*   **2022 to 2023:** Churn increased from 605 to 664, a change of 59.
*   **2023 to 2024:** Churn decreased from 664 to 526, a change of -138.
*   **2024 to 2025:** Churn decreased from 526 to 96, a change of -430.

**Execution Time:** 8980ms

---