"""
Analisi diagnostica: perche' il 5m perde con slippage?
Dataset: data/val_5m_real.csv  (Alpaca, 4 pattern validati)
Confronto: data/val_1h_large_post_fix.csv
"""

import numpy as np
import pandas as pd

# ── CONFIG ────────────────────────────────────────────────────────────────────
CSV_5M = "data/val_5m_real.csv"
CSV_1H = "data/val_1h_large_post_fix.csv"

VALIDATED = {
    "double_bottom", "double_top",
    "macd_divergence_bull", "macd_divergence_bear",
}

SEP  = "=" * 72
SEP2 = "-" * 72


def load(path, provider=None):
    df = pd.read_csv(path, parse_dates=["pattern_timestamp"])
    df = df[df["entry_filled"] == True].copy()
    df = df[df["pattern_name"].isin(VALIDATED)].copy()
    if provider:
        df = df[df["provider"] == provider].copy()
    return df


df5  = load(CSV_5M, provider="alpaca")
df1h = load(CSV_1H)

# ────────────────────────────────────────────────────────────────────────────
print(SEP)
print("  ANALISI DIAGNOSTICA 5m vs 1h")
print("  5m Alpaca: n={:,}  avg_r={:+.4f}R".format(len(df5), df5["pnl_r"].mean()))
print("  1h Yahoo:  n={:,}  avg_r={:+.4f}R".format(len(df1h), df1h["pnl_r"].mean()))
print(SEP)

# ────────────────────────────────────────────────────────────────────────────
# ANALISI 1 — DISTRIBUZIONE PnL
# ────────────────────────────────────────────────────────────────────────────
print()
print(SEP)
print("  ANALISI 1 -- DISTRIBUZIONE PnL")
print(SEP)

bins  = [float("-inf"), -3, -2, -1.5, -1, -0.5, -0.2,
         0.2, 0.5, 1, 1.5, 2, 3, float("inf")]
lbls  = ["<-3", "-3/-2", "-2/-1.5", "-1.5/-1", "-1/-0.5",
         "-0.5/0", "-0.2/+0.2*", "+0.2/+0.5", "+0.5/+1",
         "+1/+1.5", "+1.5/+2", "+2/+3", ">+3"]

for df, label in [(df5, "5m Alpaca"), (df1h, "1h Yahoo")]:
    n = len(df)
    cuts = pd.cut(df["pnl_r"], bins=bins, labels=lbls, right=True)
    cnt  = cuts.value_counts().reindex(lbls, fill_value=0)
    print()
    print("  {}  (n={:,})".format(label, n))
    print("  {:<16} {:>7} {:>8}".format("Fascia", "N", "% totale"))
    print("  " + "-" * 34)
    for lbl in lbls:
        c   = cnt[lbl]
        pct = c / n * 100
        marker = " <-- stop full" if lbl == "-1/-0.5" else (
                 " <-- breakeven/rumore" if lbl == "-0.2/+0.2*" else "")
        print("  {:<16} {:>7} {:>7.1f}%{}".format(lbl, c, pct, marker))

    # Fasce richieste esplicitamente
    stop_full  = ((df["pnl_r"] >= -1.2) & (df["pnl_r"] <= -0.8)).sum()
    noise_zone = ((df["pnl_r"] >= -0.2) & (df["pnl_r"] <=  0.2)).sum()
    print()
    print("  Stop 'full' (-1.2/-0.8R):    {:>5}  ({:.1f}%)".format(stop_full,  stop_full  / n * 100))
    print("  Breakeven/rumore (-0.2/+0.2R): {:>5}  ({:.1f}%)  <- con slip -> tutti perdenti".format(
        noise_zone, noise_zone / n * 100))

# ────────────────────────────────────────────────────────────────────────────
# ANALISI 2 — STOP / TP / TIMEOUT
# ────────────────────────────────────────────────────────────────────────────
print()
print(SEP)
print("  ANALISI 2 -- STOP LOSS / TP / TIMEOUT")
print(SEP)

for df, label in [(df5, "5m Alpaca"), (df1h, "1h Yahoo")]:
    n = len(df)
    oc = df["outcome"].value_counts()
    print()
    print("  {}  (n={:,})".format(label, n))
    for out in ["stop", "tp1", "tp2", "timeout", "no_entry"]:
        c   = oc.get(out, 0)
        pct = c / n * 100
        print("  {:<12} {:>5}  ({:.1f}%)".format(out, c, pct))

    # Avg pnl per outcome
    print()
    print("  {:<12} {:>7} {:>9}".format("Outcome", "n", "avg_r"))
    for out, grp in df.groupby("outcome")["pnl_r"]:
        print("  {:<12} {:>7} {:>+9.4f}R".format(out, len(grp), grp.mean()))

# ────────────────────────────────────────────────────────────────────────────
# ANALISI 3 — TEMPO NEL TRADE
# ────────────────────────────────────────────────────────────────────────────
print()
print(SEP)
print("  ANALISI 3 -- TEMPO NEL TRADE (bars_to_exit)")
print(SEP)

for df, label in [(df5, "5m Alpaca"), (df1h, "1h Yahoo")]:
    if "bars_to_exit" not in df.columns:
        print("  {} -- colonna bars_to_exit non presente".format(label))
        continue
    df_bte = df[df["bars_to_exit"].notna()].copy()
    df_bte["bars_to_exit"] = pd.to_numeric(df_bte["bars_to_exit"], errors="coerce")
    df_bte = df_bte[df_bte["bars_to_exit"].notna()]

    win  = df_bte[df_bte["pnl_r"] >  0]
    loss = df_bte[df_bte["pnl_r"] <= 0]

    print()
    print("  {}  (n con bars_to_exit={:,})".format(label, len(df_bte)))
    print("  Media complessiva: {:.1f} barre".format(df_bte["bars_to_exit"].mean()))
    print("  Winner:  media {:.1f} barre  (n={:,})".format(
        win["bars_to_exit"].mean()  if len(win)  > 0 else 0, len(win)))
    print("  Loser:   media {:.1f} barre  (n={:,})".format(
        loss["bars_to_exit"].mean() if len(loss) > 0 else 0, len(loss)))

    # Distribuzione durata
    bins_b  = [0, 1, 3, 5, 10, 20, 50, 9999]
    labels_b = ["1", "2-3", "4-5", "6-10", "11-20", "21-50", ">50"]
    cuts = pd.cut(df_bte["bars_to_exit"], bins=bins_b, labels=labels_b, right=True)
    cnt  = cuts.value_counts().reindex(labels_b, fill_value=0)
    print("  Distribuzione durata (barre):")
    for lbl in labels_b:
        c = cnt[lbl]
        print("    {:<8} {:>5}  ({:.1f}%)".format(lbl, c, c / len(df_bte) * 100))

# ────────────────────────────────────────────────────────────────────────────
# ANALISI 4 — ENTRY QUALITY (bars_to_entry)
# ────────────────────────────────────────────────────────────────────────────
print()
print(SEP)
print("  ANALISI 4 -- ENTRY QUALITY (bars_to_entry)")
print(SEP)

for df, label in [(df5, "5m Alpaca"), (df1h, "1h Yahoo")]:
    if "bars_to_entry" not in df.columns:
        print("  {} -- colonna bars_to_entry non presente".format(label))
        continue
    df_bte = df[df["bars_to_entry"].notna()].copy()
    df_bte["bars_to_entry"] = pd.to_numeric(df_bte["bars_to_entry"], errors="coerce")
    df_bte = df_bte[df_bte["bars_to_entry"].notna()]

    print()
    print("  {}  (n={:,})".format(label, len(df_bte)))
    print("  Media bars_to_entry: {:.2f}".format(df_bte["bars_to_entry"].mean()))

    for band, lo, hi in [("entry bar 1 (immediata)", 1, 1),
                          ("bar 2-3",                 2, 3),
                          ("bar 4-5",                 4, 5),
                          ("bar >5 (ritardata)",      6, 9999)]:
        sub = df_bte[(df_bte["bars_to_entry"] >= lo) & (df_bte["bars_to_entry"] <= hi)]
        if len(sub) == 0:
            continue
        avg = sub["pnl_r"].mean()
        wr  = (sub["pnl_r"] > 0).sum() / len(sub) * 100
        print("  {:<26} n={:>5}  ({:>5.1f}%)  avg_r={:>+.4f}R  WR={:.1f}%".format(
            band, len(sub), len(sub) / len(df_bte) * 100, avg, wr))

# ────────────────────────────────────────────────────────────────────────────
# ANALISI 5 — CONFRONTO DIRETTO 1h vs 5m per pattern
# ────────────────────────────────────────────────────────────────────────────
print()
print(SEP)
print("  ANALISI 5 -- CONFRONTO DIRETTO 1h vs 5m (stesso pattern)")
print(SEP)

print()
print("  {:<30} {:>6} {:>7} {:>8} {:>7} {:>7} {:>8}".format(
    "Pattern / TF", "n", "WR%", "avg_r", "% stop", "% tp1", "% timeo"))
print(SEP2)

for pattern in sorted(VALIDATED):
    for df, tf_label in [(df1h, "1h"), (df5, "5m")]:
        sub = df[df["pattern_name"] == pattern]
        if len(sub) == 0:
            continue
        n     = len(sub)
        wr    = (sub["pnl_r"] > 0).sum() / n * 100
        avg   = sub["pnl_r"].mean()
        oc    = sub["outcome"].value_counts()
        p_stp = oc.get("stop",    0) / n * 100
        p_tp1 = oc.get("tp1",     0) / n * 100
        p_to  = oc.get("timeout", 0) / n * 100
        print("  {:<30} {:>6} {:>6.1f}% {:>+8.3f}R {:>6.1f}% {:>6.1f}% {:>7.1f}%".format(
            "{} [{}]".format(pattern[:24], tf_label), n, wr, avg, p_stp, p_tp1, p_to))
    print()

# ────────────────────────────────────────────────────────────────────────────
# ANALISI 6 — R:R EFFETTIVO
# ────────────────────────────────────────────────────────────────────────────
print()
print(SEP)
print("  ANALISI 6 -- R:R EFFETTIVO (avg_win vs avg_loss)")
print(SEP)

for df, label in [(df5, "5m Alpaca"), (df1h, "1h Yahoo")]:
    win  = df[df["pnl_r"] >  0]["pnl_r"]
    loss = df[df["pnl_r"] <= 0]["pnl_r"]

    avg_win  = win.mean()   if len(win)  > 0 else 0
    avg_loss = loss.mean()  if len(loss) > 0 else 0
    rr_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0
    wr       = len(win) / len(df) * 100

    print()
    print("  {}  (n={:,})".format(label, len(df)))
    print("  WR:        {:.1f}%".format(wr))
    print("  avg_win:   {:+.4f}R  (n={:,})".format(avg_win,  len(win)))
    print("  avg_loss:  {:+.4f}R  (n={:,})".format(avg_loss, len(loss)))
    print("  R:R reale: {:.3f}  (win/loss in valore assoluto)".format(rr_ratio))
    print("  Edge/trade: WR * avg_win + (1-WR) * avg_loss = {:+.4f}R".format(
        wr / 100 * avg_win + (1 - wr / 100) * avg_loss))

    # Con slippage
    print()
    print("  Impatto slippage su R:R:")
    for slip in [0.05, 0.10, 0.15]:
        win_s  = win  - slip
        loss_s = loss - slip
        aw  = win_s.mean()  if len(win_s)  > 0 else 0
        al  = loss_s.mean() if len(loss_s) > 0 else 0
        # WR effettivo dopo slippage (alcuni win diventano loss)
        wr_s = (df["pnl_r"] - slip > 0).sum() / len(df) * 100
        print("  slip {:.2f}R -> avg_win={:+.4f}R  avg_loss={:+.4f}R  WR_eff={:.1f}%".format(
            slip, aw, al, wr_s))

# ────────────────────────────────────────────────────────────────────────────
# ANALISI 7 — PATTERN STRENGTH E CONFLUENZA
# ────────────────────────────────────────────────────────────────────────────
print()
print(SEP)
print("  ANALISI 7 -- PATTERN STRENGTH E CONFLUENZA")
print(SEP)

for df, label in [(df5, "5m Alpaca"), (df1h, "1h Yahoo")]:
    print()
    print("  {}".format(label))
    # pattern_strength
    if "pattern_strength" in df.columns:
        ps = pd.to_numeric(df["pattern_strength"], errors="coerce").dropna()
        print("  pattern_strength: min={:.3f} mean={:.3f} max={:.3f}".format(
            ps.min(), ps.mean(), ps.max()))
        # Quartili di strength vs avg_r
        df2 = df.copy()
        df2["ps"] = pd.to_numeric(df2["pattern_strength"], errors="coerce")
        df2 = df2.dropna(subset=["ps"])
        bins_s = [0, 0.5, 0.6, 0.7, 0.8, 0.9, 1.01]
        lbls_s = ["<0.5","0.5-0.6","0.6-0.7","0.7-0.8","0.8-0.9","0.9-1.0"]
        df2["ps_band"] = pd.cut(df2["ps"], bins=bins_s, labels=lbls_s, right=False)
        grp = df2.groupby("ps_band", observed=False)["pnl_r"].agg(n="count", avg_r="mean", wr=lambda x: (x>0).mean()*100)
        print("  Strength vs avg_r:")
        print("  {:<12} {:>6} {:>9} {:>7}".format("Band", "n", "avg_r", "WR%"))
        for idx, row in grp.iterrows():
            if row["n"] < 5:
                continue
            print("  {:<12} {:>6} {:>+9.4f}R {:>6.1f}%".format(
                str(idx), int(row["n"]), row["avg_r"], row["wr"]))

    # screener_score / final_score proxy confluenza
    for col in ["final_score", "screener_score"]:
        if col in df.columns:
            sc = pd.to_numeric(df[col], errors="coerce").dropna()
            print("  {}: min={:.1f} mean={:.1f} max={:.1f}".format(
                col, sc.min(), sc.mean(), sc.max()))

# ────────────────────────────────────────────────────────────────────────────
# ANALISI 8 — ORE DEL GIORNO (ET)
# ────────────────────────────────────────────────────────────────────────────
print()
print(SEP)
print("  ANALISI 8 -- ORE DEL GIORNO (ET = UTC-4/5)")
print(SEP)

df5_copy = df5.copy()
# Converti UTC -> ET (usa offset fisso -4h come proxy EST/EDT)
df5_copy["ts_et"] = df5_copy["pattern_timestamp"] - pd.Timedelta(hours=4)
df5_copy["hour_et"] = df5_copy["ts_et"].dt.hour

grp_h = df5_copy.groupby("hour_et")["pnl_r"].agg(n="count", avg_r="mean", wr=lambda x: (x>0).mean()*100)
grp_h = grp_h[grp_h["n"] >= 5]

print()
print("  5m Alpaca — distribuzione per ora ET (UTC-4):")
print("  {:<8} {:>6} {:>9} {:>7}".format("Ora ET", "n", "avg_r", "WR%"))
print(SEP2)
for hour, row in grp_h.iterrows():
    flag = " <-- NEGATIVO" if row["avg_r"] < -0.05 else (
           " <-- OTTIMO"   if row["avg_r"] >  0.30 else "")
    print("  {:<8} {:>6} {:>+9.4f}R {:>6.1f}%{}".format(
        "{:02d}:00".format(hour), int(row["n"]), row["avg_r"], row["wr"], flag))

# Market open / mid / close buckets
df5_copy["session"] = pd.cut(
    df5_copy["hour_et"],
    bins=[-1, 9, 11, 14, 16, 24],
    labels=["pre-market(<9:30)", "open(9:30-11)", "mid(11-14)", "close(14-16)", "after(>16)"]
)
grp_s = df5_copy.groupby("session", observed=False)["pnl_r"].agg(n="count", avg_r="mean", wr=lambda x: (x>0).mean()*100)
print()
print("  Bucket sessione:")
print("  {:<22} {:>6} {:>9} {:>7}".format("Sessione", "n", "avg_r", "WR%"))
for idx, row in grp_s.iterrows():
    if row["n"] < 3:
        continue
    print("  {:<22} {:>6} {:>+9.4f}R {:>6.1f}%".format(
        str(idx), int(row["n"]), row["avg_r"], row["wr"]))

# ────────────────────────────────────────────────────────────────────────────
# DIAGNOSI FINALE
# ────────────────────────────────────────────────────────────────────────────
print()
print(SEP)
print("  DIAGNOSI FINALE")
print(SEP)

# Calcola statistiche riassuntive per la diagnosi
n5   = len(df5)
n1h  = len(df1h)

stop_pct_5m  = (df5["outcome"]  == "stop").sum()  / n5  * 100
stop_pct_1h  = (df1h["outcome"] == "stop").sum()  / n1h * 100
tp1_pct_5m   = (df5["outcome"]  == "tp1").sum()   / n5  * 100
tp1_pct_1h   = (df1h["outcome"] == "tp1").sum()   / n1h * 100
to_pct_5m    = (df5["outcome"]  == "timeout").sum()/ n5  * 100

noise_5m = ((df5["pnl_r"]  >= -0.2) & (df5["pnl_r"] <=  0.2)).sum() / n5  * 100
noise_1h = ((df1h["pnl_r"] >= -0.2) & (df1h["pnl_r"] <= 0.2)).sum()  / n1h * 100

win5  = df5[df5["pnl_r"]   >  0]["pnl_r"]
loss5 = df5[df5["pnl_r"]   <= 0]["pnl_r"]
win1h = df1h[df1h["pnl_r"] >  0]["pnl_r"]
loss1h= df1h[df1h["pnl_r"] <= 0]["pnl_r"]

aw5   = win5.mean();   al5  = loss5.mean()
aw1h  = win1h.mean();  al1h = loss1h.mean()
wr5   = len(win5) / n5 * 100
wr1h  = len(win1h) / n1h * 100

be5 = df5["pnl_r"].mean()

print()
print("  CONFRONTO CHIAVE:")
print("  {:<30} {:>12} {:>12}".format("Metrica", "5m Alpaca", "1h Yahoo"))
print(SEP2)
rows_diag = [
    ("avg_r pre-slippage",    "{:+.4f}R".format(be5),         "{:+.4f}R".format(df1h["pnl_r"].mean())),
    ("Break-even slippage",   "{:.4f}R".format(be5),          "{:.4f}R".format(df1h["pnl_r"].mean())),
    ("WR%",                   "{:.1f}%".format(wr5),          "{:.1f}%".format(wr1h)),
    ("avg_win (R)",           "{:+.4f}R".format(aw5),         "{:+.4f}R".format(aw1h)),
    ("avg_loss (R)",          "{:+.4f}R".format(al5),         "{:+.4f}R".format(al1h)),
    ("R:R reale",             "{:.3f}".format(abs(aw5/al5)),  "{:.3f}".format(abs(aw1h/al1h))),
    ("% trade -> stop",       "{:.1f}%".format(stop_pct_5m),  "{:.1f}%".format(stop_pct_1h)),
    ("% trade -> tp1",        "{:.1f}%".format(tp1_pct_5m),   "{:.1f}%".format(tp1_pct_1h)),
    ("% trade -> timeout",    "{:.1f}%".format(to_pct_5m),    "n/a"),
    ("% trade 'rumore'(-0.2/+0.2R)", "{:.1f}%".format(noise_5m), "{:.1f}%".format(noise_1h)),
]
for r in rows_diag:
    print("  {:<30} {:>12} {:>12}".format(*r))

print()
print(SEP)
print("  CAUSE IDENTIFICATE (dalla piu' importante alla meno)")
print(SEP)
print()

cause1_note = "ALTA" if noise_5m > 20 else "MEDIA"
cause2_note = "ALTA" if (aw5 < aw1h * 0.7) else "MEDIA"
cause3_note = "ALTA" if (stop_pct_5m > stop_pct_1h + 10) else "MEDIA"

print("  CAUSA 1 -- R:R STRUTTURALMENTE INFERIORE AL 1h  [criticita': {}]".format(cause2_note))
print("  5m avg_win={:+.4f}R vs 1h avg_win={:+.4f}R  ({:+.1f}% rispetto a 1h)".format(
    aw5, aw1h, (aw5/aw1h - 1)*100))
print("  5m avg_loss={:+.4f}R vs 1h avg_loss={:+.4f}R".format(al5, al1h))
print("  Il 5m incassa meno quando vince e perde altrettanto quando perde.")
print("  Causa probabile: SL/TP parametri identici al 1h ma su barre 12x piu' corte.")
print("  -> Stesso ATR% stop su 5m = stop in assoluto molto piu' stretto = piu' rumore.")
print()
print("  CAUSA 2 -- ZONA BREAKEVEN AMPIA (trade 'rumore')  [criticita': {}]".format(cause1_note))
print("  {:.1f}% dei trade 5m finisce tra -0.2R e +0.2R (vs {:.1f}% su 1h).".format(
    noise_5m, noise_1h))
print("  Lo slippage di 0.15R sposta TUTTA questa fascia in negativo.")
print("  Formula: {:.1f}% di trade * 0.15R slippage = {:+.4f}R di danno medio per trade.".format(
    noise_5m, -noise_5m / 100 * 0.15))
print()
print("  CAUSA 3 -- STOP RATE vs 1h  [criticita': {}]".format(cause3_note))
print("  5m: {:.1f}% stop | 1h: {:.1f}% stop | delta: {:+.1f}pp".format(
    stop_pct_5m, stop_pct_1h, stop_pct_5m - stop_pct_1h))
if stop_pct_5m > stop_pct_1h + 5:
    print("  Il 5m prende piu' stop del 1h sugli stessi pattern.")
    print("  Causa: volatilita' intra-barra 5m spesso tocca lo stop prima del TP.")
else:
    print("  Stop rate simile tra 5m e 1h -- il problema non e' lo stop in se'.")
print()
print(SEP)
print("  FIX CONCRETI SUGGERITI")
print(SEP)
print()
print("  FIX 1 -- Allarga il TP su 5m (aumenta avg_win)")
print("  I target TP1/TP2 sono probabilmente calibrati per 1h (es. 1.5R/2.5R).")
print("  Su 5m, usare TP1=2.0R, TP2=3.5R potrebbe aumentare avg_win senza")
print("  cambiare il tasso di fill del TP (il mercato 5m si muove di piu'")
print("  in proporzione alla barra).")
print()
print("  FIX 2 -- Filtro orario: evita ore con avg_r negativo")
print("  Guarda Analisi 8: se alcune fasce orarie sono sistematicamente negative,")
print("  disabilitare il 5m in quelle ore riduce il volume ma migliora avg_r.")
print()
print("  FIX 3 -- Soglia min_strength piu' alta su 5m")
print("  Se Analisi 7 mostra che strength > 0.8 ha avg_r significativamente")
print("  migliore, alzare il filtro da 0.70 a 0.80 taglia i segnali deboli")
print("  (che stanno nella zona rumore -0.2/+0.2R).")
print()
print("  FIX 4 -- Allarga lo stop su 5m (riduce stop prematuri)")
print("  Se l'ATR% usato su 5m e' lo stesso del 1h, lo stop in termini di")
print("  punti di prezzo e' piu' stretto. Raddoppiare il moltiplicatore ATR")
print("  su 5m (es. da 1.5x a 2.5x) riduce i stop prematuri.")
print("  Trade-off: aumenta avg_loss in valore assoluto.")
print()
print("  ORDINE DI PRIORITA':")
print("  1. FIX 2 (filtro orario) -- zero rischio, zero codice")
print("  2. FIX 3 (min_strength)  -- 1 parametro, facile da testare OOS")
print("  3. FIX 1/4 (TP/SL)       -- richiede re-ottimizzazione e nuovo OOS")
print(SEP)
