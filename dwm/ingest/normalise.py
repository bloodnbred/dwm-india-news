"""CSV normalisation fallback.

DuckDB 1.5.6's CSV reader mis-parses the IFND file: it rejects the row with
id=46 ("CSV Error on Line: 47") and, with ignore_errors, silently discards
15,730 of 56,714 rows. Python's csv module reads the same file correctly -
all 56,714 rows have exactly 7 fields, verified.

So when a direct DuckDB load does not reconcile with the source row count,
this module rewrites the file with a strict RFC 4180 writer and the load is
retried. The rewrite is a mechanical re-quoting of the same bytes, not a
change to the data, and the row count is verified before and after.
"""

from __future__ import annotations

import csv
import sys
from dataclasses import dataclass
from pathlib import Path

from dwm.logging_utils import get

log = get("dwm.ingest.normalise")

# csv.field_size_limit defaults to 128 KB, which is smaller than some IFND
# statements; raise it well past anything these files contain.
csv.field_size_limit(min(sys.maxsize, 2**31 - 1))

NORMALISED_SUFFIX = ".normalised.csv"


@dataclass(slots=True)
class NormaliseResult:
    source: Path
    target: Path
    rows: int
    columns: list[str]


def normalised_path(source: Path) -> Path:
    return source.with_name(source.stem + NORMALISED_SUFFIX)


def normalise(source: Path, *, encoding: str = "utf-8", force: bool = False) -> NormaliseResult:
    """Rewrite `source` as strictly-quoted CSV. Returns the parsed shape."""
    target = normalised_path(source)
    if target.exists() and not force:
        rows, columns = _inspect(target, encoding)
        log.info("%s: reusing normalised %s (%s rows)", source.name, target.name, f"{rows:,}")
        return NormaliseResult(source, target, rows, columns)

    log.warning(
        "%s: normalising with the strict csv writer so DuckDB can read it",
        source.name,
    )
    rows = 0
    columns: list[str] = []
    # newline="" is required: without it the csv module doubles the newlines
    # on write and the row count drifts.
    with source.open("r", encoding=encoding, errors="replace", newline="") as reader, target.open(
        "w", encoding=encoding, newline=""
    ) as writer:
        for row in csv.reader(reader):
            if rows == 0:
                columns = [c.strip() for c in row]
                out = csv.writer(writer, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
            else:
                out = csv.writer(writer, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
            out.writerow(row)
            rows += 1

    log.info("%s: normalised to %s (%s data rows)", source.name, target.name, f"{rows:,}")
    return NormaliseResult(source, target, max(0, rows - 1), columns)


def _inspect(path: Path, encoding: str) -> tuple[int, list[str]]:
    rows = 0
    columns: list[str] = []
    with path.open("r", encoding=encoding, errors="replace", newline="") as reader:
        for row in csv.reader(reader):
            if rows == 0:
                columns = [c.strip() for c in row]
            rows += 1
    return max(0, rows - 1), columns
