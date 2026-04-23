from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Paths — anchored to backend/ so cwd doesn't matter
    data_dir: Path = Field(default=_BACKEND_ROOT / "data")

    @property
    def db_path(self) -> Path:
        return self.data_dir / "shc.duckdb"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def source_docs_dir(self) -> Path:
        return self.data_dir / "source_docs"

    @property
    def hae_dir(self) -> Path:
        """HealthAutoExport iCloud drop folder."""
        return self.data_dir / "hae"

    # Fitbod CSV export path (defaults to iCloud location, override via FITBOD_CSV_PATH env var)
    fitbod_csv_path: Path = Field(
        default=Path.home() / "Library/Mobile Documents/com~apple~CloudDocs/Health Data/Fitness Data/WorkoutExport.csv"
    )

    # Security
    db_encryption_key: str | None = Field(default=None)

    # WHOOP OAuth
    whoop_client_id: str | None = Field(default=None)
    whoop_client_secret: str | None = Field(default=None)
    whoop_redirect_uri: str = "http://127.0.0.1:8000/auth/whoop/callback"

    # Hevy
    hevy_api_key: str | None = Field(default=None)

    # Anthropic
    anthropic_api_key: str | None = Field(default=None)
    anthropic_daily_cap_usd: float = Field(default=2.00)

    # LLM kill-switch: "local_only" forces Ollama regardless of router
    shc_llm_mode: str = Field(default="auto")

    # Ollama
    ollama_base_url: str = Field(default="http://127.0.0.1:11434")
    ollama_model: str = Field(default="llama3.3:70b")

    # Server
    host: str = "127.0.0.1"
    port: int = 8000
    frontend_origin: str = "http://localhost:3000"


settings = Settings()
