"""
Unit test per app/services/tick_size.py

Esegui con:
    cd backend
    python -m pytest tests/services/test_tick_size.py -v

Non richiede DB né connessione — tutti i test sono puramente in-process.
"""

from decimal import Decimal

import pytest

from app.services.tick_size import (
    CRYPTO_TICK_SIZES,
    US_STOCK_TICK_HIGH,
    US_STOCK_TICK_LOW,
    get_tick_size,
    resolve_asset_class,
    round_to_tick,
)


# ─── get_tick_size ────────────────────────────────────────────────────────────

class TestGetTickSize:
    def test_us_stock_above_1_dollar(self):
        tick = get_tick_size("AAPL", Decimal("182.35"), "us_stock")
        assert tick == US_STOCK_TICK_HIGH == Decimal("0.01")

    def test_us_stock_at_threshold(self):
        tick = get_tick_size("AAPL", Decimal("1.00"), "us_stock")
        assert tick == US_STOCK_TICK_HIGH

    def test_us_stock_penny_stock(self):
        tick = get_tick_size("XYZ", Decimal("0.50"), "us_stock")
        assert tick == US_STOCK_TICK_LOW == Decimal("0.0001")

    def test_etf_same_as_us_stock(self):
        tick = get_tick_size("SPY", Decimal("450.00"), "etf")
        assert tick == US_STOCK_TICK_HIGH

    def test_btc_usdt_tick(self):
        tick = get_tick_size("BTC/USDT", Decimal("43892.15"), "crypto")
        assert tick == Decimal("0.01")

    def test_eth_usdt_tick(self):
        tick = get_tick_size("ETH/USDT", Decimal("2340.50"), "crypto")
        assert tick == Decimal("0.01")

    def test_doge_usdt_tick(self):
        tick = get_tick_size("DOGE/USDT", Decimal("0.08"), "crypto")
        assert tick == Decimal("0.00001")

    def test_crypto_not_in_map_uses_fallback(self, caplog):
        """Simbolo crypto sconosciuto → fallback 0.0001 + warning in log."""
        import logging
        with caplog.at_level(logging.WARNING, logger="app.services.tick_size"):
            tick = get_tick_size("NEWCOIN/USDT", Decimal("5.00"), "crypto")
        assert tick == Decimal("0.0001")
        assert "NEWCOIN/USDT" in caplog.text
        assert "fallback" in caplog.text.lower()

    def test_unknown_asset_class_fallback(self):
        tick = get_tick_size("AAPL", Decimal("182.35"), "futures")
        assert tick == Decimal("0.01")


# ─── round_to_tick ────────────────────────────────────────────────────────────

class TestRoundToTick:
    TICK = Decimal("0.01")

    def test_round_down(self):
        # Stop long: 182.347 → 182.34 (per difetto)
        result = round_to_tick(Decimal("182.347"), self.TICK, "down")
        assert result == Decimal("182.34")

    def test_round_up(self):
        # TP long: 185.671 → 185.68 (per eccesso)
        result = round_to_tick(Decimal("185.671"), self.TICK, "up")
        assert result == Decimal("185.68")

    def test_round_nearest_rounds_up_at_half(self):
        # Entry: 182.505 → 182.51 (ROUND_HALF_UP)
        result = round_to_tick(Decimal("182.505"), self.TICK, "nearest")
        assert result == Decimal("182.51")

    def test_round_nearest_rounds_down_below_half(self):
        result = round_to_tick(Decimal("182.504"), self.TICK, "nearest")
        assert result == Decimal("182.50")

    def test_already_on_tick_no_change(self):
        result = round_to_tick(Decimal("182.34"), self.TICK, "down")
        assert result == Decimal("182.34")

    def test_btc_tick_0_01(self):
        result = round_to_tick(Decimal("43892.15738"), Decimal("0.01"), "down")
        assert result == Decimal("43892.15")

    def test_btc_tick_0_01_up(self):
        result = round_to_tick(Decimal("43892.15001"), Decimal("0.01"), "up")
        assert result == Decimal("43892.16")

    def test_doge_tick_small(self):
        result = round_to_tick(Decimal("0.08347"), Decimal("0.00001"), "nearest")
        assert result == Decimal("0.08347")

    def test_zero_tick_size_returns_price_unchanged(self):
        # Guard: tick_size=0 non deve esplodere
        price = Decimal("100.123")
        result = round_to_tick(price, Decimal("0"), "down")
        assert result == price


# ─── resolve_asset_class ─────────────────────────────────────────────────────

class TestResolveAssetClass:
    def test_binance_exchange(self):
        assert resolve_asset_class(symbol="BTC/USDT", exchange="BINANCE") == "crypto"

    def test_slash_in_symbol(self):
        # Anche senza exchange esplicito, "/" nel symbol → crypto
        assert resolve_asset_class(symbol="ETH/USDT", exchange="") == "crypto"

    def test_nasdaq_exchange(self):
        assert resolve_asset_class(symbol="AAPL", exchange="NASDAQ") == "us_stock"

    def test_nyse_exchange(self):
        assert resolve_asset_class(symbol="JPM", exchange="NYSE") == "us_stock"

    def test_smart_exchange(self):
        assert resolve_asset_class(symbol="AAPL", exchange="SMART") == "us_stock"

    def test_empty_exchange_defaults_us_stock(self):
        assert resolve_asset_class(symbol="AAPL", exchange="") == "us_stock"

    def test_unknown_exchange_logs_warning_and_falls_back(self, caplog):
        import logging
        with caplog.at_level(logging.WARNING, logger="app.services.tick_size"):
            result = resolve_asset_class(symbol="XYZ", exchange="UNKNOWNEX")
        assert result == "us_stock"
        assert "UNKNOWNEX" in caplog.text


# ─── Integrazione: scenario completo AAPL long ───────────────────────────────

class TestIntegrationAaplLong:
    """
    Simula il caso d'uso reale: AAPL long con entry/stop/TP calcolati
    dal motore e poi arrotondati al tick size $0.01.
    """

    def test_aapl_long_rounding(self):
        from app.services.trade_plan_engine import _apply_tick_rounding
        from app.schemas.trade_plan import TradePlanV1

        plan = TradePlanV1(
            trade_direction="long",
            entry_strategy="close",
            entry_price=Decimal("182.505"),   # → 182.51 (nearest)
            stop_loss=Decimal("179.347"),      # → 179.34 (down = più largo)
            take_profit_1=Decimal("185.671"), # → 185.68 (up = più difficile)
            take_profit_2=Decimal("188.263"), # → 188.27 (up)
            risk_reward_ratio=Decimal("1.50"),
            invalidation_note="test",
        )
        rounded = _apply_tick_rounding(plan, symbol="AAPL", exchange="NASDAQ")

        assert rounded.entry_price == Decimal("182.51")
        assert rounded.stop_loss == Decimal("179.34")
        assert rounded.take_profit_1 == Decimal("185.68")
        assert rounded.take_profit_2 == Decimal("188.27")
        # R/R ricalcolato sui livelli arrotondati
        risk = rounded.entry_price - rounded.stop_loss  # 182.51 - 179.34 = 3.17
        reward = rounded.take_profit_1 - rounded.entry_price  # 185.68 - 182.51 = 3.17
        expected_rr = (reward / risk).quantize(Decimal("0.01"))
        assert rounded.risk_reward_ratio == expected_rr

    def test_aapl_short_rounding(self):
        from app.services.trade_plan_engine import _apply_tick_rounding
        from app.schemas.trade_plan import TradePlanV1

        plan = TradePlanV1(
            trade_direction="short",
            entry_strategy="close",
            entry_price=Decimal("182.505"),   # → 182.51 (nearest)
            stop_loss=Decimal("185.671"),      # → 185.68 (up = più largo per short)
            take_profit_1=Decimal("179.347"), # → 179.34 (down = più difficile per short)
            take_profit_2=Decimal("176.255"), # → 176.25 (down)
            risk_reward_ratio=Decimal("1.50"),
            invalidation_note="test",
        )
        rounded = _apply_tick_rounding(plan, symbol="AAPL", exchange="NYSE")

        assert rounded.entry_price == Decimal("182.51")
        assert rounded.stop_loss == Decimal("185.68")   # up per short
        assert rounded.take_profit_1 == Decimal("179.34")  # down per short
        assert rounded.take_profit_2 == Decimal("176.25")

    def test_no_rounding_when_symbol_empty(self):
        """Backtester path: symbol vuoto → nessun arrotondamento."""
        from app.services.trade_plan_engine import _apply_tick_rounding
        from app.schemas.trade_plan import TradePlanV1

        plan = TradePlanV1(
            trade_direction="long",
            entry_strategy="close",
            entry_price=Decimal("182.505"),
            stop_loss=Decimal("179.347"),
            take_profit_1=Decimal("185.671"),
            take_profit_2=Decimal("188.263"),
            risk_reward_ratio=Decimal("1.50"),
            invalidation_note="test",
        )
        result = _apply_tick_rounding(plan, symbol="", exchange="")
        # Nessun livello deve essere alterato
        assert result.entry_price == Decimal("182.505")
        assert result.stop_loss == Decimal("179.347")
        assert result.take_profit_1 == Decimal("185.671")

    def test_btc_usdt_rounding(self):
        """BTC/USDT crypto: tick 0.01."""
        from app.services.trade_plan_engine import _apply_tick_rounding
        from app.schemas.trade_plan import TradePlanV1

        plan = TradePlanV1(
            trade_direction="long",
            entry_strategy="close",
            entry_price=Decimal("43892.15738"),   # → 43892.16 (nearest)
            stop_loss=Decimal("43105.83421"),      # → 43105.83 (down)
            take_profit_1=Decimal("44679.47219"), # → 44679.48 (up)
            take_profit_2=Decimal("45460.23871"), # → 45460.24 (up)
            risk_reward_ratio=Decimal("1.00"),
            invalidation_note="test",
        )
        rounded = _apply_tick_rounding(plan, symbol="BTC/USDT", exchange="BINANCE")

        assert rounded.entry_price == Decimal("43892.16")
        assert rounded.stop_loss == Decimal("43105.83")
        assert rounded.take_profit_1 == Decimal("44679.48")
        assert rounded.take_profit_2 == Decimal("45460.24")
