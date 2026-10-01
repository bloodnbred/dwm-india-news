"""CLI contract tests.

The Phase 0 gate is "`pytest` runs and `python -m dwm --help` works". These
tests cover that plus the later stages failing with a clear NotImplementedError
rather than an ImportError, so the command surface stays stable while the
later phases are still stubs.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dwm.cli import app

PROJECT_ROOT = Path(__file__).resolve().parent.parent

STAGES = ["olap", "mine", "report"]
runner = CliRunner()


def test_help_works_as_a_subprocess() -> None:
    """`python -m dwm --help` must work, which is the literal Phase 0 gate."""
    result = subprocess.run(
        [sys.executable, "-m", "dwm", "--help"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",  # the console default is cp1252 and cannot decode this
        errors="replace",
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert "Indian News Warehouse" in result.stdout


def test_version_command() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip()


def test_config_command_emits_json() -> None:
    result = runner.invoke(app, ["config"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert set(payload["datasets"]) == {"toi", "ifnd", "nifty"}
    assert payload["datasets"]["nifty"]["labelled"] is False
    assert payload["datasets"]["ifnd"]["date_precision"] == "month"


def test_all_planned_commands_are_registered() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in [
        "ingest", "etl", "features", "build", "olap", "mine", "report",
        "audit", "tables", "serve", "config", "version",
    ]:
        assert command in result.stdout, f"{command} missing from the CLI"


@pytest.mark.parametrize("stage", STAGES)
def test_unbuilt_stage_fails_clearly(stage: str, tmp_path: Path) -> None:
    """Later phases must raise NotImplementedError, never ImportError."""
    result = runner.invoke(app, [stage, "--db", str(tmp_path / "x.duckdb")])
    assert result.exit_code != 0
    exc = result.exception
    assert exc is not None
    # NotImplementedError, not ImportError: the command surface is stable and
    # the failure names the phase that is still to be built.
    assert isinstance(exc, NotImplementedError), f"got {type(exc).__name__}: {exc}"
    assert "not built yet" in str(exc)


def test_etl_is_implemented_and_demands_staging(tmp_path: Path) -> None:
    """Implemented stages must fail on missing input, not on being a stub."""
    result = runner.invoke(app, ["etl", "--db", str(tmp_path / "x.duckdb")])
    assert result.exit_code != 0
    exc = result.exception
    assert isinstance(exc, RuntimeError), f"got {type(exc).__name__}: {exc}"
    assert "ingest" in str(exc)


@pytest.mark.parametrize(
    ("stage", "needed"),
    [("features", "etl"), ("build", "features")],
)
def test_implemented_stage_demands_its_prerequisite(
    stage: str, needed: str, tmp_path: Path
) -> None:
    result = runner.invoke(app, [stage, "--db", str(tmp_path / "x.duckdb")])
    assert result.exit_code != 0
    exc = result.exception
    assert isinstance(exc, RuntimeError), f"got {type(exc).__name__}: {exc}"
    assert needed in str(exc)


def test_tables_command_creates_a_warehouse(tmp_path: Path) -> None:
    db = tmp_path / "empty.duckdb"
    result = runner.invoke(app, ["tables", "--db", str(db)])
    assert result.exit_code == 0
    assert json.loads(result.stdout) == {}
    assert db.exists()


def test_audit_command_on_empty_warehouse(tmp_path: Path) -> None:
    db = tmp_path / "empty2.duckdb"
    result = runner.invoke(app, ["audit", "--db", str(db)])
    assert result.exit_code == 0
    assert json.loads(result.stdout) == []
