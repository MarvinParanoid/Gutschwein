from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Telegram
    bot_token: str = ""
    # Who may use the app: comma-separated telegram ids.
    allowed_telegram_ids: str = ""
    # Where the bot posts notifications (usually the family chat id). Empty = silent.
    family_chat_id: int | None = None
    # Public https URL of the Mini App, needed for the bot's WebApp button.
    webapp_url: str = ""
    run_bot: bool = True

    # Data
    database_url: str = "sqlite+aiosqlite:///./data/sparschwein.db"
    data_dir: Path = Path("./data")
    # Hour (UTC) of the nightly backup into FAMILY_CHAT_ID.
    backup_hour_utc: int = 4
    # Weekly digest: Sunday evening, before the week's shopping starts.
    digest_weekday: int = 6  # Monday is 0
    digest_hour_utc: int = 17

    # Security
    init_data_max_age: int = 24 * 3600
    # Local development without Telegram: enables the X-Dev-User header.
    dev_mode: bool = False

    cors_origins: str = ""

    @field_validator("family_chat_id", mode="before")
    @classmethod
    def empty_means_unset(cls, value: object) -> object:
        """`FAMILY_CHAT_ID=` in .env arrives as "", which is not an int."""
        return None if value == "" else value

    @property
    def allowed_ids(self) -> set[int]:
        return {
            int(chunk)
            for chunk in (c.strip() for c in self.allowed_telegram_ids.split(","))
            if chunk
        }

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    return settings


settings = get_settings()
