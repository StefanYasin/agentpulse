"""Server-rendered HTML dashboard. No template engine, no build step."""

from __future__ import annotations

import html
from datetime import timezone
from typing import List, Optional

from . import __version__
from .model import FleetSnapshot, Job
from .parser import summarize_error
from .report import humanize_seconds, label_for

CSS = """
:root {
  color-scheme: dark;
  --bg: #0b0e13;
  --panel: #11161f;
  --panel-2: #151c27;
  --line: #1f2937;
  --text: #dbe3ee;
  --muted: #8b99ad;
  --ok: #3ddc84;
  --err: #ff6b6b;
  --warn: #f5b544;
  --accent: #4cc9f0;
}
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; background: var(--bg); color: var(--text); }
body {
  font: 14px/1.5 ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  padding: 24px clamp(12px, 4vw, 48px) 40px;
}
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
header.top {
  display: flex; flex-wrap: wrap; gap: 12px 24px; align-items: center;
  justify-content: space-between; border-bottom: 1px solid var(--line);
  padding-bottom: 16px; margin-bottom: 20px;
}
.brand {
  display: flex; align-items: center; gap: 10px;
  font-weight: 700; letter-spacing: 0.18em; font-size: 15px;
}
.pulse {
  width: 10px; height: 10px; border-radius: 50%; background: var(--ok);
  box-shadow: 0 0 0 0 rgba(61, 220, 132, 0.6); animation: pulse 2.4s infinite;
}
@keyframes pulse {
  0% { box-shadow: 0 0 0 0 rgba(61, 220, 132, 0.45); }
  70% { box-shadow: 0 0 0 10px rgba(61, 220, 132, 0); }
  100% { box-shadow: 0 0 0 0 rgba(61, 220, 132, 0); }
}
.meta { color: var(--muted); font-size: 12px; display: flex; flex-wrap: wrap; gap: 6px 18px; }
.cards {
  display: grid; gap: 12px; margin-bottom: 20px;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
}
.card {
  background: var(--panel); border: 1px solid var(--line); border-radius: 10px;
  padding: 14px 16px;
}
.card .k { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; }
.card .v { font-size: 26px; font-weight: 650; margin-top: 2px; font-variant-numeric: tabular-nums; }
.card.hot { border-color: rgba(255, 107, 107, 0.45); }
.card.hot .v { color: var(--err); }
.card.warm { border-color: rgba(245, 181, 68, 0.4); }
.card.warm .v { color: var(--warn); }
.card.good .v { color: var(--ok); }
.panel {
  background: var(--panel); border: 1px solid var(--line); border-radius: 10px;
  overflow: hidden;
}
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; min-width: 940px; }
caption { text-align: left; padding: 0; height: 0; overflow: hidden; }
th, td { text-align: left; padding: 11px 14px; border-bottom: 1px solid var(--line); vertical-align: top; }
th {
  font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em;
  color: var(--muted); background: var(--panel-2); position: sticky; top: 0;
  font-weight: 600; white-space: nowrap;
}
tbody tr:hover { background: rgba(76, 201, 240, 0.04); }
tbody tr:last-child td { border-bottom: 0; }
.job { font-weight: 600; }
.job .id { display: block; color: var(--muted); font-size: 11px; font-weight: 400; margin-top: 2px; }
.badge {
  display: inline-flex; align-items: center; gap: 6px; white-space: nowrap;
  border-radius: 999px; padding: 2px 9px; font-size: 11px; font-weight: 600;
  border: 1px solid var(--line); color: var(--muted);
}
.badge .dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.badge.ok { color: var(--ok); border-color: rgba(61, 220, 132, 0.35); background: rgba(61, 220, 132, 0.08); }
.badge.error { color: var(--err); border-color: rgba(255, 107, 107, 0.4); background: rgba(255, 107, 107, 0.08); }
.badge.delivery_failed, .badge.unknown, .badge.never_run {
  color: var(--warn); border-color: rgba(245, 181, 68, 0.4); background: rgba(245, 181, 68, 0.08);
}
.badge.paused, .badge.completed { color: var(--muted); }
.drift {
  display: block; margin-top: 4px; color: var(--warn); font-size: 11px; white-space: nowrap;
}
.none { color: var(--ok); }
.detail { color: var(--muted); max-width: 420px; }
.detail.error-text { color: #ffb3b3; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px; }
.raw { display: block; color: var(--muted); font-size: 11px; margin-top: 2px; }
footer {
  margin-top: 22px; padding-top: 14px; border-top: 1px solid var(--line);
  color: var(--muted); font-size: 12px; display: flex; flex-wrap: wrap;
  gap: 8px; justify-content: space-between;
}
.stamp { font-variant-numeric: tabular-nums; }
.error-page { max-width: 760px; margin: 10vh auto; }
.error-page h1 { color: var(--err); font-size: 20px; }
.error-page pre {
  white-space: pre-wrap; background: var(--panel); border: 1px solid var(--line);
  border-radius: 10px; padding: 16px; color: #ffb3b3;
}
@media (max-width: 640px) {
  body { padding: 16px 10px 28px; }
  .card .v { font-size: 22px; }
}
"""

STAMP_JS = """
(function () {
  var start = Date.now();
  var el = document.getElementById("stamp");
  if (!el) { return; }
  setInterval(function () {
    var s = Math.round((Date.now() - start) / 1000);
    el.textContent = s < 2 ? "checked just now" : "checked " + s + "s ago";
  }, 1000);
})();
"""


def esc(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def fmt_utc(value) -> str:
    if value is None:
        return "never"
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M")


def _status_badge(job: Job) -> str:
    label = label_for(job)
    extra = ""
    if job.status == "ok" and not job.enabled:
        extra = " (disabled)"
    return '<span class="badge %s"><span class="dot"></span>%s%s</span>' % (
        esc(job.status),
        esc(label),
        esc(extra),
    )


def _next_cell(job: Job) -> str:
    if job.next_run_at is None:
        return '<span class="mono">-</span>'
    out = '<span class="mono">%s</span>' % esc(fmt_utc(job.next_run_at))
    if job.is_drifted:
        out += '<span class="drift">drift %s overdue</span>' % esc(humanize_seconds(job.drift_seconds))
    return out


def _detail_cell(job: Job) -> str:
    if job.error:
        summary = summarize_error(job.error, limit=200)
        return '<span class="detail error-text" title="%s">%s</span>' % (
            esc(job.error),
            esc(summary),
        )
    if job.is_drifted:
        return '<span class="detail">next run is %s in the past</span>' % esc(
            humanize_seconds(job.drift_seconds)
        )
    if job.status == "paused":
        return '<span class="detail">disabled or paused by the scheduler</span>'
    if job.status == "completed":
        return '<span class="detail">one-off job finished, no next run</span>'
    if job.status == "never_run":
        return '<span class="detail">no run recorded yet</span>'
    if job.status == "unknown" and job.raw_status:
        return '<span class="detail">unmapped status: %s</span>' % esc(job.raw_status)
    return '<span class="detail">-</span>'


def _gateway_pill(snapshot: FleetSnapshot) -> str:
    gw = snapshot.gateway
    if not gw:
        return ""
    phase = str(gw.get("phase") or "unknown")
    stale = bool(gw.get("heartbeat_stale"))
    age = gw.get("heartbeat_age_seconds")
    cls = "error" if stale or phase not in ("running", "started") else "ok"
    bits = [phase]
    if age is not None:
        bits.append("heartbeat %s ago" % humanize_seconds(float(age)))
    return '<span class="badge %s"><span class="dot"></span>gateway %s</span>' % (
        cls,
        esc(", ".join(bits)),
    )


def _rows(jobs: List[Job]) -> str:
    rows = []
    for job in jobs:
        rows.append(
            "<tr>"
            '<td class="job">%s<span class="id mono">%s</span></td>'
            '<td class="mono">%s</td>'
            "<td>%s</td>"
            '<td class="mono">%s</td>'
            "<td>%s</td>"
            '<td class="mono">%d</td>'
            "<td>%s</td>"
            "</tr>"
            % (
                esc(job.name),
                esc(job.id),
                esc(job.schedule),
                _status_badge(job),
                esc(fmt_utc(job.last_run_at)),
                _next_cell(job),
                job.failure_streak,
                _detail_cell(job),
            )
        )
    if not rows:
        rows.append('<tr><td colspan="7" class="detail">No jobs found in the cron state file.</td></tr>')
    return "\n".join(rows)


def render_page(snapshot: FleetSnapshot, refresh_seconds: int = 20) -> str:
    counts = snapshot.counts()
    jobs = snapshot.sorted_jobs()
    updated = fmt_utc(snapshot.source_updated_at)
    generated = fmt_utc(snapshot.generated_at)
    attention = counts["attention"]

    cards = [
        ("Jobs tracked", counts["total"], ""),
        ("Needs attention", attention, "hot" if attention else "good"),
        ("Errors", counts["error"] + counts["delivery_failed"], "hot" if counts["error"] + counts["delivery_failed"] else "good"),
        ("Drift", counts["drift"], "warm" if counts["drift"] else "good"),
        ("Paused", counts["paused"], ""),
    ]
    card_html = "\n".join(
        '<div class="card %s"><div class="k">%s</div><div class="v">%d</div></div>'
        % (cls, esc(label), value)
        for label, value, cls in cards
    )

    skipped = ""
    if snapshot.skipped:
        skipped = '<span class="badge unknown">%d records skipped</span>' % snapshot.skipped

    return """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="{refresh}">
<title>AgentPulse</title>
<style>{css}</style>
</head>
<body>
<header class="top">
  <div class="brand"><span class="pulse"></span>AGENTPULSE</div>
  <div class="meta">
    <span class="mono">{source}</span>
    <span>state updated {updated}</span>
    <span>page built {generated} UTC</span>
    <span>auto refresh {refresh}s</span>
    {gateway}
    {skipped}
  </div>
</header>
<main>
  <section class="cards">
    {cards}
  </section>
  <section class="panel">
    <div class="table-wrap">
      <table>
        <caption>Cron jobs and their latest run state</caption>
        <thead>
          <tr>
            <th scope="col">Job</th>
            <th scope="col">Schedule</th>
            <th scope="col">Status</th>
            <th scope="col">Last run (UTC)</th>
            <th scope="col">Next run (UTC)</th>
            <th scope="col">Streak</th>
            <th scope="col">Detail</th>
          </tr>
        </thead>
        <tbody>
{rows}
        </tbody>
      </table>
    </div>
  </section>
  <footer>
    <span>AgentPulse {version} - read only view of Hermes cron state</span>
    <span class="stamp" id="stamp">checked just now</span>
    <span>Built by <a href="https://stefanyasin.github.io/">Stefan Yasin</a></span>
  </footer>
</main>
<script>{js}</script>
</body>
</html>
""".format(
        refresh=max(int(refresh_seconds), 1),
        css=CSS,
        source=esc(snapshot.source),
        updated=esc(updated),
        generated=esc(generated),
        gateway=_gateway_pill(snapshot),
        skipped=skipped,
        cards=card_html,
        rows=_rows(jobs),
        version=esc(__version__),
        js=STAMP_JS,
    )


def render_error_page(message: str, status: int = 503) -> str:
    return """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AgentPulse - state unavailable</title>
<style>{css}</style>
</head>
<body>
<main class="error-page">
  <h1>State unavailable ({status})</h1>
  <p>The cron state file could not be read. The dashboard will recover on the next refresh once the file is valid.</p>
  <pre>{message}</pre>
</main>
</body>
</html>
""".format(css=CSS, status=int(status), message=esc(message))
