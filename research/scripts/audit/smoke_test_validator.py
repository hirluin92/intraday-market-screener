import sys; sys.path.insert(0, "/app")
from datetime import datetime, timezone
from app.services.opportunity_validator import validate_opportunity

def test(label, ts_str, tf, prov, risk_pct, expect):
    ts = datetime.fromisoformat(ts_str).replace(tzinfo=timezone.utc)
    result, reason = validate_opportunity(
        symbol="TSLA", timeframe=tf, provider=prov, timestamp=ts,
        pattern_name="double_top", direction="bearish",
        risk_pct=risk_pct, regime_filter=None, final_score=80.0
    )
    # validator returns "execute"/"discard"/"accept" — normalise accept aliases
    actual = "accept" if result in ("execute", "accept") else "discard"
    ok = "  OK" if actual == expect else "FAIL"
    msg = reason[0][:70] if reason else "-"
    print(f"{ok}  {label:<48}  {result}  | {msg}")

print("=== SMOKE TEST validator 5m PowerHours ===")
test("5m 13:00 ET fuori PH (EDT=17:00 UTC)",   "2026-04-28 17:00:00", "5m", "alpaca", 0.80, "discard")
test("5m 14:30 ET in PH   (EDT=18:30 UTC)",     "2026-04-28 18:30:00", "5m", "alpaca", 0.80, "accept")
test("5m 15:45 ET in PH   (EDT=19:45 UTC)",     "2026-04-28 19:45:00", "5m", "alpaca", 0.80, "accept")
test("5m 11:30 ET fuori PH (EDT=15:30 UTC)",    "2026-04-28 15:30:00", "5m", "alpaca", 0.80, "discard")
test("5m 12:00 ET fuori PH (EDT=16:00 UTC)",    "2026-04-28 16:00:00", "5m", "alpaca", 0.80, "discard")
test("5m risk_pct=0.30 sotto floor",            "2026-04-28 18:30:00", "5m", "alpaca", 0.30, "discard")
test("5m risk_pct=2.50 sopra cap",              "2026-04-28 18:30:00", "5m", "alpaca", 2.50, "discard")
test("5m risk_pct=1.90 dentro cap",             "2026-04-28 18:30:00", "5m", "alpaca", 1.90, "accept")
test("5m risk_pct=0.50 sul floor (ok)",         "2026-04-28 18:30:00", "5m", "alpaca", 0.50, "accept")
test("5m risk_pct=2.00 sul cap (ok)",           "2026-04-28 18:30:00", "5m", "alpaca", 2.00, "accept")
print("=== DONE ===")
