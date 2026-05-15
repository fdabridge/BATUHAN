Now I have everything. Let me also check what the EnMS complexity formula looks like and get the Stage 1/Stage 2 split for EnMS.Now I have everything. Let me write the complete prompt.

---

Build a new page inside BATUHAN called **Audit Time Calculator**. This is a completely standalone tool — it does not interact with the report pipeline in any way.

**Concept:** User uploads one or more files (certification application form + any additional forms for EnMS/ISMS). Claude reads all files, extracts all required data, classifies the sector, runs the full calculation, and displays a detailed breakdown. No manual input fields whatsoever.

**Accepted formats:** PDF and Word (.docx). Use the existing document parsing pipelines already in the codebase.

**Create tasks before starting. Build one task at a time.**

---

## PART 1 — WHAT CLAUDE EXTRACTS FROM THE FORM

From the standard certification application form (FR.217):
- Organisation name
- Selected standards (ISO 9001, 14001, 45001, 22000, 27001, 50001, 13485, 37001)
- Audit type (Initial Certification / Transfer / Scope Extension / Recertification)
- Scope of certification (free text description)
- Total employees, office employees, repetitive-role employees, subcontractors, seasonal
- Shift information and employees per shift
- Site addresses with process description and employee count per site
- ISO 22000: Number of HACCP studies
- Integration level: count of ticked yes/no checkboxes on page 3 (8 questions total)

From the EnMS additional form (when ISO 50001 is selected):
- Annual energy consumption in TJ
- Number of energy types
- Number of Significant Energy Uses (SEUs)

For ISO 27001: Uses same employee data from the main form. Repetitive-role reduction uses the **square root method** (not the percentage table) — square root of the repetitive workers group, rounded up.

---

## PART 2 — EFFECTIVE EMPLOYEE COUNT

For ISO 9001, 14001, 45001, 13485 (percentage table method):
1. Part-time → FTE: (hours worked per day ÷ 8) × headcount
2. Repetitive-role workers: multiply by the applicable rate based on risk/complexity category:
   - High: 20%
   - Medium: 15%
   - Low: 10%
   - Limited: 5%
3. Add office employees (full count always)
4. Result = EPS (round up)

For ISO 27001 (square root method):
- Take square root of repetitive-role group, round up to next integer
- Add office and other employees
- Result = effective persons count

For ISO 50001:
- All personnel affecting energy performance (management, energy team, SEU operators, maintenance)
- Part-time → FTE conversion same as above
- No repetitive-role reduction for EnMS

---

## PART 3 — LOOKUP TABLES (hardcode all of these exactly)

### ISO 9001 — Risk Categories (Table 1)
**High Risk:** Sectors 1 (Fishing), 2 (Mining/quarrying), 3 (Food/beverages/tobacco), 10 (Coke/petroleum), 11 (Nuclear fuel), 12 (Chemicals), 13 (Pharmaceuticals), 14 (Rubber/plastics), 16 (Concrete/cement/lime), 18 (Machinery/equipment), 19 (Electrical equipment), 20 (Shipbuilding), 21 (Space), 24 (Recovery/recycling), 25 (Electricity supply), 26 (Gas supply), 28 (Complex construction, load-bearing), 38 (Health/social)

**Medium Risk:** Sectors 1 (Agriculture), 6 (Wood products), 9 (Printing), 15 (Non-metallic minerals), 17 (Basic metals), 19 (Optical equipment), 22 (Vehicles), 23 (Other unclassified industrial), 27 (Water supply), 28 (Simple construction, non-load-bearing), 31 (Transport/storage/communication), 34 (Engineering services), 36 (Public administration), 39 (Entertainment/personal services)

**Low Risk:** Sectors 4 (Textiles/clothing), 5 (Leather), 7 (Pulp/paper), 8 (Publishing), 29 (Wholesale/retail trade), 30 (Hotels/restaurants), 32 (Financial/real estate/leasing), 33 (IT products), 35 (Office services), 37 (Education)

### ISO 9001 — Audit Time Tables (Initial: Total + Phase 1 + Phase 2 | Surveillance: Total | Recertification: Total + Phase 1 + Phase 2)

**HIGH RISK:**
```
EPS        Init.Total  Ph1   Ph2    Surv  Recert.Total  RPh1  RPh2
1-5        2.0        0.5   1.5    1.0   1.5           0.5   1.0
6-10       2.5        1.0   1.5    1.0   1.5           0.5   1.0
11-15      3.0        1.0   2.0    1.0   2.0           0.5   1.5
16-25      4.0        1.5   2.5    1.5   2.5           1.0   1.5
26-45      5.0        1.5   3.5    1.5   3.5           1.0   2.5
46-65      6.0        2.0   4.0    2.0   4.0           1.5   2.5
66-85      7.0        2.5   4.5    2.5   4.5           1.5   3.0
86-125     8.0        2.5   5.5    2.5   5.5           2.0   3.5
126-175    9.0        3.0   6.0    3.0   6.0           2.0   4.0
176-275    10.0       3.5   6.5    3.5   6.5           2.0   4.5
276-425    11.0       4.0   7.0    4.0   7.0           2.5   4.5
426-625    12.0       4.0   8.0    4.0   8.0           2.5   5.5
626-875    13.0       4.5   8.5    4.5   8.5           3.0   5.5
876-1175   14.0       4.5   9.5    4.5   9.5           3.0   6.5
1176-1550  15.0       5.0   10.0   5.0   10.0          3.5   6.5
1551-2025  16.0       5.5   10.5   5.5   10.5          3.5   7.0
2026-2675  17.0       6.0   11.0   6.0   11.0          4.0   7.0
2676-3450  18.0       6.0   12.0   6.0   12.0          4.0   8.0
3451-4350  19.0       6.5   12.5   6.5   12.5          4.0   8.5
4351-5450  20.0       6.5   13.5   6.5   13.5          4.5   9.0
5451-6800  21.0       7.0   14.0   7.0   14.0          4.5   9.5
6801-8500  22.0       7.0   15.0   7.0   15.0          5.0   10.0
8501-10700 23.0       7.5   15.5   7.5   15.5          5.0   10.5
```

**MEDIUM RISK:**
```
EPS        Init.Total  Ph1   Ph2    Surv  Recert.Total  RPh1  RPh2
1-5        1.5        0.5   1.0    1.0   1.0           0.5   0.5
6-10       2.0        0.5   1.5    1.0   1.5           0.5   1.0
11-15      2.5        1.0   1.5    1.0   1.5           0.5   1.0
16-25      3.0        1.0   2.0    1.0   2.0           0.5   1.5
26-45      4.0        1.5   2.5    1.5   2.5           1.0   1.5
46-65      5.0        1.5   3.5    1.5   3.5           1.0   2.5
66-85      6.0        2.0   4.0    2.0   4.0           1.5   2.5
86-125     7.0        2.5   4.5    2.5   4.5           1.5   3.0
126-175    8.0        2.5   5.5    2.5   5.5           2.0   3.5
176-275    9.0        3.0   6.0    3.0   6.0           2.0   4.0
276-425    10.0       3.5   6.5    3.5   6.5           2.0   4.5
426-625    11.0       4.0   7.0    4.0   7.0           2.5   4.5
626-875    12.0       4.0   8.0    4.0   8.0           2.5   5.5
876-1175   13.0       4.5   8.5    4.5   8.5           3.0   5.5
1176-1550  14.0       4.5   9.5    4.5   9.5           3.0   6.5
1551-2025  15.0       5.0   10.0   5.0   10.0          3.5   6.5
2026-2675  16.0       5.5   10.5   5.5   10.5          3.5   7.0
2676-3450  17.0       6.0   11.0   6.0   11.0          4.0   7.0
3451-4350  18.0       6.0   12.0   6.0   12.0          4.0   8.0
4351-5450  19.0       6.5   12.5   6.5   12.5          4.0   8.5
5451-6800  20.0       6.5   13.5   6.5   13.5          4.5   9.0
6801-8500  21.0       7.0   14.0   7.0   14.0          4.5   9.5
8501-10700 22.0       7.0   15.0   7.0   15.0          5.0   10.0
```

**LOW RISK:**
```
EPS        Init.Total  Ph1   Ph2    Surv  Recert.Total  RPh1  RPh2
1-5        1.0        0.5   0.5    1.0   1.0           0.5   0.5
6-10       1.5        0.5   1.0    1.0   1.0           0.5   0.5
11-15      2.0        0.5   1.5    1.0   1.5           0.5   1.0
16-25      2.5        1.0   1.5    1.0   1.5           0.5   1.0
26-45      3.0        1.0   2.0    1.0   2.0           0.5   1.5
46-65      4.0        1.5   2.5    1.5   2.5           1.0   1.5
66-85      5.0        1.5   3.5    1.5   3.5           1.0   2.5
86-125     6.0        2.0   4.0    2.0   4.0           1.5   2.5
126-175    7.0        2.5   4.5    2.5   4.5           1.5   3.0
176-275    8.0        2.5   5.5    2.5   5.5           2.0   3.5
276-425    9.0        3.0   6.0    3.0   6.0           2.0   4.0
426-625    10.0       3.5   6.5    3.5   6.5           2.0   4.5
626-875    11.0       4.0   7.0    4.0   7.0           2.5   4.5
876-1175   12.0       4.0   8.0    4.0   8.0           2.5   5.5
1176-1550  13.0       4.5   8.5    4.5   8.5           3.0   5.5
1551-2025  14.0       4.5   9.5    4.5   9.5           3.0   6.5
2026-2675  15.0       5.0   10.0   5.0   10.0          3.5   6.5
2676-3450  16.0       5.5   10.5   5.5   10.5          3.5   7.0
3451-4350  17.0       6.0   11.0   6.0   11.0          4.0   7.0
4351-5450  18.0       6.0   12.0   6.0   12.0          4.0   8.0
5451-6800  19.0       6.5   12.5   6.5   12.5          4.0   8.5
6801-8500  20.0       6.5   13.5   6.5   13.5          4.5   9.0
8501-10700 21.0       7.0   14.0   7.0   14.0          4.5   9.5
```

### ISO 14001 — Complexity Categories (Table 2)
**High:** Sectors 2, 4 (tanning), 5, 7 (pulp), 9, 10, 12, 13, 15 (non-metal), 16, 17 (primary metals), 20, 25 (coal electricity), 26, 28, 39 (hazardous waste/wastewater)
**Medium:** Sectors 1, 3, 4 (excl. tanning), 6, 7 (paper excl. pulp), 15 (glass/clay), 17 (surface treatment), 18, 19, 22, 24, 25 (non-coal), 26 (gas), 27, 29, 30 (excl. hotels), 31, 34, 35 (cleaning), 38
**Low:** Sectors 6 (excl. impregnation), 7 (paper products excl. pulp/printing), 8, 14, 17 (hot/cold forming), 18 (assemblies), 19 (electrical assembly), 29, 30, 33, 39
**Limited:** Sectors 31 (management services no equipment), 32, 35 (company HQ/holding), 37

### ISO 14001 — Audit Time Tables (Init.Total + Ph1 + Ph2 | Surv.Total | Recert.Total + Ph1 + Ph2)

**HIGH COMPLEXITY:**
```
EPS        Init   Ph1    Ph2    Surv   Recert  RPh1   RPh2
1-5        3.0    1.0    2.0    1.0    2.0     1.0    1.0
6-10       3.5    1.0    2.5    1.0    2.5     1.0    1.5
11-15      4.5    1.5    3.0    1.5    3.0     1.0    2.0
16-25      5.5    2.0    3.5    2.0    3.5     1.0    2.0
26-45      7.0    2.5    4.5    2.5    4.5     1.0    3.5
46-65      8.0    3.0    5.0    3.0    5.0     2.0    3.0
66-85      9.0    3.0    6.0    3.0    6.0     2.0    4.0
86-125     11.0   4.0    7.0    4.0    7.0     2.0    5.0
126-175    12.0   4.0    8.0    4.0    8.0     3.0    5.0
176-275    13.0   4.5    8.5    4.5    8.5     3.0    5.5
276-425    15.0   5.0    10.0   5.0    10.0    3.5    6.5
426-625    16.0   5.5    10.5   5.5    10.5    3.0    7.5
626-875    17.0   6.0    11.0   6.0    11.0    4.0    7.0
876-1175   19.0   6.5    12.5   6.5    12.5    4.0    8.5
1176-1550  20.0   6.5    13.5   6.5    13.5    4.5    9.0
1551-2025  21.0   7.0    14.0   7.0    14.0    5.0    9.0
2026-2675  23.0   8.0    15.0   8.0    15.0    5.0    10.0
2676-3450  25.0   8.5    16.5   8.5    16.5    5.5    11.0
3451-4350  27.0   9.0    18.0   9.0    18.0    6.0    12.0
4351-5450  28.0   9.5    18.5   9.5    18.5    5.5    13.0
5451-6800  30.0   10.0   20.0   10.0   20.0    7.0    13.0
6801-8500  32.0   11.0   21.0   11.0   21.0    7.0    14.0
8501-10700 34.0   11.5   22.5   11.5   22.5    7.0    15.5
```

**MEDIUM COMPLEXITY:**
```
EPS        Init   Ph1    Ph2    Surv   Recert  RPh1   RPh2
1-5        2.5    1.0    1.5    1.0    1.5     0.5    1.0
6-10       3.0    1.0    2.0    1.0    2.0     0.5    1.5
11-15      3.5    1.0    2.5    1.0    2.5     1.0    1.5
16-25      4.5    1.5    3.0    1.5    3.0     1.0    2.0
26-45      5.5    2.0    3.5    2.0    3.5     1.5    2.0
46-65      6.0    2.0    4.0    2.0    4.0     1.0    3.0
66-85      7.0    2.5    4.5    2.5    4.5     1.5    3.0
86-125     8.0    2.5    5.5    2.5    5.5     2.0    3.5
126-175    9.0    3.0    6.0    3.0    6.0     2.0    4.0
176-275    10.0   3.5    6.5    3.5    6.5     2.0    4.5
276-425    11.0   3.5    7.5    3.5    7.5     2.5    5.0
426-625    12.0   4.0    8.0    4.0    8.0     2.5    5.5
626-875    13.0   4.5    8.5    4.5    8.5     2.5    6.0
876-1175   15.0   5.0    10.0   5.0    10.0    3.5    6.5
1176-1550  16.0   5.5    10.5   5.5    10.5    3.5    7.0
1551-2025  17.0   5.5    11.5   5.5    11.5    4.0    7.5
2026-2675  18.0   6.0    12.0   6.0    12.0    4.0    8.0
2676-3450  19.0   6.5    12.5   6.5    12.5    4.0    8.5
3451-4350  20.0   6.5    13.5   6.5    13.5    4.5    9.0
4351-5450  21.0   7.0    14.0   7.0    14.0    4.5    9.5
5451-6800  23.0   7.5    15.5   7.5    15.5    5.5    10.0
6801-8500  25.0   8.5    16.5   8.5    16.5    5.5    11.0
8501-10700 27.0   9.0    18.0   9.0    18.0    6.0    12.0
```

**LOW COMPLEXITY:**
```
EPS        Init   Ph1    Ph2    Surv   Recert  RPh1   RPh2
1-5        2.5    1.0    1.5    1.0    1.5     0.5    1.0
6-10       3.0    1.0    2.0    1.0    2.0     0.5    1.5
11-15      3.0    1.0    2.0    1.0    2.0     0.5    1.5
16-25      3.5    1.0    2.5    1.0    2.5     1.0    1.5
26-45      4.0    1.5    2.5    1.5    2.5     0.5    2.0
46-65      4.5    1.5    3.0    1.5    3.0     1.0    2.0
66-85      5.0    1.5    3.5    1.5    3.5     1.5    2.0
86-125     5.5    2.0    3.5    2.0    3.5     1.5    2.0
126-175    6.0    2.0    4.0    2.0    4.0     1.5    2.5
176-275    7.0    2.5    4.5    2.5    4.5     1.5    3.0
276-425    8.0    2.5    5.5    2.5    5.5     2.0    3.5
426-625    9.0    3.0    6.0    3.0    6.0     2.0    4.0
626-875    10.0   3.5    6.5    3.5    6.5     2.0    4.5
876-1175   11.0   3.5    7.5    3.5    7.5     2.5    5.0
1176-1550  12.0   4.0    8.0    4.0    8.0     2.5    5.5
1551-2025  12.0   4.0    8.0    4.0    8.0     2.5    5.5
2026-2675  13.0   4.5    8.5    4.5    8.5     2.5    6.0
2676-3450  14.0   4.5    9.5    4.5    9.5     3.0    6.5
3451-4350  15.0   5.0    10.0   5.0    10.0    3.5    6.5
4351-5450  16.0   5.5    10.5   5.5    10.5    3.5    7.0
5451-6800  17.0   5.5    11.5   5.5    11.5    4.0    7.5
6801-8500  19.0   6.5    12.5   6.5    12.5    4.0    8.5
8501-10700 20.0   6.5    13.5   6.5    13.5    4.5    9.0
```

**LIMITED COMPLEXITY:**
```
EPS        Init   Ph1    Ph2    Surv   Recert  RPh1   RPh2
1-5        2.5    1.0    1.5    1.0    1.5     0.5    1.0
6-10       3.0    1.0    2.0    1.0    2.0     0.5    1.5
11-15      3.0    1.0    2.0    1.0    2.0     0.5    1.5
16-25      3.0    1.0    2.0    1.0    2.0     0.5    1.5
26-45      3.0    1.0    2.0    1.0    2.0     0.5    1.5
46-65      3.5    1.0    2.5    1.0    2.5     1.0    2.5
66-85      3.5    1.0    2.5    1.0    2.5     1.0    2.5
86-125     4.0    1.5    2.5    1.5    2.5     1.0    2.5
126-175    4.5    1.5    3.0    1.5    3.0     1.0    2.0
176-275    5.0    1.5    3.5    1.5    3.5     1.0    2.5
276-425    5.5    1.5    4.0    1.5    4.0     1.5    2.5
426-625    6.0    2.0    4.0    2.0    4.0     1.5    2.5
626-875    6.5    2.0    4.5    2.0    4.5     1.5    3.0
876-1175   7.0    2.5    4.5    2.5    4.5     1.5    3.0
1176-1550  7.5    2.5    5.0    2.5    5.0     1.5    3.5
1551-2025  8.0    2.5    5.5    2.5    5.5     3.5    6.5
2026-2675  8.5    3.0    5.5    3.0    5.5     3.5    7.0
2676-3450  9.0    3.0    6.0    3.0    6.0     2.0    4.0
3451-4350  10.0   3.5    6.5    3.5    6.5     2.0    4.5
4351-5450  11.0   3.5    7.5    3.5    7.5     2.5    5.0
5451-6800  12.0   4.0    8.0    4.0    8.0     2.5    5.5
6801-8500  13.0   4.5    8.5    4.5    8.5     3.0    5.5
8501-10700 14.0   4.5    9.5    4.5    9.5     3.0    6.5
```

### ISO 45001 — Same Complexity Categories as ISO 14001 (Table 3), Same Time Tables as ISO 14001

### ISO 13485 — Simple Total Table (no phase split in table — apply 1/3 Ph1, 2/3 Ph2 ratio)
```
EPS         Total (Init)    EPS          Total (Init)
1-5         3.0             626-875      15.0
6-10        4.0             876-1175     16.0
11-15       4.5             1176-1550    17.0
16-25       5.0             1551-2025    18.0
26-45       6.0             2026-2675    19.0
46-65       7.0             2676-3450    20.0
66-85       8.0             3451-4350    21.0
86-125      10.0            4351-5450    22.0
126-175     11.0            5451-6800    23.0
176-275     12.0            6801-8500    24.0
276-425     13.0            8501-10700   25.0
426-625     14.0
```
Surveillance = 1/3 of initial total, min 1 day. Recertification = 2/3 of initial total, min 1 day.

### ISO 27001 — ISMS Table T.1 (Initial only — Phase 1 + Phase 2 pre-split. Surv = 1/3 of total. Recert = 2/3 of total.)
```
EPS         Total    Ph1    Ph2
1-10        5.0      1.5    3.5
11-15       6.0      2.0    4.0
16-25       7.0      2.5    4.5
26-45       8.5      3.0    5.5
46-65       10.0     3.5    6.5
66-85       11.0     3.5    7.5
86-125      12.0     4.0    8.0
126-175     13.0     4.5    8.5
176-275     14.0     4.5    9.0
276-425     15.0     5.0    10.0
426-625     16.5     5.5    11.0
626-875     17.5     6.0    11.5
876-1175    18.5     6.0    12.5
1176-1550   19.5     6.5    13.0
1551-2025   21.0     7.0    14.0
2026-2675   22.0     7.5    14.5
2676-3450   23.0     7.5    15.5
3451-4350   24.0     8.0    16.0
4351-5450   25.0     8.5    16.5
5451-6800   26.0     8.5    17.5
6801-8500   27.0     9.0    18.0
8501-10700  28.0     9.5    18.5
```
Note: ISO 27001 on-site time floor is 70% (not 80% like other standards). Surveillance and Recertification use 1/3 and 2/3 of initial total respectively.

### ISO 50001 — EnMS (Formula-based)

**Step 1 — Complexity formula:**
K = (0.25 × FEC) + (0.25 × NET) + (0.50 × FSEU)

FEC (annual energy consumption):
- ≤20 TJ → 1.0
- 20–200 TJ → 1.2
- 200–2000 TJ → 1.4
- >2000 TJ → 1.6

NET (number of energy types):
- 1–2 types → 1.0
- 3 types → 1.2
- ≥4 types → 1.4

FSEU (number of Significant Energy Uses covering 80% consumption):
- 1–3 → 1.0
- 4–6 → 1.2
- 7–10 → 1.3
- 11–15 → 1.4
- ≥16 → 1.6

Complexity level: K > 1.35 = High | 1.15–1.35 = Medium | < 1.15 = Low

**Step 2 — Table A.3 (Initial certification, Stage 1 + Stage 2 combined — apply 1/3 Ph1, 2/3 Ph2):**
```
EPS       Low    Medium   High
1-8       2.5    4.0      5.0
9-15      4.0    6.0      7.0
16-25     5.0    7.0      9.0
26-65     6.5    8.0      10.0
66-85     8.0    9.5      11.5
86-175    8.5    11.0     12.0
176-275   9.0    11.5     12.5
276-425   10.0   13.0     15.0
```

**Step 3 — Table A.4 (Surveillance and Recertification — separate table):**
```
EPS       Surv.Low  Recert.Low  Surv.Med  Recert.Med  Surv.High  Recert.High
1-8       1.0       1.5         1.0        2.5         1.5        3.0
9-15      1.0       2.5         2.0        4.0         2.5        5.0
16-25     2.0       3.5         2.5        5.0         3.0        6.0
26-65     2.5       5.0         3.0        6.0         3.5        7.0
66-85     2.5       6.0         3.5        7.0         3.5        8.5
86-175    2.5       6.0         3.5        7.0         3.5        8.5
176-275   3.0       6.0         4.0        8.0         4.0        9.5
276-425   3.5       7.0         4.0        8.5         5.0        11.0
```

---

## PART 4 — CALCULATION STEPS

Execute in this exact order for each selected standard independently, then combine if integrated:

1. **EPS** — Calculate effective employee count per standard's method
2. **Base time** — Look up total from the appropriate table using EPS + category
3. **Multiple sites** — If additional sites: calculate each site's time based on its own EPS, divide by 2, add to HQ total
4. **Integration reduction** — If 2 or more standards selected: subtract 20% from the combined total (sum of all standards' base times). Calculate this 20% from the pre-deduction sum.
5. **Reporting deduction** — Always subtract 20% from the pre-deduction sum (Step 3 result). Both deductions calculated from the same base independently.
6. **Final total** = Step 3 sum − Step 4 − Step 5
7. **Rounding** — x.1–x.2 → round down; x.3–x.7 → round to x.5; x.8–x.9 → round up
8. **Derive all audit outputs** — Look up or calculate Phase 1 and Phase 2 from the pre-split table values where available. For standards without pre-split tables (13485, 50001), apply 1/3 Ph1, 2/3 Ph2. Apply same deduction ratio proportionally across Ph1/Ph2/Surv/Recert.

Minimum floors after rounding:
- Surveillance 1: minimum 1.0 day
- Surveillance 2: minimum 1.0 day
- Recertification: minimum 1.0 day

---

## PART 5 — OUTPUT DISPLAY

```
Organisation: [name]
Standards: [list]
Scope: [as written on form]

── SECTOR CLASSIFICATION ──────────────────────────
ISO 9001: [sector name] → [Low / Medium / High] risk
ISO 14001: [sector name] → [complexity level]
(etc. for each standard)

── EMPLOYEE CALCULATION ───────────────────────────
Total employees: X
Office employees: X (full count)
Repetitive-role employees: X → effective: X ([rate]% of X)
Part-time: X → FTE: X
Effective Employee Count (EPS): X

── AUDIT TIME CALCULATION ─────────────────────────
ISO 9001 base time ([category], [EPS]):     X.X days
ISO 14001 base time ([category], [EPS]):    X.X days
(etc.)
                                           ─────────
Combined base total:                        X.X days
Integration reduction (20%):              − X.X days  [or: N/A — single standard]
Reporting deduction (20%):                − X.X days  [always applied]
                                           ─────────
Final audit time:                           X.X days

── RESULTS ────────────────────────────────────────
INITIAL CERTIFICATION
  Stage 1:                                  X.X days
  Stage 2:                                  X.X days

SURVEILLANCE
  Surveillance 1:                           X.X days
  Surveillance 2:                           X.X days

RECERTIFICATION:                            X.X days
───────────────────────────────────────────────────
```

---

## PART 6 — IMPLEMENTATION NOTES

- Use the existing Claude API pattern in the codebase for document reading and classification
- Parse PDFs using the existing extraction pipeline; parse .docx using python-docx
- This page is synchronous — no job queue, no Redis, result shown immediately
- Keep the UI consistent with BATUHAN's existing design
- Claude's system prompt for this tool must include all sector classification tables hardcoded so Claude never guesses sectors
- If ISO 50001 is selected but no EnMS additional form is uploaded, show a message asking the user to upload the additional form — do not proceed without the energy data
- Create tasks before starting. Build one task at a time. Commit after each task.

---