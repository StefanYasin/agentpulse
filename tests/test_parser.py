"""Parser and normalization tests, driven by anonymized real state shapes."""

import json
from datetime import datetime, timezone

import pytest

from agentpulse import model
from agentpulse.parser import (
    CronStateError,
    extract_error,
    job_from_record,
    load_gateway_state,
    load_snapshot,
    parse_datetime,
    parse_schedule,
    resolve_status,
    summarize_error,
)
from agentpulse.report import humanize_seconds

from conftest import FIXED_NOW, FIXTURES


def test_loads_every_job(snapshot):
    assert len(snapshot.jobs) == 11
    assert snapshot.skipped == 0
    assert snapshot.source.endswith("jobs.json")
    assert snapshot.source_updated_at == datetime(2026, 10, 22, 15, 26, 8, 695463, tzinfo=timezone.utc)


def test_counts_match_fixture(snapshot):
    counts = snapshot.counts()
    assert counts["total"] == 11
    assert counts["ok"] == 5
    assert counts["error"] == 1
    assert counts["delivery_failed"] == 1
    assert counts["completed"] == 1
    assert counts["paused"] == 1
    assert counts["never_run"] == 1
    assert counts["unknown"] == 1
    assert counts["drift"] == 1
    assert counts["attention"] == 3


def test_errors_sort_first(snapshot):
    names = [job.name for job in snapshot.sorted_jobs()]
    assert names[0] == "Nightly vault backup push"
    assert names[1] == "Application response sweep"
    assert names[-1] == "Stage memory batch"


def test_cron_schedule(snapshot):
    job = next(j for j in snapshot.jobs if j.id == "c3d4e5f6a7b3")
    assert job.schedule == "0 11 * * 1"
    assert job.schedule_kind == "cron"


def test_interval_schedule(snapshot):
    job = next(j for j in snapshot.jobs if j.name == "Browser keepalive")
    assert job.schedule_kind == "interval"
    assert job.schedule == "every 60m"


def test_once_schedule_has_no_next_run(snapshot):
    job = next(j for j in snapshot.jobs if j.name == "Stage memory batch")
    assert job.schedule_kind == "once"
    assert job.schedule == "once at 2026-10-16 08:00"
    assert job.next_run_at is None
    assert job.status == model.COMPLETED


def test_error_text_and_summary(snapshot):
    job = next(j for j in snapshot.jobs if j.name == "Nightly vault backup push")
    assert job.status == model.ERROR
    assert job.failure_streak == 9
    assert "WinError 183" in job.error
    summary = summarize_error(job.error)
    assert summary.startswith("Script exited with code 1")
    assert "\n" not in summary


def test_delivery_error_used_when_last_error_missing(snapshot):
    job = next(j for j in snapshot.jobs if j.name == "Application response sweep")
    assert job.status == model.DELIVERY_FAILED
    assert job.error == "no delivery target resolved for deliver=telegram"


def test_status_normalization_table():
    assert resolve_status("ok", True, "scheduled", FIXED_NOW) == model.OK
    assert resolve_status("error", True, "scheduled", FIXED_NOW) == model.ERROR
    assert resolve_status("failed", True, "scheduled", FIXED_NOW) == model.ERROR
    assert resolve_status("delivery_failed", True, "scheduled", FIXED_NOW) == model.DELIVERY_FAILED
    assert resolve_status("ok", False, "scheduled", FIXED_NOW) == model.PAUSED
    assert resolve_status("ok", True, "completed", FIXED_NOW) == model.COMPLETED
    assert resolve_status(None, True, "scheduled", None) == model.NEVER_RUN
    assert resolve_status(None, True, "scheduled", FIXED_NOW) == model.UNKNOWN
    assert resolve_status("skipped", True, "scheduled", FIXED_NOW) == model.UNKNOWN


def test_drift_only_counts_active_jobs(snapshot):
    drifted = snapshot.drifted()
    assert [job.name for job in drifted] == ["Lead engine scan"]
    assert drifted[0].drift_seconds == pytest.approx(7200.0)
    assert drifted[0].is_drifted
    assert drifted[0].status == model.OK
    assert drifted[0].needs_attention

    completed = next(j for j in snapshot.jobs if j.name == "Stage memory batch")
    paused = next(j for j in snapshot.jobs if j.name == "Paused research sweep")
    assert completed.drift_seconds == 0
    assert paused.drift_seconds == 0


def test_null_next_run_is_not_drift(snapshot):
    job = next(j for j in snapshot.jobs if j.name == "Legacy import job")
    assert job.next_run_at is None
    assert job.drift_seconds == 0
    assert job.status == model.UNKNOWN
    assert job.raw_status == "skipped"


def test_never_run_job(snapshot):
    job = next(j for j in snapshot.jobs if j.name == "New posting poller")
    assert job.status == model.NEVER_RUN
    assert job.last_run_at is None
    assert job.next_run_at is not None


def test_epoch_and_z_timestamps(snapshot):
    job = next(j for j in snapshot.jobs if j.name == "Clock skew probe")
    assert job.last_run_at == datetime(2026, 10, 21, 13, 0, tzinfo=timezone.utc)
    assert job.next_run_at == datetime(2026, 10, 22, 20, 0, tzinfo=timezone.utc)


def test_missing_file_raises(tmp_path):
    with pytest.raises(CronStateError, match="cron state not found"):
        load_snapshot(tmp_path, now=FIXED_NOW)


def test_broken_json_raises(tmp_path):
    (tmp_path / "jobs.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(CronStateError, match="invalid JSON"):
        load_snapshot(tmp_path, now=FIXED_NOW)


def test_list_file_is_accepted(tmp_path):
    raw = json.loads((FIXTURES / "jobs_list.json").read_text(encoding="utf-8"))
    (tmp_path / "jobs.json").write_text(json.dumps(raw), encoding="utf-8")
    snapshot = load_snapshot(tmp_path, now=FIXED_NOW, include_gateway=False)
    assert len(snapshot.jobs) == 1
    assert snapshot.source_updated_at is None


def test_empty_jobs_file(tmp_path):
    (tmp_path / "jobs.json").write_text(
        (FIXTURES / "jobs_empty.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    snapshot = load_snapshot(tmp_path, now=FIXED_NOW, include_gateway=False)
    assert snapshot.jobs == []
    assert snapshot.counts()["total"] == 0


def test_non_object_records_are_skipped(tmp_path):
    payload = {"jobs": [{"id": "aaa", "name": "fine", "last_status": "ok"}, "junk", 5]}
    (tmp_path / "jobs.json").write_text(json.dumps(payload), encoding="utf-8")
    snapshot = load_snapshot(tmp_path, now=FIXED_NOW, include_gateway=False)
    assert len(snapshot.jobs) == 1
    assert snapshot.skipped == 2


def test_missing_optional_fields_get_defaults():
    job = job_from_record({"id": "x1"}, FIXED_NOW)
    assert job.id == "x1"
    assert job.name == "x1"
    assert job.schedule == "unknown schedule"
    assert job.schedule_kind == "unknown"
    assert job.enabled is True
    assert job.status == model.NEVER_RUN
    assert job.failure_streak == 0


def test_parse_datetime_variants():
    assert parse_datetime("2026-10-22T11:00:00-04:00") == datetime(
        2026, 10, 22, 15, 0, tzinfo=timezone.utc
    )
    assert parse_datetime("2026-10-22T15:00:00Z") == FIXED_NOW
    assert parse_datetime("2026-10-22 15:00:00") == FIXED_NOW
    assert parse_datetime(1792587600) == datetime(2026, 10, 21, 13, 0, tzinfo=timezone.utc)
    assert parse_datetime(None) is None
    assert parse_datetime("") is None
    with pytest.raises(ValueError):
        parse_datetime("not a date")
    with pytest.raises(ValueError):
        parse_datetime(True)


def test_parse_schedule_infers_kind():
    assert parse_schedule({"expr": "0 1 * * *"}) == ("0 1 * * *", "cron")
    assert parse_schedule({"minutes": 15}) == ("every 15m", "interval")
    assert parse_schedule({"run_at": "2026-01-01T00:00:00Z"})[1] == "once"
    assert parse_schedule(None, "every day at 9am") == ("every day at 9am", "unknown")
    assert parse_schedule(None) == ("unknown schedule", "unknown")
    assert parse_schedule("*/5 * * * *") == ("*/5 * * * *", "text")


def test_extract_error_falls_back_to_last_failure():
    raw = {"last_error": "", "last_failure": {"detail": "boom"}}
    assert extract_error(raw) == "boom"
    assert extract_error({"last_error": "first"}) == "first"
    assert extract_error({}) is None


def test_summarize_error_collapses_and_caps():
    assert summarize_error("  line one  \n\nline two") == "line one"
    assert summarize_error("x" * 500, limit=50).endswith("...")
    assert len(summarize_error("x" * 500, limit=50)) == 50
    assert summarize_error(None) == ""


def test_to_dict_is_json_serializable(snapshot):
    payload = json.loads(json.dumps(snapshot.to_dict()))
    assert payload["counts"]["total"] == 11
    job = next(j for j in payload["jobs"] if j["name"] == "Lead engine scan")
    assert job["drift"] is True
    assert job["drift_seconds"] == pytest.approx(7200.0)
    assert datetime.fromisoformat(job["next_run_at"]) == datetime(
        2026, 10, 22, 13, 0, tzinfo=timezone.utc
    )


def test_gateway_state_missing(tmp_path):
    assert load_gateway_state(tmp_path, now=FIXED_NOW) is None


def test_gateway_state_present_and_stale(tmp_path):
    (tmp_path / "gateway.lifecycle.json").write_text(
        json.dumps({"phase": "running", "pid": 4242, "started_at": "2026-10-21T19:40:46+00:00"}),
        encoding="utf-8",
    )
    heartbeat = tmp_path / "gateway.heartbeat"
    heartbeat.write_text("{}", encoding="utf-8")
    import os

    stale_ts = FIXED_NOW.timestamp() - 300
    os.utime(heartbeat, (stale_ts, stale_ts))
    gateway = load_gateway_state(tmp_path, now=FIXED_NOW)
    assert gateway["phase"] == "running"
    assert gateway["pid"] == 4242
    assert gateway["heartbeat_stale"] is True
    assert gateway["heartbeat_age_seconds"] == pytest.approx(300.0, abs=1.0)


def test_humanize_seconds():
    assert humanize_seconds(0) == "0s"
    assert humanize_seconds(45) == "45s"
    assert humanize_seconds(600) == "10m"
    assert humanize_seconds(7200) == "2h"
    assert humanize_seconds(7500) == "2h 05m"
    assert humanize_seconds(86400 * 2) == "2d"
    assert humanize_seconds(90000) == "1d 1h"
