"""Shared fixtures for the AgentPulse test suite."""

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agentpulse.parser import load_snapshot  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
FIXED_NOW = datetime(2026, 10, 22, 15, 0, tzinfo=timezone.utc)
FIXED_NOW_TEXT = "2026-10-22T15:00:00+00:00"


@pytest.fixture
def cron_dir():
    return FIXTURES


@pytest.fixture
def snapshot(cron_dir):
    return load_snapshot(cron_dir, now=FIXED_NOW, include_gateway=False)
