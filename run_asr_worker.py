#!/usr/bin/env python
"""Entry point for running the ASR worker."""

import asyncio
import sys
from pathlib import Path

# Add app to path
sys.path.insert(0, str(Path(__file__).parent))

from app.logging_config import setup_logging
from app.workers.asr_worker import ASRWorker

# Initialize logging
setup_logging()

if __name__ == "__main__":
    try:
        worker = ASRWorker()
        asyncio.run(worker.run())
    except KeyboardInterrupt:
        print("Worker stopped by user")
        sys.exit(0)
    except Exception as e:
        print(f"Worker failed: {e}")
        sys.exit(1)
