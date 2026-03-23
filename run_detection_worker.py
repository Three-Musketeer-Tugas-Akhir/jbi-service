#!/usr/bin/env python
"""Entry point for running the detection worker."""

import asyncio
import sys
from pathlib import Path

# Add app to path
sys.path.insert(0, str(Path(__file__).parent))

from app.services.detection_worker import run_detection_worker


if __name__ == "__main__":
    try:
        asyncio.run(run_detection_worker())
    except KeyboardInterrupt:
        print("Worker stopped by user")
        sys.exit(0)
    except Exception as e:
        print(f"Worker failed: {e}")
        sys.exit(1)
