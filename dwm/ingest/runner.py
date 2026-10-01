"""Ingest orchestration: fetch a dataset, then stage it, then audit it.

The audit row is written whether the stage succeeded or failed, so a broken
run leaves a visible trail instead of no trace.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dwm.config import DatasetSpec, Settings, load_datasets_config
from dwm.db import connect
from dwm.ingest import audit
from dwm.ingest.fetch import FetchError, FetchResult, fetch_dataset
from dwm.ingest.staging import stage_dataset, stage_table_name
from dwm.logging_utils import get, human_int, step

log = get("dwm.ingest")


@dataclass(slots=True)
class IngestOutcome:
    code: str
    fetch: FetchResult | None
    staging: dict[str, Any]
    audit_ids: list[int]
    ok: bool
    error: str | None = None


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def ingest_one(
    spec: DatasetSpec,
    settings: Settings,
    *,
    force_download: bool = False,
    skip_fetch: bool = False,
) -> IngestOutcome:
    """Fetch and stage one dataset, writing audit rows as it goes."""
    con = connect(settings)
    run_id = audit.new_run_id()
    audit.ensure_audit_table(con)
    ids: list[int] = []
    fetch_result: FetchResult | None = None

    try:
        if skip_fetch and spec.local_path().exists():
            log.info("%s: skipping fetch, using %s", spec.code, spec.local_path())
            fetch_result = None
        else:
            started = _now()
            with step(f"fetch {spec.code}") as info:
                fetch_result = fetch_dataset(spec, force=force_download)
                info.update(
                    bytes_downloaded=fetch_result.bytes_downloaded,
                    sha256=fetch_result.sha256,
                    reused=fetch_result.reused,
                    source_file=spec.filename,
                )
            ids.append(
                audit.record(
                    con, run_id=run_id, dataset_code=spec.code, step="ingest.fetch",
                    info=info, status=info["status"], started_at=started,
                )
            )

        path = spec.local_path()
        if not path.exists():
            raise FileNotFoundError(f"{spec.code}: expected {path}")

        started = _now()
        with step(f"stage {spec.code} -> {stage_table_name(spec.code)}") as info:
            info.update(stage_dataset(con, spec, path, settings=settings))
        ids.append(
            audit.record(
                con, run_id=run_id, dataset_code=spec.code, step="ingest.stage",
                info=info, status=info["status"], started_at=started,
            )
        )
        return IngestOutcome(spec.code, fetch_result, info, ids, ok=True)

    except (FetchError, FileNotFoundError, KeyError) as exc:
        log.error("%s: ingest failed: %s", spec.code, exc)
        started = _now()
        info = {"error": str(exc)}
        try:
            ids.append(
                audit.record(
                    con, run_id=run_id, dataset_code=spec.code, step="ingest.stage",
                    info=info, status="failed", started_at=started,
                )
            )
        except Exception:  # pragma: no cover - audit must never mask the cause
            log.exception("could not write failure audit row for %s", spec.code)
        return IngestOutcome(spec.code, fetch_result, info, ids, ok=False, error=str(exc))
    finally:
        con.close()


def ingest(
    settings: Settings, *, datasets: list[str] | None = None, force_download: bool = False,
    skip_fetch: bool = False,
) -> list[IngestOutcome]:
    """Ingest the requested datasets, defaulting to every enabled one."""
    specs = load_datasets_config()
    wanted = datasets or sorted(specs)
    unknown = [code for code in wanted if code not in specs]
    if unknown:
        raise KeyError(f"unknown dataset(s) {unknown}; known: {sorted(specs)}")

    outcomes: list[IngestOutcome] = []
    for code in wanted:
        spec = specs[code]
        if not spec.enabled and datasets is None:
            log.info("%s: disabled in config, skipping", code)
            continue
        outcome = ingest_one(
            spec, settings, force_download=force_download, skip_fetch=skip_fetch
        )
        outcomes.append(outcome)
        if outcome.ok:
            loaded = outcome.staging.get("rows_loaded", 0)
            log.info("%s: staged %s rows", code, human_int(int(loaded)))
    return outcomes


def load_raw(
    settings: Settings, datasets: list[str] | None = None
) -> dict[str, Path]:
    """Paths of raw files already present, without downloading anything."""
    specs = load_datasets_config()
    found: dict[str, Path] = {}
    for code, spec in specs.items():
        if datasets and code not in datasets:
            continue
        path: Path = spec.local_path()
        if path.exists():
            found[code] = path
        else:
            log.warning("%s: no raw file at %s", code, path)
    return found
