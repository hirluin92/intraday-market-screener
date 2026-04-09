import asyncio
from sqlalchemy import text
from app.db.session import AsyncSessionLocal
from datetime import datetime, timezone

async def main():
    now = datetime.now(tz=timezone.utc)
    print("Ora UTC: " + str(now)[:19])

    async with AsyncSessionLocal() as session:
        r = await session.execute(text(
            "SELECT symbol, max(timestamp) as last_pat_ts "
            "FROM candle_patterns "
            "WHERE provider = 'yahoo_finance' AND timeframe = '1h' "
            "GROUP BY symbol ORDER BY last_pat_ts DESC"
        ))
        rows = r.fetchall()
        fresh = []
        stale = []
        for row in rows:
            sym = str(row[0])
            pat_ts = row[1]
            hours_ago = (now - pat_ts).total_seconds() / 3600 if pat_ts else 999
            if hours_ago <= 8:
                fresh.append((sym, round(hours_ago, 1)))
            else:
                stale.append((sym, round(hours_ago, 1)))

        print("=== FRESH (<=8h) — appariranno nello screener ===")
        print("  Totale: " + str(len(fresh)))
        for sym, h in fresh:
            print("  " + sym.ljust(8) + "  " + str(h) + "h fa")

        print("\n=== STALE (>8h) ===")
        print("  Totale stale: " + str(len(stale)))
        for sym, h in stale[:5]:
            print("  " + sym.ljust(8) + "  " + str(h) + "h fa")

asyncio.run(main())
