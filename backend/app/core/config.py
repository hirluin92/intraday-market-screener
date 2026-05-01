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
        description="How often to run the full ingest→extract pipeline for each configured pair. Ignored when pipeline_scheduler_align_to_5m=true.",
    )
    pipeline_scheduler_align_to_5m: bool = Field(
        default=False,
        description=(
            "Se True, usa un trigger cron allineato alle chiusure delle candele 5m "
            "(XX:00:10, XX:05:10, ..., XX:55:10) invece del polling ogni N secondi. "
            "Riduce la latenza media da ~150s a ~10s per i segnali 5m e 1h. "
            "I simboli 1h saltano l'extraction 11/12 cicli grazie a skip_if_unchanged "
            "(nessuna candela nuova fuori dai boundary dell'ora) — carico DB invariato. "
            "Richiede ALPACA_ENABLED=true e/o TWS_ENABLED=true per dati 5m real-time."
        ),
    )
    pipeline_scheduler_cron_offset_s: int = Field(
        default=10,
        ge=0,
        le=59,
        description=(
            "Secondi di attesa dopo il boundary 5m prima di avviare il ciclo pipeline "
            "(buffer per ricezione dati dal provider). "
            "Default 10s: sufficiente per IBKR TWS e Alpaca REST (dati disponibili <5s dalla chiusura). "
            "Usato in modalità unified (align_to_5m=true) e split."
        ),
    )
    pipeline_scheduler_mode: str = Field(
        default="unified",
        description=(
            "Modalità scheduler pipeline: "
            "'unified' = un solo job APScheduler per tutti i simboli (cron o interval); "
            "'split' = due job separati: 'pipeline_1h' (cron XX:01:00, timeframe 1h+1d) e "
            "'pipeline_5m' (cron XX:00:10…XX:55:10, timeframe 5m). "
            "In split mode il parallelismo è 6 per ciclo (vs 12 in unified) per non saturare "
            "il pool DB se i due cicli si sovrappongono (~50s di finestra a ogni ora). "
            "Richiede ALPACA_ENABLED=true o TWS_ENABLED=true per dati 5m real-time."
        ),
    )
    pipeline_scheduler_source: str = Field(
        default="explicit",
        description=(
            "explicit | validated_1h | universe = stessa lista esplicita 40 Yahoo 1h + 5 Binance 1h "
            "(trade_plan_variant_constants); registry_full = espansione completa market_universe + tag; "
            "legacy = Binance-only da PIPELINE_SYMBOLS × PIPELINE_TIMEFRAMES."
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
            "Yahoo Finance 5m/15m: valore passato a ingest quando timeframe è 5m o 15m (pipeline refresh); "
            "lo storico effettivo segue il periodo Yahoo (es. 60d) e non è più tagliato da tail su intraday."
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

    opportunity_lookup_cache_ttl_seconds: int = Field(
        default=600,
        ge=30,
        le=86_400,
        description=(
            "TTL secondi per pattern_quality_cache (invalidata dopo ogni pipeline refresh). "
            "Usato anche come fallback se backtest_cache_ttl_seconds non è impostato."
        ),
    )

    backtest_cache_ttl_seconds: int = Field(
        default=3600,
        ge=300,
        le=86_400,
        description=(
            "TTL secondi per trade_plan_backtest_cache e variant_best_cache. "
            "Questi lookup sono storici (2+ anni di dati) e non cambiano con nuovi candle: "
            "TTL lungo evita ricalcoli bloccanti (~70s+20s) ad ogni ciclo pipeline."
        ),
    )

    opportunity_price_staleness_pct: float = Field(
        default=1.0,
        ge=0.0,
        le=50.0,
        description=(
            "Soglia % di distanza prezzo vs entry: oltre questa soglia un execute "
            "viene declassato a monitor (ultimo close candela nel DB)."
        ),
    )

    equity_provider_1h: str = Field(
        default="ibkr",
        description=(
            "Provider per l'ingestione candele 1h dei 40 simboli azionari USA: "
            "'ibkr' (default) = IBKR TWS reqHistoricalData (abbonamenti NASDAQ/NYSE/ARCA richiesti); "
            "'yahoo_finance' = fallback yfinance (soggetto a timeout sistematici). "
            "Non influenza Binance (crypto) né Alpaca (5m azionari)."
        ),
    )

    # Alerting legacy (pipeline refresh → Discord/Telegram; vedi app.services.alert_notifications).
    alert_legacy_enabled: bool = Field(
        default=False,
        description=(
            "Se True, esegue il flusso legacy maybe_notify_after_pipeline_refresh. "
            "Default False: solo gli alert pattern (alert_service / pattern_pipeline_alerts)."
        ),
    )
    # Stesso file legacy; richiede anche canali configurati e (in passato) questa flag era l'unico switch.
    alert_notifications_enabled: bool = Field(
        default=False,
        description="If true, send notifications after pipeline refresh when rules match.",
    )
    alert_include_media_priorita: bool = Field(
        default=False,
        description=(
            "Se True invia anche alert di media priorità (default False in produzione)"
        ),
    )
    alert_frontend_base_url: str = Field(
        default="http://localhost:3000",
        description=(
            "Base URL frontend per deep link opportunità / serie negli alert (no trailing slash), "
            "es. http://localhost:3000"
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
        default=0.70,
        ge=0.0,
        le=1.0,
        description="Pattern strength minima per inviare alert.",
    )
    alert_regime_filter: bool = Field(
        default=True,
        description="Se true, non inviare alert se la direzione non è allineata al regime daily (SPY su Yahoo, BTC/USDT su Binance).",
    )
    notify_order_events_enabled: bool = Field(
        default=True,
        description=(
            "Se True, invia notifica Telegram/Discord quando un bracket order viene confermato "
            "da TWS (tws_status=submitted) e quando un trade si chiude (stop/TP/timeout). "
            "Indipendente da alert_pattern_signals_enabled — per ricevere solo notifiche ordini "
            "impostare ALERT_PATTERN_SIGNALS_ENABLED=false e NOTIFY_ORDER_EVENTS_ENABLED=true. "
            "Richiede almeno un canale configurato (DISCORD_WEBHOOK_URL o TELEGRAM_*)."
        ),
    )

    # IBKR Client Portal Gateway (localhost) — esecuzione ordini
    ibkr_enabled: bool = Field(
        default=False,
        description="Abilita integrazione IBKR Client Portal API.",
    )
    ibkr_paper_trading: bool = Field(
        default=True,
        description="True = paper trading; False = conto reale (richiede approvazione esplicita).",
    )
    ibkr_gateway_url: str = Field(
        default="https://localhost:5000/v1/api",
        description="Base URL API REST del gateway (tipicamente /v1/api).",
    )
    ibkr_gateway_host_header: str = Field(
        default="",
        description=(
            "Se non vuoto, invia questo valore come header HTTP Host (es. localhost:5000). "
            "Utile con Docker → host.docker.internal se il gateway si aspetta Host localhost."
        ),
    )
    ibkr_debug: bool = Field(
        default=False,
        description="Se true, abilita GET /api/v1/ibkr/debug/auth (risposta grezza dal gateway).",
    )
    ibkr_account_id: str = Field(
        default="",
        description="Account ID IBKR (es. DU… per paper).",
    )
    ibkr_auto_execute: bool = Field(
        default=False,
        description="Se true, tenta ordini automatici dopo pipeline (solo se ibkr_enabled).",
    )
    ibkr_margin_account: bool = Field(
        default=False,
        description="Se true, conto margin (short permessi). Cash account → false: auto-execute skippa segnali bearish/short.",
    )
    ibkr_max_risk_per_trade_pct: float = Field(
        default=0.5,
        ge=0.01,
        le=100.0,
        description="Rischio massimo per trade come % del capitale allocato (position sizing). Usato come fallback se ibkr_risk_pct_1h/5m non impostati.",
    )
    ibkr_risk_pct_1h: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Risk % per trade 1h. Se > 0 sovrascrive ibkr_max_risk_per_trade_pct per i segnali 1h. 0 = usa il valore base.",
    )
    ibkr_risk_pct_5m: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Risk % per trade 5m. Se > 0 sovrascrive ibkr_max_risk_per_trade_pct per i segnali 5m. 0 = usa il valore base.",
    )
    ibkr_max_capital: float = Field(
        default=2269.0,
        gt=0.0,
        description="Capitale massimo (notional) da usare per sizing IBKR.",
    )
    ibkr_max_simultaneous_positions: int = Field(
        default=5,
        ge=1,
        le=100,
        description=(
            "Massimo posizioni totali aperte contemporanee (cap globale). "
            "Con slot separation (ibkr_slots_1h + ibkr_slots_5m), il totale e' sempre <= questo valore."
        ),
    )
    ibkr_slots_1h: int = Field(
        default=3,
        ge=1,
        le=5,
        description=(
            "Slot dedicati ai trade 1h (Strategy E: slot separation 3+2). "
            "Il 1h puo' usare slot 5m se i suoi 3 sono pieni e quelli 5m sono liberi. "
            "Il 5m NON puo' usare slot 1h."
        ),
    )
    ibkr_slots_5m: int = Field(
        default=2,
        ge=1,
        le=5,
        description=(
            "Slot dedicati ai trade 5m (Strategy E: slot separation 3+2). "
            "Il 1h puo' prenderli in prestito se i suoi 3 slot sono pieni."
        ),
    )
    eod_close_enabled: bool = Field(
        default=True,
        description=(
            "Se True, il job APScheduler chiude tutte le posizioni aperte e cancella "
            "gli ordini pendenti alle 15:55 ET (lun–ven). Richiede TWS_ENABLED=true."
        ),
    )
    ibkr_max_spread_pct: float = Field(
        default=0.5,
        ge=0.0,
        le=10.0,
        description=(
            "Spread bid/ask massimo tollerato (% del mid-price) per un segnale 'execute'. "
            "Se spread > soglia, il segnale viene retrocesso a 'monitor' per cattiva liquidità. "
            "0.0 = filtro disabilitato (default se IBKR non configurato). "
            "Valori tipici: 0.3 (liquidi) – 0.8 (small cap). "
            "Richede IBKR_ENABLED=true e Gateway autenticato."
        ),
    )

    # ── TWS (Trader Workstation) API ──────────────────────────────────────────
    tws_enabled: bool = Field(
        default=False,
        description=(
            "Abilita connessione diretta a IBKR Trader Workstation (ib_insync). "
            "Richiede TWS aperto con API socket abilitata. "
            "Fornisce bid/ask streaming, market depth Level 2 e storico bid/ask. "
            "Se false (default), il sistema usa solo Client Portal REST."
        ),
    )
    tws_host: str = Field(
        default="host.docker.internal",
        description="Host TWS (host.docker.internal da Docker, localhost da locale).",
    )
    tws_port: int = Field(
        default=7497,
        description="Porta TWS API (7497 paper trading, 7496 live).",
    )
    tws_client_id: int = Field(
        default=10,
        ge=1,
        description=(
            "Client ID per la connessione TWS API. "
            "Deve essere diverso da quello usato da altri client (es. TWS stesso usa 0). "
            "Scegli qualsiasi intero >= 1 non già in uso."
        ),
    )

    # ── Auto-execute: timeframe e provider operativi ──────────────────────────
    # Separatore: virgola. Default conservativo: solo 1h (validato da Strada A).
    # 5m è esplicitamente escluso finché non esiste un validation set 5m con
    # metriche WR e avg_R misurate out-of-sample, analogo a quello 1h esistente.
    auto_execute_timeframes_enabled: str = Field(
        default="1h",
        description=(
            "Timeframe abilitati per auto-execute (comma-separated). "
            "Default: '1h' (validato empiricamente da Strada A). "
            "5m escluso di default: nessun dataset OOS disponibile. "
            "Aggiungere '5m' solo dopo aver costruito e validato un dataset 5m."
        ),
    )
    auto_execute_providers_enabled: str = Field(
        default="yahoo_finance,binance",
        description=(
            "Provider abilitati per auto-execute (comma-separated). "
            "Default: 'yahoo_finance,binance'. "
            "Rimuovere 'binance' se non si vuole eseguire automaticamente crypto."
        ),
    )

    @property
    def auto_execute_timeframes_list(self) -> list[str]:
        return [x.strip() for x in self.auto_execute_timeframes_enabled.split(",") if x.strip()]

    @property
    def auto_execute_providers_list(self) -> list[str]:
        return [x.strip() for x in self.auto_execute_providers_enabled.split(",") if x.strip()]

    # ── Alpaca Markets (storico 5m US stocks) ─────────────────────────────────
    alpaca_enabled: bool = Field(
        default=False,
        description=(
            "Abilita provider Alpaca per ingestion OHLCV US stocks (5m/15m/1h/1d). "
            "Richiede alpaca_api_key e alpaca_api_secret validi. "
            "Alpaca free tier (IEX feed): storico ~2-3 anni su 5m — "
            "ideale per validazione pattern intraday che Yahoo Finance non può fornire (max 60 giorni su 5m)."
        ),
    )
    alpaca_api_key: str = Field(
        default="",
        description="Alpaca API Key ID (da https://app.alpaca.markets → Paper o Live).",
    )
    alpaca_api_secret: str = Field(
        default="",
        description="Alpaca API Secret Key.",
    )
    alpaca_base_url: str = Field(
        default="https://data.alpaca.markets/v2",
        description=(
            "Base URL Alpaca Data API v2. "
            "Default: SIP feed (richiede abbonamento Live). "
            "Paper account: usa stesso endpoint, dati IEX feed via alpaca_feed=iex."
        ),
    )
    alpaca_feed: str = Field(
        default="iex",
        description=(
            "Feed dati Alpaca: 'iex' (free, dati IEX) o 'sip' (paid, dati SIP National Best Bid/Offer). "
            "Con account paper/free usare 'iex'."
        ),
    )
    alpaca_backfill_years: int = Field(
        default=3,
        ge=1,
        le=5,
        description="Anni di storico da backfillare con Alpaca (endpoint /backtest/alpaca-backfill).",
    )

    # ── Mercato UK (London Stock Exchange) — sperimentale ────────────────────
    # Fase 1 di 3: flag di configurazione. Scheduler e validator UK non ancora
    # estesi (Fase 2). Auto-execute UK disabilitato di default anche se enable_uk=True.
    enable_uk_market: bool = Field(
        default=False,
        description=(
            "Abilita il supporto al mercato UK (London Stock Exchange). "
            "Default False: lo scheduler non ingesta simboli LSE finché non impostato True. "
            "Richiede abbonamento IBKR 'London Stock Exchange UK Bundle'."
        ),
    )
    uk_auto_execute_enabled: bool = Field(
        default=False,
        description=(
            "Abilita auto-execute su simboli UK (GBP, LSE). "
            "Disabilitato di default anche se enable_uk_market=True: Strada A non ancora "
            "validata su dataset UK. Abilitare solo dopo raccolta 3-6 mesi di dati UK e "
            "validazione OOS dedicata."
        ),
    )

    # ── ML Signal Scorer ──────────────────────────────────────────────────────
    ml_model_path: str = Field(
        default="",
        description=(
            "Path al file .pkl del modello LightGBM (da analyze_and_train.py --save-model). "
            "Se vuoto (default), il ML scorer è disabilitato e ml_score = None. "
            "Es: eda_output/lgbm_baseline_tp1_hit.pkl"
        ),
    )
    ml_min_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description=(
            "Soglia ML minima per mantenere la decisione 'execute' (0.0 = solo annotazione, "
            "nessun filtro aggiuntivo). Es: 0.55 → i segnali con ml_score < 0.55 "
            "vengono retrocessi a 'monitor' anche se passano tutti gli altri filtri."
        ),
    )
    ml_min_score_short: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description=(
            "Soglia ML per segnali SHORT (bearish). Se 0.0 usa ml_min_score come fallback. "
            "Il modello ML è addestrato principalmente su dati BULL: in regime BEAR i punteggi "
            "per SHORT sono sistematicamente inferiori → usare soglia ridotta (es. 0.40)."
        ),
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
