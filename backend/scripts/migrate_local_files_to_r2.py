"""
Portal 121 — Migrate local files to Cloudflare R2.

Scans all DB tables that store file_path references, uploads matching local
files to R2, and updates the DB record to the new S3 reference.

Usage:
    python scripts/migrate_local_files_to_r2.py --dry-run
    python scripts/migrate_local_files_to_r2.py --apply

Requires environment variables:
    STORAGE_BACKEND=s3
    S3_BUCKET, S3_ENDPOINT_URL, S3_ACCESS_KEY, S3_SECRET_KEY
"""
from __future__ import annotations

import argparse
import os
import sys

# Add backend/ to path so imports work when run from backend/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import get_settings
from storage.document_store import upload as store_upload, is_s3_ref

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def _relative_key(abs_path: str, storage_base: str) -> str | None:
    """Derive a relative object key from an absolute local path."""
    abs_path = os.path.abspath(abs_path)
    abs_base = os.path.abspath(storage_base)
    if abs_path.startswith(abs_base):
        return abs_path[len(abs_base):].lstrip("/").lstrip("\\")
    # Try common Railway paths
    for prefix in ["/data/storage/", "/app/storage/", "./storage/"]:
        if abs_path.startswith(prefix):
            return abs_path[len(prefix):]
    # Last resort: use everything after "storage/"
    idx = abs_path.find("storage/")
    if idx >= 0:
        return abs_path[idx + len("storage/"):]
    return None


def migrate(dry_run: bool = True) -> None:
    settings = get_settings()

    if settings.storage_backend != "s3":
        print("ERROR: STORAGE_BACKEND must be 's3' to run this migration.")
        print(f"  Current value: {settings.storage_backend!r}")
        sys.exit(1)

    engine = create_engine(settings.database_url)
    Session = sessionmaker(bind=engine)
    db = Session()

    # Tables and their file_path columns
    tables = [
        ("audit_set_shared_documents", "file_path"),
        ("audit_set_audit_reports", "file_path"),
        ("audit_set_nc_forms", "file_path"),
        ("audit_set_nc_evidence", "file_path"),
        ("audit_set_impartiality_declarations", "file_path"),
    ]

    total_migrated = 0
    total_skipped = 0
    total_missing = 0
    total_already_s3 = 0

    for table_name, col_name in tables:
        print(f"\n{'='*60}")
        print(f"Table: {table_name}.{col_name}")
        print(f"{'='*60}")

        try:
            rows = db.execute(
                __import__("sqlalchemy").text(
                    f"SELECT id, {col_name} FROM {table_name} WHERE {col_name} IS NOT NULL"
                )
            ).fetchall()
        except Exception as e:
            print(f"  SKIP — table not found or error: {e}")
            continue

        for row in rows:
            row_id, file_path = row[0], row[1]

            if is_s3_ref(file_path):
                total_already_s3 += 1
                continue

            # Check if file exists locally
            local_path = file_path
            if not os.path.isabs(local_path):
                local_path = os.path.join(settings.storage_base_path, local_path)

            if not os.path.isfile(local_path):
                print(f"  MISSING: {row_id} → {file_path}")
                total_missing += 1
                continue

            # Derive relative key
            rel_key = _relative_key(local_path, settings.storage_base_path)
            if not rel_key:
                print(f"  SKIP (cannot derive key): {row_id} → {file_path}")
                total_skipped += 1
                continue

            if dry_run:
                file_size = os.path.getsize(local_path)
                print(f"  WOULD MIGRATE: {row_id}")
                print(f"    local:  {local_path}")
                print(f"    key:    {rel_key}")
                print(f"    size:   {file_size:,} bytes")
                total_migrated += 1
            else:
                try:
                    with open(local_path, "rb") as f:
                        content = f.read()
                    new_ref = store_upload(rel_key, content)
                    db.execute(
                        __import__("sqlalchemy").text(
                            f"UPDATE {table_name} SET {col_name} = :new_ref WHERE id = :row_id"
                        ),
                        {"new_ref": new_ref, "row_id": row_id},
                    )
                    print(f"  MIGRATED: {row_id} → {new_ref}")
                    total_migrated += 1
                except Exception as e:
                    print(f"  ERROR: {row_id} → {e}")
                    total_skipped += 1

    if not dry_run:
        db.commit()

    db.close()

    print(f"\n{'='*60}")
    print(f"Summary ({'DRY RUN' if dry_run else 'APPLIED'}):")
    print(f"  Already S3:  {total_already_s3}")
    print(f"  Migrated:    {total_migrated}")
    print(f"  Missing:     {total_missing}")
    print(f"  Skipped:     {total_skipped}")
    print(f"{'='*60}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate local files to Cloudflare R2")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="Preview changes without applying")
    group.add_argument("--apply", action="store_true", help="Apply migration")
    args = parser.parse_args()
    migrate(dry_run=args.dry_run)
