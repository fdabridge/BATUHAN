# Augment Prompt — AI Generation of Non-Applicable Clauses (NAC)

## Background

ISO standards have certain clauses that may be "not applicable" to a specific organization depending on their scope of activities. For example:
- **ISO 9001:2015 clause 8.3** (Design and Development) is N/A for organizations that produce to external customer specifications and do not design products themselves
- **ISO 9001:2015 clause 8.5.4** (Preservation) may be limited or N/A for pure service organizations  
- **ISO 14001:2015 clause 8.2** (Emergency Preparedness) may be limited for office-only organizations
- **ISO 45001:2018 clause 8.1.4.1** (Elimination of hazards) may have limited applicability in certain contexts

IAF/UAF rules require that N/A clauses be justified and documented. The certification body must verify the justification during Stage 1.

The `non_applicable_clauses` field in the database stores these as a free text string (e.g., "8.3: Organization produces to customer specifications; 7.1.5.2: No calibrated measurement equipment used").

## What to Build

### 1. New API endpoint: `POST /audit-sets/{id}/generate-nac`

In `backend/audit_set/router.py` (or wherever audit set routes are):

```python
@router.post("/{audit_set_id}/generate-nac")
async def generate_nac(audit_set_id: str, db: Session = Depends(get_db)):
    """AI-generates suggested non-applicable clauses based on scope + standards."""
    audit_set = get_audit_set(db, audit_set_id)
    if not audit_set:
        raise HTTPException(404, "Audit set not found")
    
    result = await _generate_nac_ai(audit_set)
    
    # Save to DB
    audit_set.non_applicable_clauses = result["nac_text"]
    db.commit()
    
    return {"non_applicable_clauses": result["nac_text"], "suggestions": result["suggestions"]}
```

### 2. AI generation function

In `backend/audit_set/service.py` (or a new `backend/audit_set/nac_generator.py`):

```python
import anthropic
from config.settings import get_settings

_STANDARD_CLAUSES = {
    "ISO 9001:2015": {
        "7.1.5": "Monitoring and Measuring Resources",
        "7.1.5.2": "Measurement Traceability",
        "8.3": "Design and Development of Products and Services",
        "8.4": "Control of Externally Provided Processes, Products and Services",
        "8.5.4": "Preservation",
        "8.5.5": "Post-Delivery Activities",
        "8.5.6": "Control of Changes",
    },
    "ISO 14001:2015": {
        "8.2": "Emergency Preparedness and Response",
        "8.1": "Operational Planning and Control (partial exclusions possible)",
    },
    "ISO 45001:2018": {
        "8.1.4": "Procurement",
        "8.1.4.3": "Outsourcing",
        "8.2": "Management of Change",
    },
    "ISO 22000:2018": {
        "8.5.4": "Preliminary Information and PRPs (partial)",
        "8.9.4": "Handling of Potentially Unsafe Products",
    },
    "ISO 13485:2016": {
        "7.3": "Design and Development",
        "7.5.2": "Cleanliness of Product",
        "7.5.5": "Particular Requirements for Sterile Medical Devices",
        "7.6": "Control of Monitoring and Measuring Equipment",
    },
    "ISO/IEC 27001:2022": {
        "Annex A": "Selected controls only (many Annex A controls may be excluded with justification in SoA)",
    },
}


async def _generate_nac_ai(audit_set) -> dict:
    """Use Claude to suggest N/A clauses based on scope + standards."""
    standards_str = ", ".join(
        {"QMS": "ISO 9001:2015", "EMS": "ISO 14001:2015", "OHSMS": "ISO 45001:2018",
         "FSMS": "ISO 22000:2018", "ISMS": "ISO/IEC 27001:2022", "MDQMS": "ISO 13485:2016",
         "ABMS": "ISO 37001:2016", "ENMS": "ISO 50001:2018"}.get(c, c)
        for c in (audit_set.standards or [])
    )
    
    prompt = f"""You are an experienced ISO certification auditor working for IFC Global LLC, a UAF-accredited certification body.

An organization has applied for certification to: {standards_str}

Organization scope of certification:
"{audit_set.scope_en or 'Not specified'}"

Industry sector (EA code): {audit_set.ea_code or 'Not specified'}
Number of employees: {audit_set.effective_employees or 'Not specified'}

Your task: Identify which standard clauses are likely NOT APPLICABLE (N/A) for this organization, based on their scope of activities.

Rules:
1. A clause is N/A only if it is STRUCTURALLY impossible for the organization to apply it given their activities (not just because they choose not to implement it)
2. For ISO 9001, clause 8.3 (Design and Development) is N/A if the organization only manufactures to external specifications and does not design products
3. For ISO 9001, clause 7.1.5.2 (Measurement Traceability) is N/A only if the organization uses no measurement equipment whose calibration affects product conformity
4. N/A exclusions must be justified
5. Do NOT exclude clauses that are difficult to implement — only those that genuinely don't apply to this activity

For each suggested N/A clause, provide:
- Clause number
- Clause title
- Brief justification (1-2 sentences) based on the scope

Format your response as a JSON object:
{{
  "suggestions": [
    {{
      "clause": "8.3",
      "standard": "ISO 9001:2015",
      "title": "Design and Development of Products and Services",
      "justification": "The organization produces [product] to customer-provided specifications and does not design or develop new products.",
      "confidence": "high"  // "high" | "medium" | "low"
    }}
  ],
  "nac_text": "8.3 (ISO 9001:2015): Organization manufactures to external specifications — no design/development activities; ..."
}}

If no clauses are clearly N/A, return an empty suggestions list and an empty nac_text.
Be conservative — it's better to include fewer N/A exclusions than too many.
"""
    
    settings = get_settings()
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    
    message = client.messages.create(
        model=settings.claude_model,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}]
    )
    
    import json
    response_text = message.content[0].text
    # Extract JSON from response
    json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
    if json_match:
        result = json.loads(json_match.group())
    else:
        result = {"suggestions": [], "nac_text": ""}
    
    return result
```

### 3. Frontend: "Generate NAC" button

In the audit set detail / planning view, next to the "Not Applicable Clauses" text area:

- Add a button: **"✨ Generate Suggestions"** (or "Auto-generate")
- On click: POST to `/audit-sets/{id}/generate-nac`
- Show a loading spinner while waiting
- On response: populate the "Not Applicable Clauses" text area with the generated `nac_text`
- Also display the `suggestions` array as a table below the textarea: Clause No | Standard | Title | Justification | Confidence
- Allow the user to edit the text area before saving
- Add a "Save" button that calls the update endpoint to persist `non_applicable_clauses`

### 4. Response schema

Add a new response schema:
```python
class NACGenerationResponse(BaseModel):
    non_applicable_clauses: str
    suggestions: list[dict]
```

### 5. Fallback if AI returns nothing

If the generation returns empty (no N/A clauses identified), show the user a message: "No clearly non-applicable clauses were identified for this scope. You can manually enter any N/A clauses in the field above."

---

## Notes

- The NAC field accepts free text so the user can always edit the AI output
- The generated text format should match what auditors expect in documents: "Clause No (Standard): Justification; ..."
- Do NOT auto-save the generated NAC — always require the user to review and explicitly save
- The generation runs once on demand, not automatically on every save (unlike EA code derivation)

## Commit

```bash
git add backend/audit_set/
git add frontend/
git commit -m "feat: AI-generated non-applicable clauses via POST /audit-sets/{id}/generate-nac"
git push
```
