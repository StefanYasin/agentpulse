"""Command line entry point."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

from . import __version__
from .parser import CronStateError, load_snapshot, parse_datetime
from .report import render_report
from .server import DEFAULT_PORT, DEFAULT_REFRESH, create_server


def _source_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--cron-dir",
        type=Path,
        default=None,
        help="directory containing jobs.json (default: local Hermes cron dir)",
    )
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=None,
        help="directory containing gateway heartbeat files (default: sibling state dir)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentpulse",
        description="Read-only operations dashboard for a Hermes cron fleet.",
    )
    parser.add_argument("--version", action="version", version="agentpulse " + __version__)
    sub = parser.add_subparsers(dest="command", required=True)

    report = sub.add_parser("report", help="print a text digest of the fleet")
    _source_args(report)
    report.add_argument("--now", default=None, help="evaluate drift at this ISO timestamp")
    report.add_argument("--limit", type=int, default=6, help="jobs in the up next list (default: 6)")
    report.add_argument("--all", action="store_true", help="list every scheduled job, not just the next few")
    report.add_argument(
        "--fail-on-attention",
        action="store_true",
        help="exit 1 when any job is erroring or drifting (useful from cron)",
    )

    state = sub.add_parser("json", help="print the same payload as /api/state")
    _source_args(state)
    state.add_argument("--now", default=None, help="evaluate drift at this ISO timestamp")
    state.add_argument("--compact", action="store_true", help="single line output")

    serve = sub.add_parser("serve", help="serve the dashboard over HTTP")
    _source_args(serve)
    serve.add_argument("--host", default="127.0.0.1", help="bind address (default: 127.0.0.1)")
    serve.add_argument("--port", type=int, default=DEFAULT_PORT, help="port (default: 8788)")
    serve.add_argument(
        "--refresh",
        type=int,
        default=DEFAULT_REFRESH,
        help="browser auto refresh interval in seconds (default: 20)",
    )
    return parser


def _resolve_now(value: Optional[str]):
    if not value:
        return None
    try:
        return parse_datetime(value)
    except ValueError as exc:
        raise SystemExit("agentpulse: invalid --now value: %s" % exc)


def _fail(message: str) -> int:
    print("agentpulse: %s" % message, file=sys.stderr)
    return 2


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    now = _resolve_now(getattr(args, "now", None))

    if args.command == "report":
        try:
            snapshot = load_snapshot(args.cron_dir, now=now, state_dir=args.state_dir)
        except CronStateError as exc:
            return _fail(str(exc))
        sys.stdout.write(render_report(snapshot, limit=max(args.limit, 0), show_all=args.all))
        if args.fail_on_attention and snapshot.counts()["attention"]:
            return 1
        return 0

    if args.command == "json":
        try:
            snapshot = load_snapshot(args.cron_dir, now=now, state_dir=args.state_dir)
        except CronStateError as exc:
            return _fail(str(exc))
        payload = snapshot.to_dict()
        if args.compact:
            print(json.dumps(payload, separators=(",", ":")))
        else:
            print(json.dumps(payload, indent=2))
        return 0

    if args.command == "serve":
        if not 1 <= args.port <= 65535:
            return _fail("port must be between 1 and 65535")
        if args.refresh < 1:
            return _fail("--refresh must be at least 1 second")
        try:
            httpd = create_server(
                host=args.host,
                port=args.port,
                cron_dir=args.cron_dir,
                state_dir=args.state_dir,
                refresh_seconds=args.refresh,
            )
        except OSError as exc:
            return _fail("cannot bind %s:%s: %s" % (args.host, args.port, exc))
        url_host = args.host if args.host not in ("0.0.0.0", "::") else "127.0.0.1"
        print("AgentPulse %s serving http://%s:%d" % (__version__, url_host, args.port), flush=True)
        try:
            print("source: %s" % load_snapshot(args.cron_dir, state_dir=args.state_dir).source, flush=True)
        except CronStateError as exc:
            print("source: unavailable (%s)" % exc, flush=True)
        print("refreshing every %ds, Ctrl+C to stop" % args.refresh, flush=True)
        try:
            httpd.serve_forever(poll_interval=0.5)
        except KeyboardInterrupt:
            print("\nstopped")
        finally:
            httpd.server_close()
        return 0

    return _fail("unknown command: %s" % args.command)
