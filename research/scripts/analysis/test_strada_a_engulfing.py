"""Test Strada A — gate ranking engulfing_bullish.

Verifica che:
- engulfing_bullish con final_score < 84.0 → monitor (gate Strada A)
- engulfing_bullish con final_score >= 84.0 → execute
- engulfing_bullish con final_score=None → execute (safe default, no gate)
- altri pattern (es. double_bottom) con score basso → execute (gate non si applica)

Tutti i test usano regime bear + tutti i gate pre-esistenti già superati
(universo, TF, confluence, strength) per isolare il solo gate Strada A.
"""

from datetime import datetime, timezone

import pytest

from app.services.opportunity_validator import validate_opportunity


@pytest.fixture
def _base_kwargs():
    """Kwargs comuni: engulfing_bullish in regime bear, tutti gli altri gate superati."""

    class FakeRegime:
        def get_allowed_directions(self, ts):
            return {"bullish", "bearish"}

        def get_regime_label(self, ts):
            return "bear"

    return dict(
        symbol="META",
        timeframe="1h",
        provider="yahoo_finance",
        pattern_name="engulfing_bullish",
        direction="bullish",
        regime_filter=FakeRegime(),
        timestamp=datetime(2026, 4, 10, 16, 0, tzinfo=timezone.utc),
        pattern_strength=0.82,
        confluence_count=2,
    )


class TestStradaAEngulfingGate:

    def test_below_threshold_monitor(self, _base_kwargs):
        """Score 83.9 < 84.0 → monitor con messaggio Strada A."""
        dec, rat = validate_opportunity(**_base_kwargs, final_score=83.9)
        assert dec == "monitor"
        assert any("Strada A" in r for r in rat)

    def test_above_threshold_execute(self, _base_kwargs):
        """Score 84.1 >= 84.0 → execute."""
        dec, _ = validate_opportunity(**_base_kwargs, final_score=84.1)
        assert dec == "execute"

    def test_exact_threshold_execute(self, _base_kwargs):
        """Score esattamente 84.0 → execute (soglia inclusiva)."""
        dec, _ = validate_opportunity(**_base_kwargs, final_score=84.0)
        assert dec == "execute"

    def test_none_score_execute(self, _base_kwargs):
        """Score None → execute (safe default: gate non si attiva senza dato)."""
        dec, _ = validate_opportunity(**_base_kwargs, final_score=None)
        assert dec == "execute"

    def test_other_pattern_low_score_unaffected(self, _base_kwargs):
        """double_bottom con score basso → execute (gate Strada A non si applica)."""
        kw = {**_base_kwargs, "pattern_name": "double_bottom", "final_score": 40.0}
        dec, _ = validate_opportunity(**kw)
        assert dec == "execute"
