"""Application configuration.

All settings can be overridden through environment variables (or a `.env` file
next to the process working directory). See `.env.example` at the repository
root for the documented variables.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- core -------------------------------------------------------------
    app_name: str = "Bozii"
    environment: str = "development"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    database_url: str = "sqlite+aiosqlite:///./var/bozii.db"
    data_dir: Path = Path("./var")
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    log_level: str = "INFO"
    secret_key: str = "dev-only-insecure-secret-change-me"

    # --- auth -------------------------------------------------------------
    session_cookie: str = "bozii_session"
    session_ttl_hours: int = 72
    allow_signup: bool = True
    auth_rate_limit_per_minute: int = 20
    rate_limit_per_minute: int = 600

    # --- task execution ---------------------------------------------------
    task_workers: int = 2
    max_iterations: int = 24
    task_timeout_seconds: int = 900
    model_timeout_seconds: int = 120
    tool_timeout_seconds: int = 120
    max_subtasks: int = 20
    max_delegation_depth: int = 3
    max_concurrent_tasks: int = 4
    task_planning: bool = True
    restart_interrupted_tasks: bool = True
    max_task_attempts: int = 2

    # --- sandbox ----------------------------------------------------------
    sandbox_timeout_seconds: int = 60
    sandbox_memory_mb: int = 1024
    sandbox_cpu_seconds: int = 60
    sandbox_network_isolation: bool = True
    sandbox_user: str = "nobody"
    allowed_commands: str = (
        "python,python3,pytest,node,npm,npx,bun,git,ls,cat,grep,rg,find,head,tail,wc,"
        "mkdir,cp,mv,tar,zip,unzip,sort,uniq,diff,sed,awk,echo,pwd,test,true,false,"
        "jq,curl,wget,make,gcc,g++,bash,sh"
    )

    # --- capabilities -----------------------------------------------------
    capability_dep_allowlist: str = ""
    capability_auto_activate: bool = True
    max_capability_versions: int = 20
    capability_test_timeout_seconds: int = 90

    # --- advertising (never sent to model context) ------------------------
    enable_ads: bool = False
    ads_provider: str = ""
    ads_slot_id: str = ""
    ads_placement: str = "dashboard_footer"

    # --- web tool provider ------------------------------------------------
    search_provider: str = "duckduckgo"
    searxng_url: str = ""
    search_api_key_env: str = ""
    web_fetch_max_bytes: int = 2_000_000

    # --- misc -------------------------------------------------------------
    ads_network_enabled: bool = True

    # ------------------------------------------------------------------ #
    # Derived helpers
    # ------------------------------------------------------------------ #
    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def allowed_command_list(self) -> list[str]:
        return [c.strip() for c in self.allowed_commands.split(",") if c.strip()]

    @property
    def capability_dep_allowlist_list(self) -> list[str]:
        return [d.strip().lower() for d in self.capability_dep_allowlist.split(",") if d.strip()]

    @property
    def root_dir(self) -> Path:
        return self.data_dir

    @property
    def workspace_dir(self) -> Path:
        return self.data_dir / "workspaces"

    @property
    def artifact_dir(self) -> Path:
        return self.data_dir / "artifacts"

    @property
    def capability_dir(self) -> Path:
        return self.data_dir / "capabilities"

    @property
    def tmp_dir(self) -> Path:
        return self.data_dir / "tmp"

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"production", "prod"}

    def ensure_dirs(self) -> None:
        for path in (
            self.data_dir,
            self.workspace_dir,
            self.artifact_dir,
            self.capability_dir,
            self.tmp_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings() -> None:
    """Clear the settings cache (used by tests when environment changes)."""
    get_settings.cache_clear()


__all__ = ["Settings", "get_settings", "reset_settings"]
