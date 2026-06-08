# What we are trying to do and what is failing

## The goal

Each ISO standard has its own way of classifying scope. Not all standards use EA codes. Specifically:

- ISO 22000 and FSSC 22000 use food chain categories — codes like CI, CII, CIV, I, G, etc. These tell you what part of the food industry the auditor is qualified to audit (meat processing, confectionery, packaging, etc.)
- ISO 13485 uses medical device technical areas — codes like A1.1, A1.2, A1.3 etc.
- ISO 50001 uses energy complexity — Low, Medium, or High
- ISO 37001 and ISO 37301 use sector type — Public, Private, or Third sector/NGO
- ISO 9001, ISO 14001, ISO 45001, ISO 27001 use IAF EA codes (EA 1 through EA 39)

When we look at an auditor's profile, we want to see this information displayed on each standard's card. For example, Seung Kyu HAN's ISO 22000 card should show amber-colored tags like "CI", "CIV", "I" because he has documented experience in processed meats, confectionery/snacks, and food packaging. His ISO 37001 card should show "Private" because his experience is in commercial food companies.

When adding or editing an auditor, the form for each standard should show the right input for that standard — not the same EA codes text box for everything.

## What is currently happening

Every standard — including ISO 22000, FSSC 22000, ISO 13485, ISO 37001, ISO 37301, ISO 50001 — shows an EA codes text input in the add/edit form. This is wrong. These standards do not use EA codes at all.

On the auditor profile page, the ISO 22000, FSSC 22000, ISO 37001, ISO 37301, and ISO 50001 qualification cards show nothing except the role, accreditation body, and years of experience. None of the scope categories are displayed, even though this data exists in the database under a field called `scope_category`.

## What needs to change

### In the add auditor modal and the edit form on the auditor detail page

For each qualification row, instead of always showing an EA codes text box, show the right input based on the standard:

- ISO 22000 and FSSC 22000: show a set of clickable buttons for food chain categories. The user should be able to click multiple. The categories are: BIII, C0, CI, CII, CIII, CIV, D, E, FI, FII, G, I, K. Selected ones should highlight in amber/orange. This selection should save to the `scope_category` field, not `ea_codes`.

- ISO 13485: show clickable buttons for technical areas: A1.1, A1.2, A1.3, A1.4, A1.5, A1.6, A1.7, A2.1, A2.2, A2.3, A2.4. Selected ones highlight in purple. Saves to `scope_category`.

- ISO 50001: show a dropdown with Low / Medium / High. Saves to `scope_category`. Also keep an EA codes text box because ISO 50001 does use EA codes alongside the complexity level.

- ISO 37001 and ISO 37301: show a dropdown with Public / Private / Third sector/NGO. Saves to `scope_category`. No EA codes for these.

- ISO 9001, ISO 14001, ISO 45001: keep the EA codes text box. Also add a small dropdown for risk category — High, Medium, or Low (ISO 14001 also has Limited). Saves to `scope_category`.

- ISO 27001: keep the EA codes text box only. No scope_category needed.

### On the auditor detail page, in the read-only qualification cards

Show the `scope_category` data using the right visual style for each standard:

- ISO 22000 / FSSC 22000: show each food chain category code as a small amber/orange tag
- ISO 13485: show each technical area as a small purple tag
- ISO 37001 / ISO 37301: show the sector type as a small blue tag
- ISO 50001: show the complexity level (Low/Medium/High) as a colored badge
- ISO 9001 / 14001 / 45001: show the risk category badge plus the EA code chips (already working for EA codes)

The data is already in the database. The display just needs to read `scope_category` and render it appropriately for each standard type.
