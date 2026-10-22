"""Core data types shared by the parser, report, renderer and server."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

# Normalized job states. The scheduler's raw value is kept on Job.raw_status.
OK = "ok"
ERROR = "error"
DELIVERY_FAILED = "delivery_failed"
PAUSED = "paused"
COMPLETED = "completed"
NEVER_RUN = "never_run"
UNKNOWN = "unknown"

SEVERITY = {
    ERROR: 0,
    DELIVERY_FAILED: 1,
    UNKNOWN: 2,
    NEVER_RUN: 3,
    PAUSED: 4,
    OK: 5,
    COMPLETED: 6,
}

ATTENTION_STATUSES = frozenset({ERROR, DELIVERY_FAILED})


@dataclass
class Job:
    """One cron job, normalized for display."""

    id: str
    name: str
    schedule: str
    schedule_kind: str
    enabled: bool
    state: str
    status: str
    raw_status: Optional[str] = None
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None
    error: Optional[str] = None
    failure_streak: int = 0
    repeat_completed: Optional[int] = None
    drift_seconds: float = 0.0
    lateness_seconds: Optional[float] = None

    @property
    def is_drifted(self) -> bool:
        return self.drift_seconds > 0

    @property
    def needs_attention(self) -> bool:
        return self.status in ATTENTION_STATUSES or self.is_drifted

    def sort_key(self) -> tuple:
        return (SEVERITY.get(self.status, 9), -self.drift_seconds, self.name.lower())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "schedule": self.schedule,
            "schedule_kind": self.schedule_kind,
            "enabled": self.enabled,
            "state": self.state,
            "status": self.status,
            "raw_status": self.raw_status,
            "last_run_at": iso_or_none(self.last_run_at),
            "next_run_at": iso_or_none(self.next_run_at),
            "error": self.error,
            "failure_streak": self.failure_streak,
            "repeat_completed": self.repeat_completed,
            "drift": self.is_drifted,
            "drift_seconds": round(self.drift_seconds, 1),
            "lateness_seconds": self.lateness_seconds,
        }


@dataclass
class FleetSnapshot:
    """A point-in-time view of the whole fleet."""

    generated_at: datetime
    source: str
    jobs: List[Job] = field(default_factory=list)
    source_updated_at: Optional[datetime] = None
    skipped: int = 0
    gateway: Optional[Dict[str, Any]] = None

    def counts(self) -> Dict[str, int]:
        counts = {
            "total": len(self.jobs),
            "ok": 0,
            "error": 0,
            "delivery_failed": 0,
            "paused": 0,
            "completed": 0,
            "never_run": 0,
            "unknown": 0,
            "drift": 0,
            "attention": 0,
        }
        for job in self.jobs:
            bucket = job.status if job.status in counts else "unknown"
            counts[bucket] += 1
            if job.is_drifted:
                counts["drift"] += 1
            if job.needs_attention:
                counts["attention"] += 1
        return counts

    def sorted_jobs(self) -> List[Job]:
        return sorted(self.jobs, key=lambda job: job.sort_key())

    def attention(self) -> List[Job]:
        return [job for job in self.sorted_jobs() if job.needs_attention]

    def drifted(self) -> List[Job]:
        return sorted(
            [job for job in self.jobs if job.is_drifted],
            key=lambda job: (-job.drift_seconds, job.name.lower()),
        )

    def upcoming(self, limit: Optional[int] = None) -> List[Job]:
        """Active jobs with a next run in the future, soonest first.

        Overdue jobs are reported by ``drifted()`` instead so the digest never
        lists a past timestamp under an "up next" heading.
        """
        jobs = [
            job
            for job in self.jobs
            if job.next_run_at is not None
            and job.next_run_at > self.generated_at
            and job.enabled
            and job.state != "completed"
        ]
        jobs.sort(key=lambda job: job.next_run_at)
        return jobs[:limit] if limit is not None else jobs

    def to_dict(self) -> Dict[str, Any]:
        return {
            "generated_at": self.generated_at.isoformat(),
            "source": self.source,
            "source_updated_at": iso_or_none(self.source_updated_at),
            "counts": self.counts(),
            "gateway": self.gateway,
            "skipped": self.skipped,
            "jobs": [job.to_dict() for job in self.sorted_jobs()],
        }


def iso_or_none(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value is not None else None
