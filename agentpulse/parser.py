"""Read Hermes cron state from disk and normalize it.

The scheduler writes a single ``jobs.json`` under the cron directory. The
shape is a mapping with a ``jobs`` list plus an ``updated_at`` stamp, but the
parser also accepts a bare list so hand-written fixtures stay easy to read.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import model
from .model import FleetSnapshot, Job

CRON_STATE_FILE = "jobs.json"
STATE_DIR_NAME = "state"
GATEWAY_LIFECYCLE = "gateway.lifecycle.json"
GATEWAY_HEARTBEAT = "gateway.heartbeat"
HEARTBEAT_STALE_SECONDS = 120.0


class CronStateError(RuntimeError):
    """Raised when cron state cannot be located or parsed."""


def default_cron_dir() -> Path:
    """Best guess for the local Hermes cron directory."""
    override = os.environ.get("AGENTPULSE_CRON_DIR")
    if override:
        return Path(override).expanduser()

    candidates: List[Path] = []
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        candidates.append(Path(local_appdata) / "hermes" / "cron")
    candidates.append(Path.home() / ".hermes" / "cron")
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        candidates.append(Path(xdg) / "hermes" / "cron")
    candidates.append(Path.home() / ".local" / "share" / "hermes" / "cron")

    for candidate in candidates:
        if (candidate / CRON_STATE_FILE).is_file():
            return candidate
    return candidates[0]


def default_state_dir(cron_dir: Path) -> Path:
    """State files live next to the cron directory in a Hermes install."""
    override = os.environ.get("AGENTPULSE_STATE_DIR")
    if override:
        return Path(override).expanduser()
    return Path(cron_dir).parent / STATE_DIR_NAME


def parse_datetime(value: Any) -> Optional[datetime]:
    """Coerce the timestamp shapes seen in cron state into aware datetimes."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    if isinstance(value, bool):
        raise ValueError("boolean is not a timestamp")
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    if not isinstance(value, str):
        raise ValueError("unsupported timestamp type: %s" % type(value).__name__)

    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    parsed = None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
    if parsed is None:
        raise ValueError("unrecognized timestamp: %r" % value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def parse_schedule(raw: Any, fallback_display: Any = None) -> Tuple[str, str]:
    """Return ``(display, kind)`` for any schedule shape in the state file."""
    display = fallback_display if isinstance(fallback_display, str) and fallback_display.strip() else ""
    if isinstance(raw, dict):
        kind = str(raw.get("kind") or "").strip().lower()
        if not kind:
            if raw.get("expr"):
                kind = "cron"
            elif raw.get("minutes") is not None:
                kind = "interval"
            elif raw.get("run_at"):
                kind = "once"
            else:
                kind = "unknown"
        if not display:
            candidate = raw.get("display")
            if isinstance(candidate, str) and candidate.strip():
                display = candidate.strip()
            elif raw.get("expr"):
                display = str(raw["expr"]).strip()
            elif raw.get("minutes") is not None:
                display = "every %sm" % raw["minutes"]
            elif raw.get("run_at"):
                display = "once at %s" % raw["run_at"]
            else:
                display = "unknown schedule"
        return display, kind
    if isinstance(raw, str) and raw.strip():
        return raw.strip(), "text"
    if display:
        return display, "unknown"
    return "unknown schedule", "unknown"


def extract_error(raw: Dict[str, Any]) -> Optional[str]:
    """Pick the most useful failure text from a job record."""
    for key in ("last_error", "last_delivery_error"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    failure = raw.get("last_failure")
    if isinstance(failure, dict):
        for key in ("detail", "error"):
            value = failure.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def resolve_status(
    raw_status: Optional[str],
    enabled: bool,
    state: str,
    last_run_at: Optional[datetime],
) -> str:
    state = (state or "").lower()
    if state == "completed":
        return model.COMPLETED
    if not enabled or state in ("paused", "disabled"):
        return model.PAUSED
    if not raw_status:
        return model.NEVER_RUN if last_run_at is None else model.UNKNOWN
    if raw_status in ("ok", "success", "succeeded"):
        return model.OK
    if raw_status in ("error", "failed", "failure"):
        return model.ERROR
    if raw_status in ("delivery_failed", "delivery_error"):
        return model.DELIVERY_FAILED
    return model.UNKNOWN


def summarize_error(error: Optional[str], limit: int = 180) -> str:
    """First meaningful line, collapsed and capped for table display."""
    if not error:
        return ""
    for line in error.splitlines():
        line = " ".join(line.split())
        if line:
            if len(line) > limit:
                return line[: max(limit - 3, 0)] + "..."
            return line
    return ""


def _as_bool(value: Any, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() not in ("false", "0", "no", "off", "")


def _as_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def job_from_record(raw: Dict[str, Any], now: datetime, index: int = 0) -> Job:
    """Normalize one raw job mapping."""
    if not isinstance(raw, dict):
        raise CronStateError("job record %d is %s, expected an object" % (index, type(raw).__name__))

    job_id = str(raw.get("id") or raw.get("job_id") or "job-%d" % index)
    name = str(raw.get("name") or raw.get("title") or job_id)
    schedule, schedule_kind = parse_schedule(raw.get("schedule"), raw.get("schedule_display"))

    enabled = _as_bool(raw.get("enabled"), True)
    state = str(raw.get("state") or "").strip().lower()
    last_run_at = parse_datetime(raw.get("last_run_at"))
    next_run_at = parse_datetime(raw.get("next_run_at"))
    raw_status = raw.get("last_status")
    raw_status = str(raw_status).strip().lower() if raw_status else None
    error = extract_error(raw)
    status = resolve_status(raw_status, enabled, state, last_run_at)

    drift_seconds = 0.0
    if next_run_at is not None and enabled and state != "completed":
        delta = (now - next_run_at).total_seconds()
        if delta > 0:
            drift_seconds = delta

    repeat = raw.get("repeat") if isinstance(raw.get("repeat"), dict) else {}
    dispatch = raw.get("last_dispatch") if isinstance(raw.get("last_dispatch"), dict) else {}

    return Job(
        id=job_id,
        name=name,
        schedule=schedule,
        schedule_kind=schedule_kind,
        enabled=enabled,
        state=state,
        status=status,
        raw_status=raw_status,
        last_run_at=last_run_at,
        next_run_at=next_run_at,
        error=error,
        failure_streak=_as_int(raw.get("failure_streak"), 0),
        repeat_completed=_as_int(repeat.get("completed"), 0) if repeat else None,
        drift_seconds=drift_seconds,
        lateness_seconds=_as_float(dispatch.get("lateness_seconds")),
    )


def load_gateway_state(state_dir: Path, now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """Read gateway liveness files when they exist. Missing files are fine."""
    state_dir = Path(state_dir)
    lifecycle_path = state_dir / GATEWAY_LIFECYCLE
    heartbeat_path = state_dir / GATEWAY_HEARTBEAT
    if not lifecycle_path.is_file() and not heartbeat_path.is_file():
        return None

    payload: Dict[str, Any] = {}
    if lifecycle_path.is_file():
        try:
            raw = json.loads(lifecycle_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                payload["phase"] = raw.get("phase")
                payload["pid"] = raw.get("pid")
                payload["started_at"] = raw.get("started_at")
        except (OSError, ValueError):
            payload["phase"] = "unreadable"

    if heartbeat_path.is_file():
        try:
            age = (now or datetime.now(timezone.utc)).timestamp() - heartbeat_path.stat().st_mtime
            payload["heartbeat_age_seconds"] = round(age, 1)
            payload["heartbeat_stale"] = age > HEARTBEAT_STALE_SECONDS
        except OSError:
            payload["heartbeat_age_seconds"] = None
            payload["heartbeat_stale"] = True
    return payload or None


def load_snapshot(
    cron_dir=None,
    now: Optional[datetime] = None,
    state_dir=None,
    include_gateway: bool = True,
) -> FleetSnapshot:
    """Load and normalize ``jobs.json``. Raises CronStateError on bad input."""
    now = now or datetime.now(timezone.utc)
    cron_path = Path(cron_dir) if cron_dir is not None else default_cron_dir()
    jobs_path = cron_path / CRON_STATE_FILE
    if not jobs_path.is_file():
        raise CronStateError("cron state not found: %s" % jobs_path)

    try:
        text = jobs_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CronStateError("cannot read %s: %s" % (jobs_path, exc)) from exc

    try:
        data = json.loads(text)
    except ValueError as exc:
        raise CronStateError("invalid JSON in %s: %s" % (jobs_path, exc)) from exc

    if isinstance(data, dict):
        records = data.get("jobs")
        updated_at = parse_datetime(data.get("updated_at"))
    elif isinstance(data, list):
        records = data
        updated_at = None
    else:
        raise CronStateError("unexpected top level type in %s: %s" % (jobs_path, type(data).__name__))

    if records is None:
        raise CronStateError("no 'jobs' list in %s" % jobs_path)
    if not isinstance(records, list):
        raise CronStateError("'jobs' in %s is %s, expected a list" % (jobs_path, type(records).__name__))

    jobs: List[Job] = []
    skipped = 0
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            skipped += 1
            continue
        try:
            jobs.append(job_from_record(record, now, index))
        except ValueError:
            skipped += 1

    gateway = None
    if include_gateway:
        gw_dir = Path(state_dir) if state_dir is not None else default_state_dir(cron_path)
        gateway = load_gateway_state(gw_dir, now=now)

    return FleetSnapshot(
        generated_at=now,
        source=str(jobs_path),
        jobs=jobs,
        source_updated_at=updated_at,
        skipped=skipped,
        gateway=gateway,
    )
