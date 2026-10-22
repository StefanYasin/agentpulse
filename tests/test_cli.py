"""CLI behavior tests."""

import json

import pytest

from agentpulse.cli import main

from conftest import FIXED_NOW_TEXT, FIXTURES


def test_report_command(capsys):
    code = main(["report", "--cron-dir", str(FIXTURES), "--now", FIXED_NOW_TEXT])
    out = capsys.readouterr().out
    assert code == 0
    assert "AGENTPULSE  fleet report" in out
    assert "ATTENTION (3)" in out


def test_report_fail_on_attention(capsys):
    code = main(
        ["report", "--cron-dir", str(FIXTURES), "--now", FIXED_NOW_TEXT, "--fail-on-attention"]
    )
    capsys.readouterr()
    assert code == 1


def test_json_command(capsys):
    code = main(["json", "--cron-dir", str(FIXTURES), "--now", FIXED_NOW_TEXT, "--compact"])
    out = capsys.readouterr().out
    assert code == 0
    payload = json.loads(out)
    assert payload["counts"]["total"] == 11
    assert "\n" not in out.strip()


def test_missing_state_exit_code(capsys, tmp_path):
    code = main(["report", "--cron-dir", str(tmp_path / "missing")])
    captured = capsys.readouterr()
    assert code == 2
    assert "cron state not found" in captured.err


def test_invalid_now_is_rejected(tmp_path):
    with pytest.raises(SystemExit) as excinfo:
        main(["report", "--cron-dir", str(FIXTURES), "--now", "yesterday"])
    assert "invalid --now value" in str(excinfo.value.code)


def test_invalid_port_is_rejected(capsys):
    assert main(["serve", "--port", "0"]) == 2
    assert "port must be between 1 and 65535" in capsys.readouterr().err


def test_version_flag():
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
