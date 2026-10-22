"""Plain text fleet digest."""

from __future__ import annotations

import textwrap
from datetime import datetime
from typing import List, Optional

from .model import FleetSnapshot, Job
from .parser import summarize_error

LABELS = {
    "ok": "OK",
    "error": "ERROR",
    "delivery_failed": "DELIVERY FAILED",
    "paused": "PAUSED",
    "completed": "COMPLETED",
    "never_run": "NEVER RUN",
    "unknown": "UNKNOWN",
}

RULE = "-" * 72


def format_dt_utc(value: Optional[datetime]) -> str:
    if value is None:
        return "never"
    from datetime import timezone

    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def humanize_seconds(seconds: float) -> str:
    seconds = abs(int(round(seconds)))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days:
        return "%dd %dh" % (days, hours) if hours else "%dd" % days
    if hours:
        return "%dh %02dm" % (hours, minutes) if minutes else "%dh" % hours
    if minutes:
        return "%dm" % minutes
    return "%ds" % secs


def relative(value: Optional[datetime], now: datetime) -> str:
    if value is None:
        return ""
    delta = (value - now).total_seconds()
    if delta >= 0:
        return "in %s" % humanize_seconds(delta)
    return "%s ago" % humanize_seconds(delta)


def label_for(job: Job) -> str:
    label = LABELS.get(job.status, job.status.upper())
    if job.status == "unknown" and job.raw_status:
        label = "UNKNOWN (%s)" % job.raw_status
    return label


def attention_label(job: Job) -> str:
    """A drifting but otherwise healthy job should read as DRIFT, not OK."""
    if job.is_drifted and job.status == "ok":
        return "DRIFT"
    return label_for(job)


def _wrapped(text: str, indent: str, width: int = 96) -> List[str]:
    lines = textwrap.wrap(text, width=max(width - len(indent), 20)) or [""]
    return [indent + line for line in lines]


def _job_block(job: Job, now: datetime) -> List[str]:
    lines = ["  %-17s %s" % (attention_label(job), job.name)]
    lines.append(
        "  %-17s schedule %s | last %s (%s) | streak %d"
        % ("", job.schedule, format_dt_utc(job.last_run_at), relative(job.last_run_at, now) or "n/a", job.failure_streak)
    )
    next_bits = "next %s" % format_dt_utc(job.next_run_at)
    if job.next_run_at is not None:
        next_bits += " (%s)" % relative(job.next_run_at, now)
    if job.is_drifted:
        next_bits += " | DRIFT %s overdue" % humanize_seconds(job.drift_seconds)
    lines.append("  %-17s %s" % ("", next_bits))
    if job.error:
        first = summarize_error(job.error, limit=400)
        lines.extend(_wrapped("error: " + first, "  %-17s " % ""))
    return lines


def render_report(
    snapshot: FleetSnapshot,
    limit: int = 6,
    show_all: bool = False,
) -> str:
    """Render a deterministic text digest for terminal or cron mail."""
    now = snapshot.generated_at
    counts = snapshot.counts()
    lines: List[str] = []

    lines.append("AGENTPULSE  fleet report")
    lines.append("generated  %s" % format_dt_utc(now))
    source = snapshot.source
    if snapshot.source_updated_at is not None:
        source += "  (updated %s)" % format_dt_utc(snapshot.source_updated_at)
    lines.append("source     %s" % source)
    if snapshot.gateway:
        gw = snapshot.gateway
        phase = gw.get("phase") or "unknown"
        pid = gw.get("pid")
        age = gw.get("heartbeat_age_seconds")
        bits = [str(phase)]
        if pid:
            bits.append("pid %s" % pid)
        if age is not None:
            bits.append("heartbeat %s ago" % humanize_seconds(age))
        if gw.get("heartbeat_stale"):
            bits.append("STALE")
        lines.append("gateway    %s" % ", ".join(bits))
    lines.append("")

    summary = "%d jobs: %d ok, %d error, %d delivery failed, %d drift" % (
        counts["total"],
        counts["ok"],
        counts["error"],
        counts["delivery_failed"],
        counts["drift"],
    )
    extras = []
    if counts["paused"]:
        extras.append("%d paused" % counts["paused"])
    if counts["completed"]:
        extras.append("%d completed" % counts["completed"])
    if counts["never_run"]:
        extras.append("%d never run" % counts["never_run"])
    if extras:
        summary += ", " + ", ".join(extras)
    lines.append(summary)
    lines.append("")

    attention = snapshot.attention()
    lines.append("ATTENTION (%d)" % len(attention))
    lines.append(RULE)
    if attention:
        for job in attention:
            lines.extend(_job_block(job, now))
            lines.append("")
    else:
        lines.append("  none")
        lines.append("")

    drifted = snapshot.drifted()
    lines.append("DRIFT (%d)" % len(drifted))
    lines.append(RULE)
    if drifted:
        for job in drifted:
            lines.append(
                "  %-17s %-42s %s overdue"
                % ("DRIFT", job.name[:42], humanize_seconds(job.drift_seconds))
            )
    else:
        lines.append("  none")
    lines.append("")

    upcoming = snapshot.upcoming(limit=None if show_all else limit)
    heading = "UP NEXT" if not show_all else "ALL SCHEDULED"
    lines.append("%s (%d)" % (heading, len(upcoming)))
    lines.append(RULE)
    if upcoming:
        for job in upcoming:
            lines.append(
                "  %s  %-40s %s"
                % (format_dt_utc(job.next_run_at), job.name[:40], job.schedule)
            )
    else:
        lines.append("  none")
    lines.append("")

    if counts["paused"] or counts["completed"]:
        inactive = [job for job in snapshot.sorted_jobs() if job.status in ("paused", "completed")]
        lines.append("INACTIVE (%d)" % len(inactive))
        lines.append(RULE)
        for job in inactive:
            lines.append(
                "  %-17s %-40s %s"
                % (label_for(job), job.name[:40], job.schedule)
            )
    return "\n".join(line.rstrip() for line in lines).rstrip() + "\n"
