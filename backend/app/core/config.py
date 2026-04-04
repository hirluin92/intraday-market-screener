from urllib.parse import quote_plus

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = "development"
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000

    sqlalchemy_echo: bool = False

    database_url: str | None = None
    postgres_user: str = "postgres"
    postgres_password: str = "postgres"
    postgres_db: str = "intraday_market_screener"
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    # In-process pipeline scheduler (APScheduler); see ``app.scheduler.pipeline_scheduler``.
    pipeline_scheduler_enabled: bool = False
    pipeline_refresh_interval_seconds: int = Field(
        default=300,
        ge=1,
        le=86400,
        description="How often to run the full ingest→extract pipeline for each configured pair.",
    )
    pipeline_scheduler_source: str = Field(
        default="universe",
        description=(
            "universe = cross-market jobs from app.core.market_universe; "
            "legacy = Binance-only grid from PIPELINE_SYMBOLS × PIPELINE_TIMEFRAMES."
        ),
    )
    pipeline_universe_tags: str = Field(
        default="",
        description=(
            "Comma-separated tags (case-insensitive). When non-empty, each listed tag must "
            "be present on the registry entry (AND). Use etf or yahoo_etf for Yahoo ETF-only; "
            "yahoo alone selects all Yahoo instruments. See market_universe.iter_scheduler_jobs."
        ),
    )
    pipeline_symbols: str = Field(
        default="",
        description="(legacy mode only) Comma-separated pairs (e.g. BTC/USDT,ETH/USDT). Empty = default symbols.",
    )
    pipeline_timeframes: str = Field(
        default="",
        description="(legacy mode only) Comma-separated (e.g. 1m,5m,15m). Empty = default timeframes.",
    )
    pipeline_ingest_limit: int = Field(default=100, ge=1, le=1500)
    pipeline_extract_limit: int = Field(default=500, ge=1, le=10_000)
    pipeline_lookback: int = Field(default=20, ge=3, le=200)

    # Comma-separated origins for browser clients (e.g. Next.js on another port).
    cors_origins: str = Field(
        default="http://localhost:3000",
        description="Allowed CORS origins for the API (comma-separated).",
    )

    # Outbound alerts (v1): alta_priorita only; see app.services.alert_notifications.
    alert_notifications_enabled: bool = Field(
        default=False,
        description="If true, send notifications after pipeline refresh when rules match.",
    )
    alert_frontend_base_url: str = Field(
        default="",
        description=(
            "Base URL for serie detail links in alerts (no trailing slash), "
            "e.g. http://localhost:3000"
        ),
    )
    discord_webhook_url: str = Field(
        default="",
        description="Discord incoming webhook URL (optional).",
    )
    telegram_bot_token: str = Field(
        default="",
        description="Telegram Bot API token (optional).",
    )
    telegram_chat_id: str = Field(
        default="",
        description="Telegram chat id for sendMessage (optional).",
    )

    @property
    def cors_origins_list(self) -> list[str]:
        parts = [x.strip() for x in self.cors_origins.split(",") if x.strip()]
        return parts if parts else ["http://localhost:3000"]

    @property
    def database_url_effective(self) -> str:
        """Async SQLAlchemy URL (postgresql+asyncpg)."""
        if self.database_url:
            return self.database_url
        user = quote_plus(self.postgres_user)
        password = quote_plus(self.postgres_password)
        return (
            f"postgresql+asyncpg://{user}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


settings = Settings()
