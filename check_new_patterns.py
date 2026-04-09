"""Verifica quanti nuovi pattern sono stati estratti nel DB."""
import asyncio, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))
os.environ.setdefault('DATABASE_URL', 'postgresql+asyncpg://postgres:postgres@localhost:5432/intraday_market_screener')

NEW_PATTERNS = [
    'nr7_breakout', 'liquidity_sweep_bull', 'liquidity_sweep_bear',
    'rsi_divergence_bull', 'rsi_divergence_bear',
    'volatility_squeeze_breakout', 'double_bottom', 'double_top',
    'macd_divergence_bull', 'macd_divergence_bear'
]

async def main():
    from app.db.session import AsyncSessionLocal
    from sqlalchemy import text
    async with AsyncSessionLocal() as session:
        placeholders = ', '.join([f"'{p}'" for p in NEW_PATTERNS])
        q = f"""
            SELECT pattern_name, COUNT(*) as n
            FROM candle_patterns
            WHERE pattern_name IN ({placeholders})
            GROUP BY pattern_name ORDER BY n DESC
        """
        r = await session.execute(text(q))
        rows = r.fetchall()
        if rows:
            print('Nuovi pattern nel DB:')
            for row in rows:
                print(f'  {row[0]}: {row[1]} segnali')
        else:
            print('Nessun nuovo pattern ancora nel DB — estrazione in corso?')

        # Conta totale pattern nel DB
        r2 = await session.execute(text('SELECT COUNT(*) FROM candle_patterns'))
        total = r2.scalar()
        print(f'\nTotale pattern nel DB: {total}')

if __name__ == '__main__':
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
