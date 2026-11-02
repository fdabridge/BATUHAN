# Independent IFC Global tracker

The `/certificate-tracker` page opens in a separate window from the staff sidebar. It uses IFC Global branding and the existing Certiva sign-in, with shared server-side saves, revision conflict protection and change history.

## Access

Administrators have access. To grant a colleague access, add their existing account email to the backend environment variable `IFC_TRACKER_EDITOR_EMAILS` (comma-separated). Other users are denied by the API. Designated editors can use the direct page URL; administrators and planners also see the sidebar shortcut. Only administrators can import.

## Separate storage and initial import

Backend startup creates only three additional tables in the configured persistent database: `standalone_tracker_records`, `standalone_tracker_history`, and `standalone_tracker_metadata`. No existing operational client, certificate, audit or invoice tables are read or changed by this module.

An administrator can select **Import existing tracker** on an empty tracker and upload its **Export for sweep** JSON. Import preserves certificates, invoices, other payments, archived records, source notes and IAF/UAF evidence. Validation is atomic and a second import is rejected. Client data is deliberately not committed to GitHub. History begins with the import; legacy change history is not imported. The original tracker remains a separate system, not a synchronized source.

## Editing and review

The module retains stage views, expiry ranges, consultant filters, invoice and payment views, registry reviews, notes, archive/restore and exports. Registry statuses are imported snapshots, not live IAF/UAF connections. Changing certificate identity clears its previous registry match. Confirmed-paid certificates do not require invoice follow-up; Ender Karsli remains payment-only.

Edits save to the server. The screen refreshes every 15 seconds when it is safe to do so. Stale revisions receive a conflict rather than overwriting another editor. Invoice payment changes update linked records within this tracker only, respecting owner-confirmed payments. Unknown amounts are not invented.

## Validation

- `PYTHONPATH=backend python3 -m pytest backend/tests/unit/test_standalone_tracker.py -q`
- In `frontend`: `npx tsc --noEmit` and `npm run build`

Use the existing backend persistent database configuration and backups in production. Deploy both backend and frontend before importing the current tracker export.
