from __future__ import annotations

import logging
from pathlib import Path

import keyring
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger(__name__)

_KEYCHAIN_SERVICE = "savage-health-center"
_KEYCHAIN_DB_KEY_ACCOUNT = "db-encryption-key"


def _load_db_encryption_key() -> str | None:
    """Prefer macOS Keychain; fall back to env-loaded value if present.

    Storing the key in `.env` is supported for migration but discouraged — set
    it once via ``security add-generic-password -s savage-health-center -a
    db-encryption-key -w <key>`` and remove it from `.env`.
    """
    try:
        kc = keyring.get_password(_KEYCHAIN_SERVICE, _KEYCHAIN_DB_KEY_ACCOUNT)
    except Exception as exc:
        log.warning("keychain lookup failed: %s", exc)
        kc = None
    return kc

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

    # Obsidian vault path — "vault" always refers to this knowledge graph
    vault_path: Path = Field(default=Path.home() / "Vault/savage_vault")

    # Fitbod CSV export path (defaults to iCloud location, override via FITBOD_CSV_PATH env var)
    fitbod_csv_path: Path = Field(
        default=Path.home() / "Library/Mobile Documents/com~apple~CloudDocs/Health Data/Fitness Data/WorkoutExport.csv"
    )

    # Security — prefer Keychain over .env (see _load_db_encryption_key)
    db_encryption_key: str | None = Field(default_factory=_load_db_encryption_key)

    # WHOOP OAuth
    whoop_client_id: str | None = Field(default=None)
    whoop_client_secret: str | None = Field(default=None)
    whoop_redirect_uri: str = "http://127.0.0.1:8000/auth/whoop/callback"

    # Hevy
    hevy_api_key: str | None = Field(default=None)

    # Apple Health webhook (HAE / Shortcuts)
    # Generate with: python -c "import secrets; print(secrets.token_urlsafe(32))"
    apple_webhook_key: str | None = Field(default=None)

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    frontend_origin: str = "http://localhost:3000"
    # Tailscale hostname (e.g. "my-mac.tail1234.ts.net") — added to allowed Host headers
    # so Health Auto Export can POST from iPhone over Tailscale.
    tailscale_host: str | None = Field(default=None)


settings = Settings()
