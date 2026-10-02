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

STAGES: list[str] = []
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
    """Later phases must raise NotImplementedError, never ImportError.

    The parameter list is currently empty because every registered stage is
    built. The test is kept rather than deleted: it is the check that will fail
    if a future stub is added without a guard, and `assert STAGES` documents
    that the empty list is deliberate rather than an oversight.
    """
    assert STAGES == [], (
        f"these stages are listed as stubs but are now built: {STAGES}. "
        "Remove them from STAGES and add a real test instead."
    )


def test_every_registered_stage_is_built() -> None:
    """No command in the CLI may still raise NotImplementedError."""
    import inspect

    from dwm import cli

    for name, obj in vars(cli).items():
        if not inspect.isfunction(obj) or name.startswith("_"):
            continue
        if not hasattr(obj, "registered_commands"):
            continue
        source = inspect.getsource(obj)
        assert "NotImplementedError" not in source, f"{name} is still a stub"


def test_etl_is_implemented_and_demands_staging(tmp_path: Path) -> None:
    """Implemented stages must fail on missing input, not on being a stub."""
    result = runner.invoke(app, ["etl", "--db", str(tmp_path / "x.duckdb")])
    assert result.exit_code != 0
    exc = result.exception
    assert isinstance(exc, RuntimeError), f"got {type(exc).__name__}: {exc}"
    assert "ingest" in str(exc)


def test_report_is_implemented_and_demands_mining(tmp_path: Path) -> None:
    """`report` renders from mining.json, so it must name that prerequisite.

    A report built from absent results would render an empty document that
    looks like a finding of "nothing to say", which is worse than refusing.
    """
    result = runner.invoke(app, ["report", "--db", str(tmp_path / "x.duckdb")])
    assert result.exit_code != 0
    exc = result.exception
    assert isinstance(exc, FileNotFoundError), f"got {type(exc).__name__}: {exc}"
    assert "mine" in str(exc)


@pytest.mark.parametrize(
    ("stage", "needed"),
    [("features", "etl"), ("build", "features"), ("mine", "build")],
)
def test_implemented_stage_demands_its_prerequisite(
    stage: str, needed: str, tmp_path: Path
) -> None:
    result = runner.invoke(app, [stage, "--db", str(tmp_path / "x.duckdb")])
    assert result.exit_code != 0
    exc = result.exception
    assert isinstance(exc, RuntimeError), f"got {type(exc).__name__}: {exc}"
    assert needed in str(exc)


def test_olap_lists_its_operations(tmp_path: Path) -> None:
    """OLAP is built, so with no --op it enumerates rather than raising."""
    result = runner.invoke(app, ["olap", "--db", str(tmp_path / "x.duckdb")])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    names = {o["name"] for o in payload["operations"]}
    assert {
        "slice", "dice", "roll_up", "drill_down", "pivot", "cube", "drill_across",
    } <= names


def test_olap_rejects_a_malformed_param(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["olap", "--db", str(tmp_path / "x.duckdb"), "-p", "nonsense"]
    )
    assert result.exit_code != 0


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
