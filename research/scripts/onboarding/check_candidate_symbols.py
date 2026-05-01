"""
Verifica fattibilità simboli candidati su Alpaca (read-only, no DB write).

Step 1: ping Alpaca per disponibilità ogni simbolo
Step 2: scarica 1 settimana di candele 5m (in CSV temp)
Step 3: calcola profilo (prezzo, ATR%, volume)
Step 4: matching con profilo top performer (ATR% 1-5%, vol > 2M/giorno, prezzo $10-300)

NESSUNA modifica a DB di produzione né a config.
"""
from __future__ import annotations
import os, asyncio, httpx, json, sys
from datetime import datetime, timedelta, timezone
import pandas as pd
import numpy as np

# Carica .env per credenziali
from pathlib import Path
ENV_PATH = Path(r"C:\Lavoro\Trading\intraday-market-screener\.env")
env_vars = {}
if ENV_PATH.exists():
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, _, v = line.partition("=")
            env_vars[k.strip()] = v.strip().strip('"').strip("'")

ALPACA_KEY    = env_vars.get("ALPACA_API_KEY", "")
ALPACA_SECRET = env_vars.get("ALPACA_API_SECRET", "")
ALPACA_BASE   = env_vars.get("ALPACA_BASE_URL", "https://data.alpaca.markets/v2")
ALPACA_FEED   = env_vars.get("ALPACA_FEED", "iex")

CANDIDATES = ["NIO", "XPEV", "RIVN", "IONQ", "SOUN", "UPST", "AFRM", "DKNG"]
# Reference: top performer attuali per benchmark profilo
REFERENCES = ["COIN", "PLTR", "SMCI", "TSLA", "NVDA", "HOOD", "ZS"]
TMP_DIR = Path(r"C:\Lavoro\Trading\intraday-market-screener\research\datasets\_tmp_candidates")
TMP_DIR.mkdir(parents=True, exist_ok=True)

SEP = "=" * 92
SEP2 = "-" * 92


def headers():
    return {
        "APCA-API-KEY-ID": ALPACA_KEY,
        "APCA-API-SECRET-KEY": ALPACA_SECRET,
        "accept": "application/json",
    }


async def fetch_bars(client, symbol, tf, start, end, max_pages=10):
    """Scarica barre paginate. Ritorna lista di dict bar."""
    url = f"{ALPACA_BASE}/stocks/{symbol}/bars"
    params = {
        "timeframe": tf,
        "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "limit": 5000,
        "adjustment": "split",
        "feed": ALPACA_FEED,
    }
    all_bars = []
    page_token = None
    pages = 0
    while pages < max_pages:
        if page_token:
            params["page_token"] = page_token
        try:
            resp = await client.get(url, params=params, timeout=30)
            if resp.status_code == 422:
                return None  # non supportato
            if resp.status_code == 403:
                return "FORBIDDEN"
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as e:
            return f"ERROR: {type(e).__name__}: {e}"
        bars = data.get("bars") or []
        all_bars.extend(bars)
        page_token = data.get("next_page_token")
        if not page_token or not bars:
            break
        pages += 1
    return all_bars


async def get_first_available(client, symbol):
    """Trova la data più vecchia disponibile per il simbolo (binary search approx)."""
    # Try 2020-01-01 → se OK, è vecchio. Altrimenti restringi.
    for year_start in [2020, 2021, 2022, 2023, 2024]:
        start = datetime(year_start, 1, 1, tzinfo=timezone.utc)
        end = start + timedelta(days=10)
        bars = await fetch_bars(client, symbol, "1Day", start, end, max_pages=1)
        if isinstance(bars, list) and len(bars) > 0:
            return year_start, bars[0]["t"]
        if bars == "FORBIDDEN" or (isinstance(bars, str) and bars.startswith("ERROR")):
            return None, bars
    return None, "no data found 2020-2024"


async def get_recent_5m(client, symbol, days_back=10):
    """Scarica 5m delle ultime N giornate trading."""
    end = datetime.now(timezone.utc) - timedelta(days=2)  # IEX ha lag
    start = end - timedelta(days=days_back)
    return await fetch_bars(client, symbol, "5Min", start, end, max_pages=20)


async def get_recent_1d(client, symbol, days_back=30):
    """Scarica 1d delle ultime giornate."""
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days_back)
    return await fetch_bars(client, symbol, "1Day", start, end, max_pages=2)


def calc_atr_pct(bars_5m: list[dict]) -> float | None:
    """ATR(14) come % del close, su barre 5m."""
    if not bars_5m or len(bars_5m) < 20:
        return None
    df = pd.DataFrame(bars_5m)
    df["h"] = pd.to_numeric(df["h"]); df["l"] = pd.to_numeric(df["l"]); df["c"] = pd.to_numeric(df["c"])
    df["tr"] = df[["h","l","c"]].apply(
        lambda r: max(r["h"]-r["l"], abs(r["h"]-r["c"]), abs(r["l"]-r["c"])), axis=1
    )
    atr = df["tr"].rolling(14).mean().iloc[-1]
    last_close = df["c"].iloc[-1]
    return (atr / last_close * 100) if last_close > 0 else None


def calc_atr_pct_1d(bars_1d: list[dict]) -> float | None:
    """ATR daily come % - più robusto per profilo simbolo."""
    if not bars_1d or len(bars_1d) < 14:
        return None
    df = pd.DataFrame(bars_1d)
    df["h"] = pd.to_numeric(df["h"]); df["l"] = pd.to_numeric(df["l"]); df["c"] = pd.to_numeric(df["c"])
    # TR daily
    df["c_prev"] = df["c"].shift(1)
    df["tr"] = df.apply(
        lambda r: max(r["h"]-r["l"],
                      abs(r["h"]-r["c_prev"]) if pd.notna(r["c_prev"]) else 0,
                      abs(r["l"]-r["c_prev"]) if pd.notna(r["c_prev"]) else 0), axis=1
    )
    atr = df["tr"].rolling(14).mean().iloc[-1]
    last_close = df["c"].iloc[-1]
    return (atr / last_close * 100) if last_close > 0 else None


async def main():
    print(SEP)
    print("  VERIFICA FATTIBILITÀ — 8 simboli candidati su Alpaca")
    print(SEP)
    print(f"\n  Endpoint: {ALPACA_BASE}")
    print(f"  Feed: {ALPACA_FEED}")
    print(f"  API key: {ALPACA_KEY[:10]}...{ALPACA_KEY[-4:] if ALPACA_KEY else 'MISSING'}")
    if not ALPACA_KEY or not ALPACA_SECRET:
        print("\n  ERRORE: credenziali Alpaca mancanti in .env")
        return

    profiles = []
    reference_profiles = []

    async with httpx.AsyncClient(headers=headers()) as client:
        # Reference: top performer per benchmark (1d only, no 5m save)
        print("\n  REFERENCE — top performer attuali (per benchmark):")
        for sym in REFERENCES:
            bars_1d = await get_recent_1d(client, sym, days_back=45)
            if isinstance(bars_1d, list) and len(bars_1d) >= 5:
                df_d = pd.DataFrame(bars_1d)
                df_d["v"] = pd.to_numeric(df_d["v"]); df_d["c"] = pd.to_numeric(df_d["c"])
                avg_vol = df_d["v"].mean()
                price = df_d["c"].iloc[-1]
                atr = calc_atr_pct_1d(bars_1d)
                reference_profiles.append({"sym": sym, "price": price, "atr_1d": atr, "vol_d": avg_vol})
                print(f"    {sym:<6}  ${price:>7.2f}  ATR={atr:>5.2f}%  vol={avg_vol/1e6:>5.2f}M/d")

        if reference_profiles:
            ref_atr = np.median([p["atr_1d"] for p in reference_profiles if p["atr_1d"]])
            ref_vol = np.median([p["vol_d"] for p in reference_profiles])
            ref_price_min = min(p["price"] for p in reference_profiles)
            ref_price_max = max(p["price"] for p in reference_profiles)
            print(f"\n    Reference median: ATR%={ref_atr:.2f} vol={ref_vol/1e6:.2f}M price=${ref_price_min:.0f}-${ref_price_max:.0f}")

        print("\n  CANDIDATI:")
        for sym in CANDIDATES:
            print(f"\n  [{sym}] verifica...", end=" ", flush=True)
            # 1. First available
            year, first_ts = await get_first_available(client, sym)
            if year is None:
                print(f"NON DISPONIBILE ({first_ts})")
                profiles.append({"sym": sym, "available": False, "note": str(first_ts)})
                continue

            # 2. Recent 5m (1 settimana)
            bars_5m = await get_recent_5m(client, sym, days_back=10)
            if not isinstance(bars_5m, list):
                print(f"errore 5m: {bars_5m}")
                profiles.append({"sym": sym, "available": False, "note": "5m fetch fail"})
                continue

            # 3. Recent 1d (30 giorni)
            bars_1d = await get_recent_1d(client, sym, days_back=45)
            if not isinstance(bars_1d, list) or len(bars_1d) < 5:
                print(f"errore 1d")
                profiles.append({"sym": sym, "available": False, "note": "1d fetch fail"})
                continue

            # Salva CSV temp
            df5 = pd.DataFrame(bars_5m)
            df5.to_csv(TMP_DIR / f"{sym}_5m_test.csv", index=False)

            # Calcoli profilo
            df_d = pd.DataFrame(bars_1d)
            df_d["v"] = pd.to_numeric(df_d["v"])
            df_d["c"] = pd.to_numeric(df_d["c"])
            avg_vol_daily = df_d["v"].mean()
            last_price    = df_d["c"].iloc[-1]
            atr_pct_5m    = calc_atr_pct(bars_5m)
            atr_pct_1d    = calc_atr_pct_1d(bars_1d)

            profiles.append({
                "sym": sym, "available": True,
                "first_year": year, "first_ts": first_ts,
                "n_5m": len(bars_5m), "n_1d": len(bars_1d),
                "price": last_price,
                "atr_pct_5m": atr_pct_5m,
                "atr_pct_1d": atr_pct_1d,
                "vol_daily": avg_vol_daily,
                "csv": str(TMP_DIR / f"{sym}_5m_test.csv"),
            })
            print(f"OK ({len(bars_5m)} bar 5m, {len(bars_1d)} bar 1d, da {year})")

    # ─── Stampa risultati ─────────────────────────────────────────────────────
    print()
    print(SEP)
    print("  STEP 3 — PROFILO CANDIDATI")
    print(SEP)
    print(f"\n  {'Symbol':<7} {'Avail':<6} {'From':>5} {'Price':>8} {'ATR% 5m':>8} {'ATR% 1d':>8} "
          f"{'Vol/day':>11} {'Match?':<10}  Note")
    print("  " + SEP2)

    # Profilo top performer dal pool TRIPLO (Config D, IEX feed):
    # NB: il volume Alpaca IEX è una FRAZIONE del totale (IEX = ~1-3% del volume USA).
    # I top performer hanno ~1.5M IEX/giorno (~20k IEX/5min).
    # ATR 1d range ampliato per coprire growth/AI/EV (alcuni top sono volatili).
    top_profile = {"atr_min": 2.0, "atr_max": 8.0, "vol_min": 700_000, "p_min": 5, "p_max": 300}

    matching = []
    for p in profiles:
        if not p.get("available"):
            print(f"  {p['sym']:<7} {'NO':<6} {'—':>5} {'—':>8} {'—':>8} {'—':>8} "
                  f"{'—':>11} {'—':<10}  {p.get('note','')}")
            continue

        atr5 = p["atr_pct_5m"] or 0
        atr1d = p["atr_pct_1d"] or 0
        vol = p["vol_daily"]
        price = p["price"]

        # Match check
        match_atr = top_profile["atr_min"] <= atr1d <= top_profile["atr_max"]
        match_vol = vol >= top_profile["vol_min"]
        match_price = top_profile["p_min"] <= price <= top_profile["p_max"]
        match = match_atr and match_vol and match_price
        match_str = "MATCH" if match else "no"
        reasons = []
        if not match_atr: reasons.append(f"atr={atr1d:.1f}%")
        if not match_vol: reasons.append(f"vol={vol/1e6:.1f}M<2M")
        if not match_price: reasons.append(f"price=${price:.0f}")

        if match:
            matching.append(p)

        print(f"  {p['sym']:<7} {'SI':<6} {p['first_year']:>5} ${price:>7.2f} "
              f"{atr5:>7.2f}% {atr1d:>7.2f}% {vol/1e6:>9.1f}M {match_str:<10}  "
              f"{', '.join(reasons) if reasons else 'OK'}")

    # ─── Step 4: comandi backfill ────────────────────────────────────────────
    print()
    print(SEP)
    print("  STEP 4 — Comandi BACKFILL (da NON eseguire ora)")
    print(SEP)

    if not matching:
        print("\n  Nessun simbolo MATCH — nessun backfill consigliato.")
    else:
        print(f"\n  Simboli che matchano profilo top performer: {len(matching)}")
        for p in matching:
            print(f"    - {p['sym']}: ATR% {p['atr_pct_1d']:.2f}, vol {p['vol_daily']/1e6:.1f}M/d, ${p['price']:.0f}")

        print(f"\n  Per backfill 6 mesi 5m + 1h + indicators + patterns:")
        print(f"\n  Step A — Aggiungere a SCHEDULER_SYMBOLS_ALPACA_5M (NON ancora a VALIDATED):")
        print(f"    File: app/core/constants/symbols.py")
        for p in matching:
            print(f"      ('{p['sym']}', '5m'),")

        print(f"\n  Step B — Backfill via API endpoint o CLI Alpaca ingestion:")
        print(f"    docker exec intraday-market-screener-backend-1 python -c \"")
        print(f"    import asyncio")
        print(f"    from datetime import datetime, timedelta, timezone")
        print(f"    from app.services.alpaca_ingestion import AlpacaIngestionService")
        print(f"    from app.db.session import AsyncSessionLocal")
        print(f"    async def main():")
        print(f"        end = datetime.now(timezone.utc)")
        print(f"        start = end - timedelta(days=180)")
        print(f"        symbols = {[p['sym'] for p in matching]}")
        print(f"        async with AsyncSessionLocal() as s:")
        print(f"            svc = AlpacaIngestionService()")
        print(f"            await svc.ingest(s, symbols=symbols, timeframes=['5m'], "
              f"start=start, end=end)")
        print(f"    asyncio.run(main())")
        print(f"    \"")

        print(f"\n  Step C — Pipeline extract per generare patterns/indicators:")
        print(f"    python pipeline_extract.ps1   # estrae indicators + contexts")
        print(f"    python pipeline_indicators_patterns.ps1   # genera patterns")

        print(f"\n  Step D — Validazione OOS (PRIMA di promuovere a execute):")
        print(f"    docker exec intraday-market-screener-backend-1 python scripts/build/build_validation_dataset.py "
              f"--timeframe 5m --output data/val_5m_candidates.csv --holdout-days 0")
        print(f"    Poi analizza il subset {[p['sym'] for p in matching]} su val_5m_candidates")
        print(f"    Edge atteso post-Config D: > +0.30R per essere promosso.")

        print(f"\n  Step E — Solo se passa OOS, aggiungere a VALIDATED:")
        print(f"    Rimuovere il commento di esclusione — il sym entrerà automaticamente")
        print(f"    in VALIDATED_SYMBOLS_ALPACA_5M tramite la fix che abbiamo già fatto.")

    # ─── Salva profili JSON ───────────────────────────────────────────────────
    out_json = TMP_DIR / "candidate_profiles.json"
    out_json.write_text(json.dumps(profiles, default=str, indent=2), encoding="utf-8")
    print(f"\n  Profili salvati: {out_json}")
    print(f"  CSV 5m test: {TMP_DIR}/<symbol>_5m_test.csv")

    print()
    print(SEP)
    print("  CONCLUSIONI")
    print(SEP)
    available = [p for p in profiles if p.get("available")]
    print(f"  Disponibili su Alpaca: {len(available)}/{len(profiles)}")
    print(f"  Match profilo top:     {len(matching)}/{len(available)}")
    print(f"  Nessuna modifica DB / config produzione.")


if __name__ == "__main__":
    asyncio.run(main())
