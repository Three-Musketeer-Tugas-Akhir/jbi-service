#!/usr/bin/env python3
"""
Cleanup script: delete all FAILED / CROPPING_FAILED pipeline jobs
and their associated MinIO objects.

Usage:
    python cleanup_failed_jobs.py [--dry-run]

Requirements (from project venv):
    pip install psycopg2-binary minio

Override defaults via env vars:
    DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASS
    MINIO_ENDPOINT, MINIO_ACCESS_KEY, MINIO_SECRET_KEY, MINIO_BUCKET, MINIO_SECURE
"""

import os
import sys
import argparse
from urllib.parse import urlparse

import psycopg2
from minio import Minio
from minio.error import S3Error

# ── Defaults (match app/core/config.py) ──────────────────────────────
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "anotasi_db")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASS = os.getenv("DB_PASS", "Pastibisa123")

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "anotasi-videos")
MINIO_SECURE = os.getenv("MINIO_SECURE", "false").lower() in ("1", "true", "yes")

STATUSES = ("FAILED", "CROPPING_FAILED")


def get_db_connection():
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASS,
    )


def get_minio_client():
    return Minio(
        MINIO_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=MINIO_SECURE,
    )


def delete_minio_prefix(minio_client: Minio, prefix: str, dry_run: bool = False):
    """Remove all objects under a given prefix from MinIO."""
    try:
        objects = list(minio_client.list_objects(MINIO_BUCKET, prefix=prefix, recursive=True))
        if not objects:
            return 0, []

        if dry_run:
            return len(objects), [obj.object_name for obj in objects]

        # minio-python >= 7.0 uses remove_objects generator
        errors = list(minio_client.remove_objects(MINIO_BUCKET, objects))
        if errors:
            for err in errors:
                print(f"  ⚠️  MinIO delete error: {err}", file=sys.stderr)
        return len(objects), errors
    except S3Error as e:
        print(f"  ⚠️  MinIO error for prefix {prefix}: {e}", file=sys.stderr)
        return 0, [e]


def main():
    parser = argparse.ArgumentParser(description="Delete failed pipeline jobs + MinIO files")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be deleted without deleting")
    args = parser.parse_args()

    dry_run = args.dry_run
    label = "[DRY-RUN] Would delete" if dry_run else "Deleting"

    conn = get_db_connection()
    conn.autocommit = False
    cur = conn.cursor()

    # 1. Select candidate jobs
    cur.execute(
        "SELECT id, status, original_filename, error_message FROM pipeline_jobs WHERE status IN %s",
        (STATUSES,),
    )
    rows = cur.fetchall()

    if not rows:
        print("No FAILED / CROPPING_FAILED jobs found.")
        return

    print(f"Found {len(rows)} job(s) to process:\n")
    for job_id, status, filename, err in rows:
        print(f"  • {job_id} | {status} | {filename or '(no name)'}")
        if err:
            print(f"    Error: {err[:120]}")
    print()

    if dry_run:
        print("This is a DRY RUN. No data will be deleted.\n")
    else:
        confirm = input(f"Delete {len(rows)} job(s) + their MinIO files? [y/N]: ")
        if confirm.lower() not in ("y", "yes"):
            print("Aborted.")
            return

    minio_client = get_minio_client()
    deleted_jobs = 0
    deleted_minio_objects = 0

    try:
        for job_id, status, filename, _ in rows:
            prefix = f"jobs/{job_id}/"
            print(f"{label} MinIO prefix: {prefix} …", end=" ")
            count, errors = delete_minio_prefix(minio_client, prefix, dry_run=dry_run)
            print(f"{count} object(s)")
            deleted_minio_objects += count

            if not dry_run and errors:
                # If MinIO deletion had errors, ask whether to continue
                print(f"  ⚠️  Errors occurred deleting MinIO files for {job_id}")
                # Still proceed with DB deletion — orphan files can be cleaned later

        # 2. Delete from PostgreSQL
        if not dry_run:
            print(f"\nDeleting {len(rows)} job(s) from database …")
            cur.execute(
                "DELETE FROM pipeline_jobs WHERE status IN %s RETURNING id",
                (STATUSES,),
            )
            deleted = cur.fetchall()
            conn.commit()
            deleted_jobs = len(deleted)
            print(f"Done. Deleted {deleted_jobs} job(s) and {deleted_minio_objects} MinIO object(s).")
        else:
            print(f"\n[DRY-RUN] Would delete {len(rows)} job(s) from database and ~{deleted_minio_objects} MinIO object(s).")

    except Exception as e:
        conn.rollback()
        print(f"\n❌ Transaction rolled back due to error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
