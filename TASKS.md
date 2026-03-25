# BATUHAN Bug Fix Tasks

## Task 1 — Step A parser heading mismatch [DONE]
In `prompt_a.txt`, explicitly instruct Claude to use these exact section headings with no numbering or prefix: `Company Overview`, `Scope of Activities`, `Documented Information Identified`, `Key Processes and Functions`, `Evidence of System Implementation`, `Audit-Relevant Records`, `Identified Gaps or Unclear Areas`. Then in the Step A output parser, add fuzzy case-insensitive substring matching so variations like `COMPANY INFORMATION` still map to `Company Overview`.

## Task 2 — Organisation Information shows wrong company [DONE]
The report shows IFC Global LLC's name, address and phone in the Organisation Information block and site table instead of the auditee's details. The assembly step is pulling from the template header instead of the job's input data. Fix so organisation name, address, and phone always come from the job's submitted data.

## Task 3 — Audit Objectives cell is being wiped [DONE]
The a/b/c/d audit objectives text disappears from the output. The `strip_template_instruction_cells()` regex is too broad and is clearing the Audit Objectives cell along with the food boilerplate. Fix the regex to only strip cells containing the food instruction text and never touch legitimate audit objectives content.

## Task 4 — 8.3 N/A justification is factually wrong [DONE]
When 8.3 is in the N/A table the generated justification sometimes says the organisation has an active design and development process — the opposite of why it is excluded. Fix `prompt_b.txt` so the N/A justification always explains why the clause does not apply.

## Task 5 — Recommendation checkbox renders as plain text [DONE]
The recommendation checkbox is not being ticked — it renders as plain text. Check whether the template uses a content control checkbox, legacy form field, or Unicode character, log which type is detected, and fix the correct branch in `_tick_checkbox_cell()`.

