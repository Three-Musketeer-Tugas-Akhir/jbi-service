#!/usr/bin/env python3
"""Verify premerge columns exist in pipeline_jobs table.

Usage:
    python scripts/verify_premerge_schema.py

Requires DATABASE_URL env var or .env file in project root.
"""

import os
import sys
import asyncio
import asyncpg

# Try to load .env from project root
from pathlib import Path
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                os.environ.setdefault(key, val)

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL not set")
    sys.exit(1)


EXPECTED_COLUMNS = {
    "premerge_status": "character varying(20)",
    "premerge_total_pairs": "integer",
    "premerge_completed_pairs": "integer",
    "premerge_failed_pairs": "integer",
    "premerge_started_at": "timestamp with time zone",
    "premerge_completed_at": "timestamp with time zone",
    "premerge_batches": "jsonb",
    "premerge_error": "text",
}

EXPECTED_INDEX = "ix_pipeline_jobs_premerge_status"


async def main():
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        print("=" * 60)
        print("Pre-merge Schema Verification")
        print("=" * 60)

        # 1. Check columns
        rows = await conn.fetch(
            """
            SELECT column_name, data_type, character_maximum_length
            FROM information_schema.columns
            WHERE table_name = 'pipeline_jobs'
            AND column_name LIKE 'premerge_%'
            ORDER BY ordinal_position
            """
        )

        found = {r["column_name"]: r for r in rows}
        all_ok = True

        print("\n📋 Columns:")
        for col, expected_type in EXPECTED_COLUMNS.items():
            if col in found:
                actual_type = found[col]["data_type"]
                if found[col]["character_maximum_length"]:
                    actual_type += f"({found[col]['character_maximum_length']})"
                if actual_type == expected_type or (expected_type == "character varying(20)" and actual_type == "character varying"):
                    print(f"  ✅ {col:<30} {actual_type}")
                else:
                    print(f"  ⚠️  {col:<30} {actual_type} (expected: {expected_type})")
                    all_ok = False
            else:
                print(f"  ❌ {col:<30} MISSING")
                all_ok = False

        # 2. Check index
        idx_rows = await conn.fetch(
            """
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE tablename = 'pipeline_jobs'
            AND indexname = $1
            """,
            EXPECTED_INDEX,
        )

        print(f"\n🔍 Index '{EXPECTED_INDEX}':")
        if idx_rows:
            print(f"  ✅ EXISTS")
            print(f"     {idx_rows[0]['indexdef']}")
        else:
            print(f"  ❌ MISSING")
            all_ok = False

        # 3. Show existing premerge statuses (if any data)
        status_rows = await conn.fetch(
            """
            SELECT premerge_status, COUNT(*) as cnt
            FROM pipeline_jobs
            WHERE premerge_status IS NOT NULL
            GROUP BY premerge_status
            ORDER BY cnt DESC
            """
        )

        print(f"\n📊 Current premerge data:")
        if status_rows:
            for r in status_rows:
                print(f"  {r['premerge_status']}: {r['cnt']} job(s)")
        else:
            print("  No jobs with premerge_status yet (expected after first CV2 job completes)")

        print("\n" + "=" * 60)
        if all_ok:
            print("✅ ALL CHECKS PASSED — schema ready")
        else:
            print("❌ SOME CHECKS FAILED — run the ALTER TABLE script")
        print("=" * 60)

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
