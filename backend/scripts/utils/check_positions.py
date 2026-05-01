"""Bootstrap path: scripts/utils/ → backend root."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import asyncio
import datetime
from sqlalchemy import text
from app.db.session import AsyncSessionLocal

async def check():
    async with AsyncSessionLocal() as s:
        cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=24)

        # Le N record che entrano nel slot registry al restart
        r = await s.execute(text("""
            SELECT symbol, timeframe, direction, entry_price, stop_price,
                   close_outcome, tws_status, sl_order_id, tp_order_id, executed_at
            FROM executed_signal
            WHERE closed_at IS NULL
              AND tws_status NOT IN ('skipped', 'error', 'cancelled')
              AND executed_at >= :cutoff
            ORDER BY executed_at DESC
        """), {"cutoff": cutoff})
        rows = r.all()
        print(f"SLOT REGISTRY SOURCE: {len(rows)} record (ultimi 24h, non-skipped)")
        print(f"{'SYM':<6} {'TF':<4} {'DIR':<8} {'ENTRY':>8} {'SL_ID':>9} {'TP_ID':>9} {'TWS_STATUS':<25} EXECUTED_AT")
        print("-" * 110)
        for row in rows:
            slid = str(row[7]) if row[7] else "None"
            tpid = str(row[8]) if row[8] else "None"
            print(f"{row[0]:<6} {row[1]:<4} {(row[2] or ''):<8} {float(row[3]):>8.2f} {slid:>9} {tpid:>9} {(row[6] or ''):<25} {row[9]}")

        # Breakdown totali per status
        r2 = await s.execute(text("""
            SELECT tws_status, count(*)
            FROM executed_signal
            WHERE closed_at IS NULL
            GROUP BY tws_status
            ORDER BY count(*) DESC
        """))
        print("\nBREAKDOWN closed_at IS NULL per tws_status:")
        total = 0
        for row in r2.all():
            print(f"  {(row[0] or 'None'):<30} {row[1]}")
            total += row[1]
        print(f"  {'TOTALE':<30} {total}")

        # Check anche quanti hanno closed_at valorizzato (trade chiusi correttamente)
        r3 = await s.execute(text("""
            SELECT close_outcome, count(*)
            FROM executed_signal
            WHERE closed_at IS NOT NULL
            GROUP BY close_outcome
            ORDER BY count(*) DESC
        """))
        print("\nCHIUSI (closed_at IS NOT NULL) per outcome:")
        for row in r3.all():
            print(f"  {(row[0] or 'None'):<30} {row[1]}")

asyncio.run(check())
