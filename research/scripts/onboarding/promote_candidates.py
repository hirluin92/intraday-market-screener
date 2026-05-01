"""
Promozione candidati: legge promotion_decision.json e applica modifiche
a SYMBOLS_BLOCKED_ALPACA_5M in symbols.py.

Esegui DOPO evaluate_candidates_oos.py.
"""
import json
import re
from pathlib import Path

DECISION_FILE = Path(r"C:\Lavoro\Trading\intraday-market-screener\research\datasets\_tmp_candidates\promotion_decision.json")
SYMBOLS_FILE = Path(r"C:\Lavoro\Trading\intraday-market-screener\backend\app\core\constants\symbols.py")

print("="*80)
print("  PROMOZIONE CANDIDATI")
print("="*80)

if not DECISION_FILE.exists():
    print(f"  ERROR: {DECISION_FILE} non trovato. Esegui evaluate_candidates_oos.py prima.")
    raise SystemExit(1)

decision = json.loads(DECISION_FILE.read_text())
to_promote = decision.get("to_promote", [])
stats = decision.get("stats", {})

print(f"\n  Decisione: {to_promote}")
print(f"\n  Stats per simbolo:")
for sym, s in stats.items():
    promoted = "PROMOTE" if sym in to_promote else "BLOCK"
    print(f"    {sym}: n={s['n']}  eff={s['eff']:+.4f}  WR={s['wr']:.1f}%  → {promoted}")

if not to_promote:
    print("\n  Nessun simbolo da promuovere. blocklist invariato.")
    print("  Rimangono in scheduler per data collection futura.")
    raise SystemExit(0)

# Modifica symbols.py: rimuovi i simboli promossi dal blocklist
content = SYMBOLS_FILE.read_text(encoding="utf-8")

# Trova la riga con NIO/RIVN/DKNG/SOUN nel blocklist
blocklist_line_pattern = r'    "NIO", "RIVN", "DKNG", "SOUN",\n'

if not re.search(blocklist_line_pattern, content):
    print(f"\n  WARN: blocklist line non trovata nel file (potrebbe essere già stata modificata).")
    print(f"  Verifica manuale.")
    raise SystemExit(2)

# Genera nuova lista con solo i NON promossi
remaining = [s for s in ["NIO", "RIVN", "DKNG", "SOUN"] if s not in to_promote]
if remaining:
    new_line = f'    {", ".join(f"""\"{s}\"""" for s in remaining)},\n'
else:
    # Tutti promossi → rimuovi la linea con i 4
    new_line = ""

# Sostituisci
new_content = re.sub(blocklist_line_pattern, new_line, content)

# Aggiorna il commento se tutti promossi
if not remaining:
    # Rimuovi anche il commento "Candidati in fase di onboarding"
    comment_pattern = r'    # Candidati in fase di onboarding.*?iGaming\)\.\n'
    new_content = re.sub(comment_pattern, "", new_content, flags=re.DOTALL)

SYMBOLS_FILE.write_text(new_content, encoding="utf-8")
print(f"\n  symbols.py modificato:")
print(f"    Promossi: {to_promote}")
print(f"    Restano bloccati (in fase onboarding): {remaining}")
print(f"\n  Step successivi:")
print(f"    1. py_compile + restart backend")
print(f"    2. Smoke test: i simboli promossi devono essere in VALIDATED_SYMBOLS_ALPACA_5M")
