"""Bootstrap path: scripts/utils/ → backend root."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import asyncio
from sqlalchemy import text
from app.db.session import AsyncSessionLocal

async def main():
    async with AsyncSessionLocal() as session:
        result = await session.execute(text("""
            SELECT symbol, timestamp, open, high, low, close, market_metadata
            FROM candles
            WHERE provider = 'yahoo_finance'
              AND timeframe = '1h'
              AND symbol IN ('NVDA', 'SPY', 'TSLA', 'MSFT')
              AND timestamp >= NOW() - INTERVAL '6 hours'
            ORDER BY symbol, timestamp DESC
        """))
        rows = result.fetchall()
        if not rows:
            print("Nessuna candela trovata nelle ultime 6 ore")
            return
        for r in rows:
            meta = r[6] or {}
            partial = '(PARZIALE)' if meta.get('is_partial') else '(completa)'
            src = meta.get('source', '?')
            print(str(r[0]) + '  ' + str(r[1]) + '  C=' + str(round(float(r[5]),2)) + '  [' + src + '] ' + partial)

asyncio.run(main())
