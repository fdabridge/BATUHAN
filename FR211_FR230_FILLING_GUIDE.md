# FR.211 & FR.230 Filling Guide

---

## Important: Stage Differences

Neither FR.211 nor FR.230 needs a structurally different template per stage.  
**You edit the same placeholders in every stage folder.** The VALUES change automatically at render time because the filler passes different stage context (different dates, different team members) to each folder's render call.

So the workflow is:
1. Edit the Stage 1 copy of each file
2. Apply the exact same edits to the Stage 2 copy
3. Apply the exact same edits to the Surveillance copy

---

## FR.211 — Lead Auditor / Auditor Assessment Form

### What this form is

FR.211 is filled **by the client organization** to rate each member of the audit team.  
- The lead auditor gets a copy (the client rates them too).  
- Each additional auditor and each technical expert gets a copy.  
- Observers do NOT get a copy.  
- It is rendered once per team member, per stage.

The team members can differ per stage — Stage 1, Stage 2, and Surveillance may have different auditors assigned. The filler loops over whoever is on that specific stage's team.

---

### Table 0 — Header (4 rows)

Edit these cells one by one:

| Row label | Cell to fill | What to type |
|---|---|---|
| Lead Auditor / Auditor | Empty cell to the right | `{{ assessed_person_name }}` |
| Audit Date(s) | Empty cell to the right | `{{ audit_dates }}` |
| Customer Organization | Empty cell to the right | `{{ company_name }}` |
| Standard(s) | Empty cell to the right | `{{ standards_str }}` |

**`assessed_person_name`** = the name of the specific person this copy of FR.211 belongs to (auditor or TE). At render time the filler loops over each team member and fills this with their name.

**`audit_dates`** = automatically resolves to the correct stage's dates (Stage 1 dates for Stage 1 copy, Stage 2 dates for Stage 2 copy, Surveillance dates for Surveillance copy).

---

### Table 1 — Rating Criteria

Do not touch. All 10 criteria rows (Attitude-Behavior, Clothing, Timely availability, etc.) and the Total / % Average rows are filled by hand on-site by the lead auditor.

Leave every cell in this table blank.

---

### Table 2 — Signature

| Cell | Action |
|---|---|
| Customer Establishment Officer | Leave blank — signed on-site |
| Signature | Leave blank — signed on-site |

---

### Which files to edit

Edit ALL of these (same changes in each):

- `9-14-45-22-5001/İlk Belgelendirme/Aşama 1/FR.211...docx`
- `9-14-45-22-5001/İlk Belgelendirme/Aşama 2/FR.211...docx`
- `9-14-45-22-5001/Gözetim/FR.211...docx`
- `13485/İlk Belgelendirme/Aşama 1/FR.211...docx`
- `13485/İlk Belgelendirme/Aşama 2/FR.211...docx`
- `13485/Gözetim/FR.211...docx`
- `27001/İlk Belgelendirme/Aşama 1/FR.211...docx`
- `27001/İlk Belgelendirme/Aşama 2/FR.211...docx`
- `27001/Gözetim/FR.211...docx`

---

## FR.230 — Nonconformity Notification Form

### What this form is

FR.230 is the nonconformity tracking sheet. It is filled entirely **by hand on-site** by the audit team during and after the audit. There is almost nothing to pre-fill — the only piece of information Certiva knows in advance is who the lead auditor is.

---

### IMPORTANT: Header fields are in the document header

To edit these, double-click the very top of the page in Word to enter Header editing mode. You will see two header tables.

**Header Table 1** — IFC GLOBAL LLC / NON-CONFORMITY NOTIFICATION FORM  
Do not touch — static branding.

**Header Table 2** — fill these cells:

| Cell label | Placeholder |
|---|---|
| Organization | `{{ company_name }}` |
| Project Number | `{{ plan_number }}` |
| Audit Type | `{{ audit_type_display }}` |
| Date | `{{ audit_date_end }}` |

`audit_date_end` = the last day of the current stage, formatted DD/MM/YYYY.  
- Stage 1 copy → last day of Stage 1  
- Stage 2 copy → last day of Stage 2  
- Surveillance copy → last day of Surveillance  

Press Escape or double-click the body to exit header editing mode.

---

### Paragraph (above the table)

Static instruction text — do not touch:
> *"This form; must be forwarded to IFC GLOBAL within 14 days after the audit..."*

---

### Table 0 — NC Tracking Table

All columns are filled by hand on-site:

| Column | Filled by |
|---|---|
| No. | Auditor on-site |
| Reference (Standard and clause no) | Auditor on-site |
| Definition of nonconformity | Auditor on-site |
| NC degree | Auditor on-site |
| Root cause | Company on-site |
| Correction | Company on-site |
| Corrective action based on root cause analysis | Company on-site |
| Evidence provided / Review result | Auditor review |
| Follow-up Y/N | Auditor on-site |
| Date reviewed | Auditor on-site |
| Reviewed by / Signature | Auditor on-site |

**Do not add any placeholders to Table 0.** Leave all 10 data rows blank.

---

### Table 1 — Signatures

| Cell | What to type |
|---|---|
| Organisation Representative / Date & Sign | Leave blank — signed on-site |
| Auditor / Sign | `{{ lead_auditor_name }}` |

The lead auditor's name is pre-filled so the company knows who to return the form to. They still sign over it on-site.

---

### Which files to edit

Edit ALL of these (same change in each — only the Auditor/Sign cell):

- `9-14-45-22-5001/İlk Belgelendirme/Aşama 1/FR.230...docx`
- `9-14-45-22-5001/İlk Belgelendirme/Aşama 2/FR.230...docx`
- `9-14-45-22-5001/Gözetim/FR.230...docx`
- `13485/İlk Belgelendirme/Aşama 1/FR.230...docx`
- `13485/İlk Belgelendirme/Aşama 2/FR.230...docx`
- `13485/Gözetim/FR.230...docx`
- `27001/İlk Belgelendirme/Aşama 1/FR.230...docx`
- `27001/İlk Belgelendirme/Aşama 2/FR.230...docx`
- `27001/Gözetim/FR.230...docx`

---

## Summary: Stage Differences

| Form | Stage 1 template | Stage 2 template | Surveillance template |
|---|---|---|---|
| FR.211 | Same placeholders | Same placeholders | Same placeholders |
| FR.230 | Same placeholders | Same placeholders | Same placeholders |

The only "differences" are in the **rendered output** (different dates, different assessed person names) — not in the template itself. The filler handles this automatically by passing the correct stage context to each render call.
