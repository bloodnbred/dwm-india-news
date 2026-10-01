"""Ingest stage: fetch raw CSVs and land them in the DuckDB staging tables."""

from dwm.ingest.runner import IngestOutcome, ingest, ingest_one, load_raw

__all__ = ["IngestOutcome", "ingest", "ingest_one", "load_raw"]
