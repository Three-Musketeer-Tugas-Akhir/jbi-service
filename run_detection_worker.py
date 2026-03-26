#!/usr/bin/env python
"""Entry point for running the detection worker."""

import asyncio
import sys
from pathlib import Path

# Add app to path
sys.path.insert(0, str(Path(__file__).parent))

from app.workers.detection_worker import DetectionWorker


if __name__ == "__main__":
    try:
        worker = DetectionWorker()
        asyncio.run(worker.run())
    except KeyboardInterrupt:
        print("Worker stopped by user")
        sys.exit(0)
    except Exception as e:
        print(f"Worker failed: {e}")
        sys.exit(1)
