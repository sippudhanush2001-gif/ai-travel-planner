"""FastAPI application factory.

Run with:  uvicorn app.main:app --reload
"""

from __future__ import annotations

from fastapi import FastAPI

from app._version import __version__
from app.api.routes import router
from app.config import Settings, get_settings
from app.runtime.manager import WorkflowManager


def create_app(
    settings: Settings | None = None,
    manager: WorkflowManager | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    manager = manager or WorkflowManager(settings)

    app = FastAPI(
        title="AI Travel Planner",
        description=(
            "Multi-agent AI travel planning with human-in-the-loop approval. "
            "POST /plan to start, review drafts, then fetch the finalized plan."
        ),
        version=__version__,
    )
    app.state.settings = settings
    app.state.manager = manager
    app.include_router(router)
    return app


app = create_app()

__all__ = ["app", "create_app"]