"""Impostazioni esposte via API (solo flag non sensibili, nessun segreto)."""

from typing import Any

from pydantic import BaseModel, Field


class PublicSettingsResponse(BaseModel):
    """Sottoinsieme di config utile per verifica operativa / integrazione."""

    environment: str = Field(description="Ambiente runtime (es. development, production).")
    alert_notifications_enabled: bool = Field(
        description="True se le notifiche post-pipeline sono abilitate (flusso legacy).",
    )
    alert_legacy_enabled: bool = Field(
        description="True se il flusso alert_notifications (legacy) è attivo dopo il pipeline.",
    )
    alert_include_media_priorita: bool = Field(
        description="True se inviare anche alert media_priorita (env ALERT_INCLUDE_MEDIA_PRIORITA).",
    )
    pipeline_scheduler_enabled: bool = Field(
        description="True se lo scheduler pipeline in-process è attivo.",
    )
    frontend_base_url: str = Field(
        default="",
        description="Base URL frontend per deep link negli alert (ALERT_FRONTEND_BASE_URL).",
    )
    scheduler_universe: dict[str, Any] = Field(
        default_factory=dict,
        description="Conteggi universo scheduler esplicito (Yahoo 1h, Binance 1h, Binance 1d regime, totale).",
    )
    cache_stats: dict[str, Any] = Field(
        default_factory=dict,
        description="Statistiche cache lookup opportunità (pattern_quality, trade_plan_backtest, variant_best).",
    )
    alert_min_strength: float = Field(
        description="Soglia strength alert (Settings.alert_min_strength / ALERT_MIN_STRENGTH).",
    )
    signal_min_strength: float = Field(
        description="Soglia strength execute/validator (trade_plan_variant_constants.SIGNAL_MIN_STRENGTH).",
    )