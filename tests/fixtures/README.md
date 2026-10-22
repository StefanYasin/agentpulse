# Fixtures

`jobs.json` is the main fixture. It keeps the exact field shapes and value
types observed in a real Hermes `cron/jobs.json` (28 jobs at the time), with
job names, ids, and filesystem paths changed. The error text is real in shape
but points at `<home>` instead of a real user directory.

Covered cases:

- `a1b2c3d4e5f1`: cron job with a multi line script error and a 9 run streak
- `b2c3d4e5f6a2`: healthy daily cron job
- `c3d4e5f6a7b3`: healthy weekly cron job with a late dispatch
- `d4e5f6a7b8c4`: healthy job with `next_run_at` in the past, which is drift
- `e5f6a7b8c9d5`: `delivery_failed` with `last_delivery_error` and no `last_error`
- `f6a7b8c9d0e6`: `interval` schedule
- `a7b8c9d0e1f7`: completed `once` job with a null `next_run_at`
- `b8c9d0e1f2a8`: disabled and paused job with no next run
- `c9d0e1f2a3b9`: never run job (`last_run_at` and `last_status` null)
- `d0e1f2a3b4ca`: unknown raw status `skipped` and no schedule object
- `e1f2a3b4c5db`: epoch `last_run_at` and `Z` suffixed `next_run_at`

Other files:

- `jobs_list.json`: bare list at the top level
- `jobs_bare.json`: one job object, used when a compact fixture is enough
- `jobs_empty.json`: valid file with zero jobs
- `jobs_broken.json`: invalid JSON for the error path

Tests treat `2026-10-22T15:00:00Z` as "now" so drift math is deterministic.
