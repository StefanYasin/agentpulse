"""Report rendering tests."""

from datetime import datetime, timedelta, timezone

from agentpulse import model
from agentpulse.model import FleetSnapshot, Job
from agentpulse.report import humanize_seconds, relative, render_report

from conftest import FIXED_NOW


def test_header_and_summary(snapshot):
    out = render_report(snapshot)
    assert out.startswith("AGENTPULSE  fleet report")
    assert "generated  2026-10-22 15:00 UTC" in out
    assert "jobs.json" in out
    assert (
        "11 jobs: 5 ok, 1 error, 1 delivery failed, 1 drift, 1 paused, 1 completed, 1 never run"
        in out
    )


def test_attention_section_lists_three(snapshot):
    out = render_report(snapshot)
    assert "ATTENTION (3)" in out
    assert "Nightly vault backup push" in out
    assert "Application response sweep" in out
    assert "Lead engine scan" in out
    assert "ERROR" in out
    assert "DELIVERY FAILED" in out
    assert "Script exited with code 1" in out
    assert "no delivery target resolved for deliver=telegram" in out


def test_drift_section(snapshot):
    out = render_report(snapshot)
    assert "DRIFT (1)" in out
    assert "2h overdue" in out


def test_drifted_job_is_labelled_drift_in_attention(snapshot):
    out = render_report(snapshot)
    assert "  DRIFT             Lead engine scan" in out
    assert "  OK                Lead engine scan" not in out


def test_up_next_is_sorted_and_limited(snapshot):
    out = render_report(snapshot, limit=2)
    section = out.split("UP NEXT (2)")[1]
    lines = [line for line in section.splitlines() if line.startswith("  2026")]
    assert len(lines) == 2
    assert "Application response sweep" in lines[0]
    assert "Clock skew probe" in lines[1]
    assert "Lead engine scan" not in section


def test_show_all_lists_every_future_job(snapshot):
    out = render_report(snapshot, show_all=True)
    assert "ALL SCHEDULED (7)" in out
    assert "Weekly portfolio maintenance" in out


def test_inactive_section(snapshot):
    out = render_report(snapshot)
    assert "INACTIVE (2)" in out
    assert "Stage memory batch" in out
    assert "Paused research sweep" in out


def test_no_attention_and_no_drift():
    job = Job(
        id="healthy1",
        name="Healthy job",
        schedule="0 1 * * *",
        schedule_kind="cron",
        enabled=True,
        state="scheduled",
        status=model.OK,
        last_run_at=FIXED_NOW - timedelta(hours=1),
        next_run_at=FIXED_NOW + timedelta(hours=1),
    )
    snapshot = FleetSnapshot(generated_at=FIXED_NOW, source="/tmp/jobs.json", jobs=[job])
    out = render_report(snapshot)
    assert "ATTENTION (0)" in out
    assert "DRIFT (0)" in out
    assert "none" in out
    assert "Healthy job" in out


def test_gateway_line():
    job = Job(
        id="j1",
        name="Job",
        schedule="0 1 * * *",
        schedule_kind="cron",
        enabled=True,
        state="scheduled",
        status=model.OK,
    )
    snapshot = FleetSnapshot(
        generated_at=FIXED_NOW,
        source="/tmp/jobs.json",
        jobs=[job],
        gateway={"phase": "running", "pid": 4242, "heartbeat_age_seconds": 720.0, "heartbeat_stale": False},
    )
    out = render_report(snapshot)
    assert "gateway    running, pid 4242, heartbeat 12m ago" in out


def test_report_is_deterministic(snapshot):
    assert render_report(snapshot) == render_report(snapshot)
    assert render_report(snapshot).endswith("\n")


def test_relative_and_humanize():
    assert relative(FIXED_NOW + timedelta(minutes=90), FIXED_NOW) == "in 1h 30m"
    assert relative(FIXED_NOW - timedelta(minutes=5), FIXED_NOW) == "5m ago"
    assert relative(None, FIXED_NOW) == ""
    assert humanize_seconds(-600) == "10m"
    assert humanize_seconds(3600 * 24 * 3 + 60) == "3d"
