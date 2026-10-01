"""Console logging shared by the CLI and the pipeline stages.

Deliberately simple: one human-readable line per step, plus a machine-readable
summary that the stages use when writing etl_audit. Audit numbers never come
from log text, they come from returned values.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from time import perf_counter

_CONFIGURED = False


def setup(level: str = "INFO") -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s | %(message)s", "%H:%M:%S"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    _CONFIGURED = True


def get(name: str) -> logging.Logger:
    setup()
    return logging.getLogger(name)


@contextmanager
def step(name: str, logger: logging.Logger | None = None) -> Iterator[dict]:
    """Time a pipeline step and report the outcome.

    Yields a mutable dict; anything written to it lands in etl_audit. On an
    exception the step is logged as failed and the exception propagates, so a
    broken stage can never look like a clean one.
    """
    log = logger or get("dwm")
    info: dict = {}
    start = perf_counter()
    log.info("--> %s", name)
    try:
        yield info
    except Exception:
        info["status"] = "failed"
        info["elapsed_s"] = round(perf_counter() - start, 3)
        log.exception("!!! %s failed after %.2fs", name, info["elapsed_s"])
        raise
    info["status"] = "ok"
    info["elapsed_s"] = round(perf_counter() - start, 3)
    log.info("<-- %s ok in %.2fs", name, info["elapsed_s"])


def human_int(value: int) -> str:
    return f"{value:,}"
