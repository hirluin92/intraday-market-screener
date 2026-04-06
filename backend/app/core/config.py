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
    pipeline_ingest_limit: int = Field(
        default=2500,
        ge=1,
        le=5000,
        description=(
            "Barre OHLCV da richiedere per simbolo/timeframe a ogni ciclo pipeline. "
            "Binance: ccxt resta ~1000 barre per chiamata. Yahoo: fino a ~2500/3500 barre (1d/1h); "
            "le=5000 evita di tagliare lo storico yfinance con df.tail(limit)."
        ),
    )
    pipeline_ingest_limit_5m: int = Field(
        default=10_000,
        ge=1,
        le=20_000,
        description=(
            "Yahoo Finance 5m: valore passato a ingest quando timeframe=5m (pipeline refresh); "
            "lo storico effettivo segue il periodo Yahoo (es. 60d) e non è più tagliato da tail su 5m."
        ),
    )
    pipeline_extract_limit: int = Field(
        default=5000,
        ge=1,
        le=10_000,
        description=(
            "Max barre per serie da processare in feature/context/pattern extraction. "
            "5000 permette di sfruttare tutto lo storico accumulato dopo ingest massivo. "
            "Abbassare a 1000–2000 se la pipeline è troppo lenta su hardware limitato."
        ),
    )
    pipeline_lookback: int = Field(
        default=50,
        ge=3,
        le=200,
        description=(
            "Finestra rolling per context extraction (regime, volatilità, espansione). "
            "50 barre dà una classificazione più stabile rispetto al default 20, "
            "specialmente su 1h e 1d dove 20 barre sono meno di un mese."
        ),
    )

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

    # Pattern alerts (Telegram/Discord) dopo estrazione pattern nel pipeline — vedi app.services.alert_service.
    alert_pattern_signals_enabled: bool = Field(
        default=True,
        description=(
            "Se true, dopo extract_patterns invia alert su pattern operativi (1h/5m) se canali configurati."
        ),
    )
    alert_min_quality_score: float = Field(
        default=55.0,
        ge=0.0,
        le=100.0,
        description="Score qualità backtest minimo (0–100) per inviare alert pattern.",
    )
    alert_min_strength: float = Field(
        default=0.60,
        ge=0.0,
        le=1.0,
        description="Pattern strength minima per inviare alert.",
    )
    alert_regime_filter: bool = Field(
        default=True,
        description="Se true, non inviare alert se direzione pattern non è allineata al regime SPY 1d.",
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


# ---------------------------------------------------------------------------
# NOTE OPERATIVE — storico massimo per provider:
#
# Binance (crypto):
#   fetch_ohlcv restituisce max 1000 barre per chiamata (ccxt default).
#   Con pipeline_ingest_limit=1000 si ottiene il massimo senza paginazione.
#   1h × 1000 barre = ~42 giorni; 1m × 1000 = ~17 ore.
#   Per storico più lungo su 1h/1d usare Yahoo Finance (ETF proxy o indici).
#
# Yahoo Finance (ETF/stock US):
#   1d: period="10y" → ~2500 barre (10 anni) — ottimo per backtest
#   1h: period="730d" → ~3500 barre (2 anni) — sufficiente per n>200 per pattern
#   5m: period="60d" → ~11700 barre (60 giorni) — buono per intraday
#   pipeline_ingest_limit su Yahoo taglia solo se < barre disponibili;
#   default 2500 e cap le=5000 per non perdere storico 1d/1h (~2500–3500 barre).
# ---------------------------------------------------------------------------


settings = Settings()
