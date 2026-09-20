"""FastAPI dependency helpers."""

from __future__ import annotations

from fastapi import Request

from app.runtime.manager import WorkflowManager


def get_manager(request: Request) -> WorkflowManager:
    return request.app.state.manager


def get_settings_obj(request: Request):
    return request.app.state.settings