#!/usr/bin/env python3
"""
Certiva Auditor Bulk Import Script
-----------------------------------
Reads auditors_import.json and POSTs each auditor to POST /auditors/
using an admin JWT token obtained via POST /auth/login.

Usage:
    python import_auditors.py \
        --api-url https://YOUR-BACKEND-RAILWAY-URL \
        --username admin@email.com \
        --password yourpassword

    Optional:
        --dry-run       Print payloads without sending
        --skip-existing Skip if an auditor with the same name already exists
        --start-from N  Skip first N entries (resume after a failed run)
"""
import argparse
import json
import sys
import time
import requests


def login(api_url: str, username: str, password: str) -> str:
    """Authenticate and return JWT token."""
    resp = requests.post(
        f"{api_url}/auth/login",
        json={"username": username, "password": password},
        timeout=15,
    )
    resp.raise_for_status()
    token = resp.json().get("access_token")
    if not token:
        raise ValueError(f"No access_token in response: {resp.json()}")
    print(f"✓ Logged in as {username}")
    return token


def get_existing_names(api_url: str, headers: dict) -> set:
    """Fetch all existing auditor names to detect duplicates."""
    resp = requests.get(f"{api_url}/auditors/?active_only=false", headers=headers, timeout=30)
    resp.raise_for_status()
    return {a["name"].strip().lower() for a in resp.json()}


def main():
    parser = argparse.ArgumentParser(description="Import auditors into Certiva")
    parser.add_argument("--api-url", required=True, help="Backend base URL (no trailing slash)")
    parser.add_argument("--username", required=True, help="Admin username / email")
    parser.add_argument("--password", required=True, help="Admin password")
    parser.add_argument("--input", default="auditors_import.json", help="JSON file to import")
    parser.add_argument("--dry-run", action="store_true", help="Don't actually POST — just show what would be sent")
    parser.add_argument("--skip-existing", action="store_true", help="Skip auditors already in the system by name")
    parser.add_argument("--start-from", type=int, default=0, help="Skip first N entries (0-indexed)")
    args = parser.parse_args()

    # Strip trailing slash
    api_url = args.api_url.rstrip("/")

    # Load data
    with open(args.input, encoding="utf-8") as f:
        auditors = json.load(f)
    print(f"Loaded {len(auditors)} auditors from {args.input}")

    if args.dry_run:
        print("\n[DRY RUN] First 3 payloads:")
        for a in auditors[:3]:
            print(json.dumps(a, ensure_ascii=False, indent=2))
        print(f"\n[DRY RUN] Would import {len(auditors)} auditors. Exiting.")
        return

    # Authenticate
    token = login(api_url, args.username, args.password)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # Optional: build existing name set
    existing = set()
    if args.skip_existing:
        print("Fetching existing auditors…")
        existing = get_existing_names(api_url, headers)
        print(f"Found {len(existing)} existing auditors in the system")

    # Import loop
    created = 0
    skipped = 0
    errors = []

    for i, payload in enumerate(auditors):
        if i < args.start_from:
            continue

        name = payload["name"]

        if args.skip_existing and name.strip().lower() in existing:
            print(f"  [{i+1}/{len(auditors)}] SKIP  {name} (already exists)")
            skipped += 1
            continue

        try:
            resp = requests.post(
                f"{api_url}/auditors/",
                headers=headers,
                json=payload,
                timeout=20,
            )
            if resp.status_code == 201:
                print(f"  [{i+1}/{len(auditors)}] OK    {name}")
                created += 1
            else:
                detail = resp.json().get("detail", resp.text[:120])
                print(f"  [{i+1}/{len(auditors)}] ERR   {name} — {resp.status_code}: {detail}")
                errors.append({"index": i, "name": name, "status": resp.status_code, "detail": detail})
        except Exception as e:
            print(f"  [{i+1}/{len(auditors)}] EXC   {name} — {e}")
            errors.append({"index": i, "name": name, "status": None, "detail": str(e)})

        # Small delay to avoid hammering the API
        time.sleep(0.15)

    print(f"\n{'='*50}")
    print(f"Done. Created: {created}  Skipped: {skipped}  Errors: {len(errors)}")
    if errors:
        print("\nFailed entries:")
        for e in errors:
            print(f"  [{e['index']}] {e['name']}: {e['status']} — {e['detail']}")
        # Write error log
        with open("import_errors.json", "w") as f:
            json.dump(errors, f, indent=2)
        print("Error details saved to import_errors.json")
        sys.exit(1)


if __name__ == "__main__":
    main()
