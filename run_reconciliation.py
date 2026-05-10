#!/usr/bin/env python
"""
Entry point for running the pipeline reconciliation job.

This script periodically checks for pipeline jobs stuck in intermediate
stages and republishes them to Kafka if needed.

Usage:
    python run_reconciliation.py
    
Environment:
    RECONCILIATION_INTERVAL_MINUTES: How often to run (default: 5)
"""

import asyncio
import os
import sys
from pathlib import Path

# Add app to path
sys.path.insert(0, str(Path(__file__).parent))

from app.logging_config import setup_logging
from app.services.reconciliation_service import reconciliation_service

setup_logging()

RECONCILIATION_INTERVAL_MINUTES = int(os.getenv("RECONCILIATION_INTERVAL_MINUTES", "5"))


async def main():
    """Run reconciliation loop."""
    print(f"Starting pipeline reconciliation (interval={RECONCILIATION_INTERVAL_MINUTES}min)")
    
    while True:
        try:
            results = await reconciliation_service.run_reconciliation()
            total = sum(v for k, v in results.items() if k != "checked_at")
            if total > 0:
                print(f"Reconciliation: {results}")
        except Exception as e:
            print(f"Reconciliation error: {e}")
        
        await asyncio.sleep(RECONCILIATION_INTERVAL_MINUTES * 60)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Reconciliation stopped by user")
        sys.exit(0)
