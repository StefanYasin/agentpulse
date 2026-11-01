# agentpulse

A read-only operations dashboard for my Hermes cron fleet. It reads the scheduler's `jobs.json`, normalizes every job, and shows what is failing, what is overdue, and what runs next.

I built this because `jobs.json` is a 28 job wall of JSON, and the failures I actually care about are easy to miss: a backup job erroring for nine runs straight, or a delivery target that silently stopped resolving.

## What it shows

- Name, schedule, enabled state, and normalized status for every job
- Last run, next run, and failure streak
- The error text from `last_error`, `last_delivery_error`, or `last_failure.detail`
- Drift: `next_run_at` in the past while the job is still enabled
- Gateway phase and heartbeat age when the Hermes `state` directory is present
- A dark HTML page that refreshes itself, a JSON API, and a text digest

Statuses are normalized to `ok`, `error`, `delivery_failed`, `paused`, `completed`, `never_run`, and `unknown`. The scheduler's original value is kept in the JSON payload as `raw_status`.

## Requirements

Python 3.9 or newer. No runtime dependencies.

## Install

```bash
git clone https://github.com/StefanYasin/agentpulse.git
cd agentpulse
python -m pip install -e .
```

Or skip the install and run from the checkout:

```bash
python -m agentpulse report
```

## Usage

```bash
# text digest for the terminal or a cron mail
agentpulse report

# every scheduled job, not just the next six
agentpulse report --all --limit 10

# exit 1 when something is erroring or drifting
agentpulse report --fail-on-attention

# dashboard
agentpulse serve --port 8788

# raw normalized state
agentpulse json --compact
```

Open `http://127.0.0.1:8788` after `serve`.

### Endpoints

| Path | What it returns |
| --- | --- |
| `GET /` | Dashboard HTML, auto refresh every 20 seconds by default |
| `GET /api/state` | Same payload as `agentpulse json` |
| `GET /healthz` | `200` with job counts, or `503` when state cannot be read |

Change the refresh interval with `--refresh`. Bind elsewhere with `--host`. Both `serve` and `report` accept `--cron-dir` and `--state-dir`; `AGENTPULSE_CRON_DIR` and `AGENTPULSE_STATE_DIR` do the same from the environment. Without either, the CLI looks in the standard Hermes locations.

```bash
agentpulse serve --host 0.0.0.0 --port 8788 --refresh 30
agentpulse report --cron-dir /opt/hermes/cron --state-dir /opt/hermes/state
```

## State source

The parser reads `<cron-dir>/jobs.json`. It accepts the current shape:

```json
{
  "jobs": [
    {
      "id": "a1b2c3d4e5f1",
      "name": "Nightly vault backup push",
      "schedule": {"kind": "cron", "expr": "0 4 * * *", "display": "0 4 * * *"},
      "enabled": true,
      "state": "scheduled",
      "last_status": "error",
      "last_run_at": "2026-10-22T04:01:11-04:00",
      "next_run_at": "2026-10-23T04:00:00-04:00",
      "last_error": "Script exited with code 1"
    }
  ],
  "updated_at": "2026-10-22T11:26:08-04:00"
}
```

It also handles `interval` and `once` schedules, a bare list at the top level, missing optional fields, `null` timestamps, and epoch or ISO timestamps. Records that cannot be normalized are skipped and counted, not fatal. A missing or corrupt `jobs.json` returns exit code 2 from the CLI and a 503 from the server, with the path in the message.

Drift only applies to active jobs: enabled, not completed, and with a `next_run_at` in the past. A paused job with no next run is not drift.

## Tests

```bash
python -m pytest -q
```

The suite runs against anonymized fixtures in `tests/fixtures/` that were copied from real Hermes state shapes: a job failing nine runs in a row, a delivery failure with no `last_error`, an interval job, a completed one-off, a paused job, an unknown status, a never run job, and a drifted job. Tests cover the parser, status normalization, drift math, the text report, HTML escaping, the HTTP endpoints over a real socket, and the CLI exit codes.

## Limits

- Read only. No restart button, no writes to the scheduler.
- The state file is read on every request. It is small (under 100 KB for 28 jobs), so caching has not been worth the staleness.
- Run durations are not shown because `jobs.json` does not record them. `cron/executions.db` is the natural next source.
- Times are shown in UTC so the output is stable across machines. The JSON keeps the original ISO offsets.

## License

MIT

Built by [Stefan Yasin](https://stefanyasin.github.io/)


## Operations

Read-only by design:

- **No write path:** the dashboard reads the scheduler's `jobs.json` and state files. There is no endpoint that can change a job.
- **Raw values preserved:** normalized statuses keep the scheduler's original value in `raw_status`, so nothing is hidden and nothing is invented.
- **Failures surface fast:** failure streaks, drift (a job whose `next_run_at` is in the past), and error text are on the page, not buried in JSON.
- **Tested:** the suite runs in CI and passes on a fresh clone.
