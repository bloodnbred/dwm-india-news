"""FastAPI backend (Phase 8).

Built. The dashboard stays thin: Streamlit reads from these endpoints and holds
no logic of its own (BLUEPRINT section 1), so there is exactly one place where
a number is turned into a response.

Run it with `python -m dwm serve`, which starts uvicorn against
`dwm.api.app:app`.
"""

from __future__ import annotations

from dwm.api.app import app
from dwm.api.store import DataUnavailable

__all__ = ["app", "DataUnavailable", "create_app"]


def create_app():
    """Return the ASGI app.

    A factory rather than a bare module import, so a test can build an
    isolated instance and so the object is constructed explicitly instead of
    as an import side effect.
    """
    return app
