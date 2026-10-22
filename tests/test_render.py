"""HTML rendering tests."""

from agentpulse import model
from agentpulse.model import FleetSnapshot, Job
from agentpulse.render import render_error_page, render_page

from conftest import FIXED_NOW


def test_page_renders_every_job(snapshot):
    page = render_page(snapshot, refresh_seconds=15)
    assert page.startswith("<!doctype html>")
    assert "AGENTPULSE" in page
    assert '<meta http-equiv="refresh" content="15">' in page
    for job in snapshot.jobs:
        assert job.name in page


def test_status_badges_and_drift(snapshot):
    page = render_page(snapshot)
    assert 'class="badge error"' in page
    assert 'class="badge delivery_failed"' in page
    assert 'class="badge ok"' in page
    assert "drift 2h overdue" in page
    assert "WinError 183" in page


def test_summary_cards(snapshot):
    page = render_page(snapshot)
    assert "Needs attention" in page
    assert '<div class="v">3</div>' in page
    assert '<div class="v">11</div>' in page


def test_user_content_is_escaped():
    job = Job(
        id="evil",
        name='<img src=x onerror="alert(1)">',
        schedule="<b>0 1 * * *</b>",
        schedule_kind="cron",
        enabled=True,
        state="scheduled",
        status=model.ERROR,
        error='<script>alert("x")</script>',
        next_run_at=FIXED_NOW,
    )
    snapshot = FleetSnapshot(generated_at=FIXED_NOW, source="/tmp/jobs.json", jobs=[job])
    page = render_page(snapshot)
    assert "<img src=x" not in page
    assert "&lt;img src=x" in page
    assert "<script>alert" not in page
    assert "&lt;script&gt;" in page
    assert "&lt;b&gt;0 1 * * *&lt;/b&gt;" in page


def test_empty_fleet_page():
    snapshot = FleetSnapshot(generated_at=FIXED_NOW, source="/tmp/jobs.json", jobs=[])
    page = render_page(snapshot)
    assert "No jobs found" in page
    assert '<div class="v">0</div>' in page


def test_error_page_escapes_message():
    page = render_error_page("<bad> /nope", status=503)
    assert "State unavailable (503)" in page
    assert "&lt;bad&gt;" in page
    assert "<bad>" not in page


def test_footer_credit(snapshot):
    page = render_page(snapshot)
    assert "Built by" in page
    assert 'href="https://stefanyasin.github.io/"' in page
