"""Application configuration.

All settings are read from environment variables (or a local ``.env`` file)
via ``pydantic-settings``. The application is designed to run fully
**without any API keys** (``mock`` provider defaults) so it can be evaluated
end-to-end offline; real providers are enabled simply by changing ``.env``.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app._version import __version__


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- LLM -----------------------------------------------------------------
    # One of: "mock" | "openai" | "anthropic"
    llm_provider: str = "mock"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-3-5-haiku-latest"
    llm_temperature: float = 0.2

    # --- Web search (mandatory research tool) --------------------------------
    # One of: "mock" | "serper" | "exa"
    web_search_provider: str = "mock"
    serper_api_key: str | None = None
    exa_api_key: str | None = None

    # --- Weather -------------------------------------------------------------
    # One of: "openmeteo" (free, keyless) | "mock"
    weather_provider: str = "openmeteo"

    # --- Storage / runtime ---------------------------------------------------
    storage_dir: str = "storage"
    database_path: str = "storage/planner.sqlite"
    request_timeout_seconds: float = Field(default=60.0, gt=0)
    max_revisions: int = Field(default=3, ge=1)
    max_agent_iterations: int = Field(default=6, ge=1)

    @property
    def app_name(self) -> str:
        return f"AI Travel Planner v{__version__}"

    @property
    def saver_connection_string(self) -> str:
        return self.database_path

    @property
    def effective_web_search_provider(self) -> str:
        """Auto-select serper/exa if configured, else gracefully use mock."""
        if self.web_search_provider in {"serper", "exa"} and getattr(
            self, f"{self.web_search_provider}_api_key", None
        ):
            return self.web_search_provider  # type: ignore[return-value]
        if self.web_search_provider in {"serper", "exa", "mock"}:
            return self.web_search_provider
        return "mock"


@lru_cache
def get_settings() -> Settings:
    return Settings()