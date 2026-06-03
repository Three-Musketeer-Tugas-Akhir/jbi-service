#!/usr/bin/env python3
"""
JBI Pipeline Monitor - Standalone monitoring script.

Usage:
    python scripts/pipeline_monitor.py              # Human-readable table
    python scripts/pipeline_monitor.py --json       # Machine-readable JSON
    python scripts/pipeline_monitor.py --watch 30   # Live dashboard (30s refresh)

Requirements:
    - Python 3.11+
    - Environment: DATABASE_URL, KAFKA_BROKERS
    - Docker socket access (for container monitoring)
"""

import asyncio
import json
import os
import sys
import subprocess
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich.panel import Panel
from rich import box

# Add project root to path for config
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class PipelineMonitor:
    """Monitor JBI pipeline status across Docker, Kafka, and PostgreSQL."""

    def __init__(self):
        self.database_url = os.getenv(
            "DATABASE_URL",
            "postgresql+asyncpg://postgres:Pastibisa123@localhost:5432/anotasi_db"
        )
        self.kafka_brokers = os.getenv("KAFKA_BROKERS", "localhost:9092")
        self.console = Console()

    async def get_container_status(self) -> List[Dict[str, Any]]:
        """Get Docker container status."""
        containers = []
        try:
            result = subprocess.run(
                ["docker", "ps", "--format", "json", "-a"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    if not line:
                        continue
                    try:
                        c = json.loads(line)
                        name = c.get("Names", "")
                        # Filter only jbi-service containers
                        if any(svc in name for svc in ["api", "worker", "db", "kafka", "minio", "reconciliation"]):
                            containers.append({
                                "name": name,
                                "status": c.get("State", "unknown"),
                                "health": c.get("Health", "N/A"),
                                "uptime": c.get("Status", ""),
                                "running": c.get("State") == "running"
                            })
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            containers.append({
                "name": "docker-error",
                "status": f"error: {e}",
                "health": "N/A",
                "uptime": "",
                "running": False
            })
        return containers

    async def get_kafka_status(self) -> Dict[str, Any]:
        """Get Kafka topic and consumer group status."""
        status = {
            "topics": [],
            "consumer_groups": [],
            "error": None
        }
        try:
            from aiokafka import AIOKafkaAdminClient
            
            admin = AIOKafkaAdminClient(
                bootstrap_servers=self.kafka_brokers
            )
            await admin.start()
            
            try:
                # List topics
                topics = await admin.list_topics()
                for topic in topics:
                    if topic.startswith("pipeline."):
                        status["topics"].append({
                            "name": topic,
                            "partitions": len(topics[topic].partitions)
                        })
                
                # Consumer groups
                groups = ["detection-workers", "asr-workers", "cropping-workers"]
                for group in groups:
                    try:
                        group_info = await admin.describe_consumer_groups([group])
                        if group_info:
                            gi = group_info[0]
                            members = len(gi.members) if hasattr(gi, 'members') else 0
                            status["consumer_groups"].append({
                                "group": group,
                                "state": gi.state if hasattr(gi, 'state') else "unknown",
                                "members": members,
                                "status": "healthy" if members > 0 else "no-consumers"
                            })
                    except Exception:
                        status["consumer_groups"].append({
                            "group": group,
                            "state": "unknown",
                            "members": 0,
                            "status": "error"
                        })
            finally:
                await admin.close()
                
        except ImportError:
            status["error"] = "aiokafka not installed"
        except Exception as e:
            status["error"] = str(e)
        
        return status

    async def get_db_status(self) -> Dict[str, Any]:
        """Get PostgreSQL pipeline status."""
        status = {
            "jobs_by_status": {},
            "stuck_jobs": [],
            "transcript_status": {},
            "error": None
        }
        
        try:
            import asyncpg
            
            # Parse DATABASE_URL
            db_url = self.database_url.replace("postgresql+asyncpg://", "postgresql://")
            conn = await asyncpg.connect(db_url)
            
            try:
                # Jobs by status
                rows = await conn.fetch(
                    "SELECT status, COUNT(*) as count FROM pipeline_jobs GROUP BY status ORDER BY count DESC"
                )
                for row in rows:
                    status["jobs_by_status"][row["status"]] = row["count"]
                
                # Stuck jobs (thresholds from reconciliation service)
                stuck_rows = await conn.fetch("""
                    SELECT 
                        id::text,
                        status,
                        current_stage,
                        updated_at,
                        NOW() - updated_at as stuck_duration
                    FROM pipeline_jobs
                    WHERE status IN ('DETECTING', 'TRANSCRIBING', 'CROPPING_IN_PROGRESS')
                    AND (
                        (status = 'DETECTING' AND updated_at < NOW() - INTERVAL '30 minutes')
                        OR (status = 'TRANSCRIBING' AND updated_at < NOW() - INTERVAL '60 minutes')
                        OR (status = 'CROPPING_IN_PROGRESS' AND updated_at < NOW() - INTERVAL '60 minutes')
                    )
                    ORDER BY updated_at ASC
                """)
                for row in stuck_rows:
                    status["stuck_jobs"].append({
                        "job_id": row["id"],
                        "status": row["status"],
                        "stage": row["current_stage"],
                        "stuck_for": str(row["stuck_duration"])
                    })
                
                # Transcript status
                transcript_rows = await conn.fetch(
                    "SELECT status, COUNT(*) as count FROM pipeline_transcripts GROUP BY status"
                )
                for row in transcript_rows:
                    status["transcript_status"][row["status"] or "pending"] = row["count"]
                    
            finally:
                await conn.close()
                
        except ImportError:
            status["error"] = "asyncpg not installed"
        except Exception as e:
            status["error"] = str(e)
        
        return status

    def format_table(self, containers, kafka_status, db_status) -> None:
        """Format output as rich tables."""
        self.console.print("\n")
        
        # Title
        self.console.print(
            Panel.fit(
                "[bold blue]JBI Pipeline Monitor[/bold blue]\n"
                f"[dim]{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}[/dim]"
            )
        )
        
        # Container Status
        container_table = Table(title="Container Status", box=box.ROUNDED)
        container_table.add_column("Container", style="cyan")
        container_table.add_column("Status", style="bold")
        container_table.add_column("Health")
        container_table.add_column("Uptime")
        
        for c in containers:
            status_color = "green" if c["running"] else "red"
            container_table.add_row(
                c["name"],
                f"[{status_color}]{c['status']}[/{status_color}]",
                c["health"],
                c["uptime"]
            )
        
        self.console.print(container_table)
        self.console.print()
        
        # Kafka Consumer Groups
        if kafka_status["consumer_groups"]:
            kafka_table = Table(title="Kafka Consumer Groups", box=box.ROUNDED)
            kafka_table.add_column("Group", style="cyan")
            kafka_table.add_column("State")
            kafka_table.add_column("Members", justify="right")
            kafka_table.add_column("Status", style="bold")
            
            for g in kafka_status["consumer_groups"]:
                status_color = "green" if g["members"] > 0 else "yellow"
                kafka_table.add_row(
                    g["group"],
                    g["state"],
                    str(g["members"]),
                    f"[{status_color}]{g['status']}[/{status_color}]"
                )
            
            self.console.print(kafka_table)
            self.console.print()
        
        if kafka_status["error"]:
            self.console.print(f"[yellow]Kafka: {kafka_status['error']}[/yellow]\n")
        
        # Topics
        if kafka_status["topics"]:
            topic_table = Table(title="Kafka Topics", box=box.ROUNDED)
            topic_table.add_column("Topic", style="cyan")
            topic_table.add_column("Partitions", justify="right")
            
            for t in kafka_status["topics"]:
                topic_table.add_row(t["name"], str(t["partitions"]))
            
            self.console.print(topic_table)
            self.console.print()
        
        # Jobs by Status
        if db_status["jobs_by_status"]:
            job_table = Table(title="Pipeline Jobs", box=box.ROUNDED)
            job_table.add_column("Status", style="cyan")
            job_table.add_column("Count", justify="right", style="bold")
            
            for status, count in db_status["jobs_by_status"].items():
                color = "green" if status in ["NEEDS_VOICE_ANNOTATION", "READY_FOR_ANNOTATION"] else \
                        "yellow" if status in ["DETECTING", "TRANSCRIBING", "CROPPING_IN_PROGRESS"] else \
                        "red" if status in ["FAILED", "CROPPING_FAILED"] else "white"
                job_table.add_row(status, f"[{color}]{count}[/{color}]")
            
            self.console.print(job_table)
            self.console.print()
        
        # Transcript Status
        if db_status["transcript_status"]:
            transcript_table = Table(title="Transcripts", box=box.ROUNDED)
            transcript_table.add_column("Status", style="cyan")
            transcript_table.add_column("Count", justify="right", style="bold")
            
            for status, count in db_status["transcript_status"].items():
                color = "green" if status == "cropped" else \
                        "red" if status == "failed" else "yellow"
                transcript_table.add_row(status, f"[{color}]{count}[/{color}]")
            
            self.console.print(transcript_table)
            self.console.print()
        
        # Stuck Jobs
        if db_status["stuck_jobs"]:
            stuck_table = Table(title="[yellow]Stuck Jobs[/yellow]", box=box.ROUNDED)
            stuck_table.add_column("Job ID", style="cyan")
            stuck_table.add_column("Status")
            stuck_table.add_column("Stage")
            stuck_table.add_column("Stuck For", style="red")
            
            for job in db_status["stuck_jobs"]:
                stuck_table.add_row(
                    job["job_id"][:8] + "...",
                    job["status"],
                    job["stage"] or "-",
                    job["stuck_for"]
                )
            
            self.console.print(stuck_table)
            self.console.print()
        
        if db_status["error"]:
            self.console.print(f"[yellow]Database: {db_status['error']}[/yellow]\n")

    def format_json(self, containers, kafka_status, db_status) -> None:
        """Format output as JSON."""
        output = {
            "timestamp": datetime.now().isoformat(),
            "containers": containers,
            "kafka": kafka_status,
            "database": db_status
        }
        print(json.dumps(output, indent=2, default=str))

    async def run(self, json_output: bool = False) -> None:
        """Run monitoring once."""
        containers = await self.get_container_status()
        kafka_status = await self.get_kafka_status()
        db_status = await self.get_db_status()
        
        if json_output:
            self.format_json(containers, kafka_status, db_status)
        else:
            self.format_table(containers, kafka_status, db_status)

    async def watch(self, interval: int = 30) -> None:
        """Run monitoring in watch mode."""
        with Live(refresh_per_second=4, screen=True) as live:
            while True:
                containers = await self.get_container_status()
                kafka_status = await self.get_kafka_status()
                db_status = await self.get_db_status()
                
                # Capture table output
                with self.console.capture() as capture:
                    self.format_table(containers, kafka_status, db_status)
                live.update(capture.get())
                
                await asyncio.sleep(interval)


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="JBI Pipeline Monitor")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--watch", type=int, metavar="SECONDS", help="Watch mode with refresh interval")
    parser.add_argument("--env", default=".env", help="Path to .env file")
    
    args = parser.parse_args()
    
    # Load .env if exists
    env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), args.env)
    if os.path.exists(env_path):
        from dotenv import load_dotenv
        load_dotenv(env_path)
    
    monitor = PipelineMonitor()
    
    if args.watch:
        try:
            asyncio.run(monitor.watch(args.watch))
        except KeyboardInterrupt:
            print("\nMonitoring stopped.")
    else:
        asyncio.run(monitor.run(json_output=args.json))


if __name__ == "__main__":
    main()
