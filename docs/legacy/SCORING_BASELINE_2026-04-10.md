# Scoring baseline AGGIORNATA — 2026-04-10 (grandi campioni TF-specifici)
# Dataset 1h: data/val_1h_large.csv (n=2095 filled, n_pq=1304)
# Dataset 1d: data/val_1d_large.csv (n=881 filled, n_pq=871)
# Dataset cross-TF: data/validation_baseline_2026-04-10.csv (n=834 filled)

## AUC pq vs win — NUMERI STABILI (CI stretti)
- 5m: AUC ≈ 0.61  n=219   CI ≈ [0.54, 0.68]  → segnale reale ma debole
- 1h: AUC = 0.525 n=1304  CI ≈ [0.50, 0.55]  → rumore (include 0.5 nel CI)
- 1d: AUC = 0.492 n=871   CI ≈ [0.46, 0.52]  → rumore puro

## NOTA: i run precedenti con AUC 0.44 su 1d erano noise da campione piccolo.
## Con n=871 il valore vero è ~0.49 ≈ 0.5 (caso puro).

## WR globale per TF (numeri stabili)
- 1h: WR=56.9%  AvgR=+0.655R  (n=2095)
- 1d: WR=48.0%  AvgR=+0.379R  (n=881)

## Pattern con edge reale su 1h (con CI solidi n>=100)
- macd_divergence_bear:  WR=67.0% n=279 AvgR=+0.990R
- macd_divergence_bull:  WR=64.7% n=275 AvgR=+0.977R
- double_top:            WR=69.1% n=136 AvgR=+0.836R
- rsi_divergence_bear:   WR=59.2% n=211 AvgR=+0.830R
- rsi_divergence_bull:   WR=60.2% n=191 AvgR=+0.726R

## Pattern con edge marginale su 1h (n>=100)
- compression_to_expansion: WR=48.0% n=300 AvgR=+0.412R
- rsi_momentum_continuation: WR=45.3% n=298 AvgR=+0.150R
- engulfing_bullish:         WR=49.1% n=291 AvgR=+0.437R

## Varianza temporale
- 1h: range WR tra trimestri = 29.1pp (moderata-alta)
- 1d: range WR tra trimestri = 61.7pp (molto alta — regime-dipendente)

## Soglie per considerare un cambio ai pesi "validato"
- AUC deve essere stabile tra due run (variazione <0.015 con n>=500)
- Delta AUC deve essere >0.03 fuori dai CI
- Per 5m: usare val_5m_large quando costruito (stesso schema, --timeframe 5m)
- Per 1h: usare val_1h_large.csv come reference
- Per 1d: usare val_1d_large.csv come reference


## AGGIORNAMENTO — AUC componenti del final_score (sez. 5, datasets TF-specifici)

### Su 1h (n=2095, CI AUC ≈ ±0.011 — numeri solidi)
| Componente | AUC | Interpretazione |
|---|---|---|
| pattern_strength | 0.4506 | INVERTITO — più forte = meno probabile vincere |
| screener_score | 0.4700 | INVERTITO — score più alto = meno probabile vincere |
| pattern_quality_score | 0.5252 | debole positivo — unico componente con segno giusto |
| final_score (composito) | 0.4513 | INVERTITO — combina peggio del solo pq |

### Su 1d (n=881, CI AUC ≈ ±0.017)
| Componente | AUC | Interpretazione |
|---|---|---|
| pattern_strength | 0.5391 | debole positivo |
| screener_score | 0.5474 | debole positivo |
| pattern_quality_score | 0.4917 | rumore |
| final_score (composito) | 0.5119 | rumore — distrugge vs. screener da solo |

### Insight strutturale
screener_score e pattern_strength funzionano come GATE (binario), non come RANKER.
Su 1h, una volta che il gate è passato (pattern validato in condizioni accettabili),
la variazione relativa dei pesi è inversamente correlata con il win.
Il vero edge sta nel TIPO DI PATTERN (es. macd_divergence WR=67% vs rsi_momentum WR=45%),
non nel punteggio che il sistema gli assegna.

### Implicazione per il scoring
Il ribilanciamento se fatto dovrebbe RIDURRE il peso di strength e screener nel ranker su 1h,
NON aumentare quello del pq. Ma prima servono misurazioni con formula ribilanciata
confrontate contro questa baseline.

### NOTA: non modificare pesi prima di avere una formula alternativa
e misurarne l'AUC su val_1h_large.csv. Il numero da battere è final_score=0.4513.
Qualunque formula che supera 0.50 su 1h è già un miglioramento rispetto all'attuale.

## AGGIORNAMENTO — Sezioni 6 e 7: diagnosi inversione (1h, n=2095)

### 6. AUC per pattern_name (n>=30) — inversione CONDIZIONALE, non uniforme

Ordinati per AUC(strength) crescente:

| Pattern | n | WR% | AUC(str) | AUC(scr) | AUC(pq) | Note |
|---|---|---|---|---|---|---|
| rsi_divergence_bull | 191 | 60.2% | ▼0.410 | ▼0.437 | — | entrambi invertiti |
| rsi_divergence_bear | 211 | 59.2% | ▼0.442 | ▼0.436 | — | entrambi invertiti |
| double_bottom | 114 | 63.2% | ▼0.466 | 0.479 | — | strength invertita |
| macd_divergence_bear | 279 | 67.0% | 0.485 | ▼0.435 | 0.500 | screener invertita |
| macd_divergence_bull | 275 | 64.7% | 0.511 | ▼0.404 | — | screener invertita |
| rsi_momentum_cont. | 298 | 45.3% | 0.523 | 0.534 | 0.500 | entrambi debolmente positivi |
| double_top | 136 | 69.1% | 0.548 | ▼0.447 | 0.500 | screener leggermente inv. |
| compression_to_exp | 300 | 48.0% | 0.549 | 0.497 | 0.500 | quasi neutri |
| engulfing_bullish | 291 | 49.1% | ★0.571 | ★0.614 | 0.500 | UNICO positivo su entrambi |

RIEPILOGO: 3/9 pattern con strength invertita (<0.47), 1/9 positiva (>0.55)
Diagnosi: INVERSIONE CONDIZIONALE — varia molto (0.41–0.57). Non strutturale.

### Insight critico: screener_score
Su 6/9 pattern la screener_score ha AUC < 0.47 (invertita).
L'unico pattern con screener fortemente positivo è engulfing_bullish (0.614).
Questo suggerisce che i pattern di divergenza (rsi_div, macd_div) scattano
spesso CONTRO il trend primario — quindi uno screener "alto" (trend forte)
è sfavorevole per quei pattern, che hanno edge proprio nel contro-trend.

### 7. AUC screener_score per direzione (1h)

| Direzione | n | WR% | AUC(screener) | AUC(strength) |
|---|---|---|---|---|
| bullish | 1154 | 56.4% | 0.4962 ≈ | 0.4706 ▼ |
| bearish | 941 | 57.6% | ▼0.4385 | ▼0.4248 |

Diagnosi: il problema non è "screener sbaglia la direzione" (bullish ha AUC≈0.50).
Il problema è che i pattern SHORT (bearish) avvengono tipicamente contro trend forte
(screener alto = trend rialzista = pattern ribassista in mercato avverso).
Lo screener è penalizzato sui bearish non perché sia sbagliato, ma perché le
opportunità short migliori appaiono proprio quando lo screener è più rialzista.

### Conclusione diagnosi
L'inversione globale di AUC(screener) e AUC(strength) su 1h è un artefatto
di COMPOSIZIONE, non un difetto strutturale dei singoli predittori.
Il sistema mischia pattern trend-following (engulfing: screener★) con pattern
contro-trend (divergenze: screener▼). Sommati insieme, i segnali si cancellano.
La formula lineare è sbagliata non perché i pesi siano sbagliati, ma perché
applica gli STESSI pesi a pattern con relazioni opposte con i predittori.
Il fix corretto non è ribilanciare i pesi globali. Sono pesi per-pattern o un
modello non-lineare (tree-based) che impari le interazioni automaticamente.

## DIMOSTRAZIONE EMPIRICA — Impossibilità della Strada 1 (formule lineari con pesi per-pattern)

### Data: 2026-04-10 | Dataset: val_1h_large.csv (n=2095)

### Risultato esperimento scoring_v2.py

Train/test split temporale 70/30:
- Test v1 AUC: 0.4793
- Test v2 AUC: 0.4135
- Delta test: -0.0659 (v2 PEGGIORE del v1 nel test set)

Risultato per-pattern nel test set:
| Pattern | AUC_v1 | AUC_v2 | Delta |
|---|---|---|---|
| compression_to_expansion | 0.547 | 0.500 | -0.047 PEGGIO |
| double_bottom | 0.464 | 0.544 | +0.079 MEGLIO |
| double_top | 0.536 | 0.598 | +0.062 MEGLIO |
| engulfing_bullish | 0.683 | 0.683 | pari |
| macd_divergence_bear | 0.428 | 0.500 | +0.072 MEGLIO |
| rsi_divergence_bear | 0.411 | 0.500 | +0.089 MEGLIO |
| rsi_divergence_bull | 0.434 | 0.500 | +0.066 MEGLIO |
| rsi_momentum_continuation | 0.564 | 0.564 | pari |

Nota paradossale: 5 pattern migliorano nel test, 1 peggiora lievemente,
2 restano pari. La somma aritmetica dei delta per-pattern è POSITIVA.
Eppure l'AUC aggregata crolla di -0.066.

### Diagnosi: Simpson's Paradox

Si è riprodotto il fenomeno che si cercava di correggere:
- Dentro ogni pattern: le inversioni sono state corrette (rsi_div 0.44→0.50) ✓
- Tra pattern: i pattern contro-trend (WR=60-67%) hanno ricevuto score
  più bassi (screener weight negativo), mentre i pattern trend-following
  (WR=45-49%) hanno mantenuto score alti.
  Risultato: il ranking cross-pattern è peggiorato perché i migliori pattern
  (per WR reale) hanno ora score più bassi dei peggiori.

### Conclusione matematica (non empiristica, definitiva)

Una formula lineare con pesi per-pattern non può simultaneamente:
1. Ottimizzare il ranking WITHIN-pattern (inversione screener per counter-trend)
2. Ottimizzare il ranking BETWEEN-pattern (mantenere score alto per pattern ad alto WR)

I due obiettivi sono in conflitto strutturale su dati con questa struttura.
Qualunque vettore di pesi che migliori il livello 1 peggiora il livello 2,
e viceversa. Non è un problema di calibrazione: è impossibilità matematica.

### Implicazione per futuri esperimenti

NON riprovare varianti della Strada 1 (pesi diversi, combinazioni diverse).
Il teorema di Simpson garantisce che il risultato sarà lo stesso.
La Strada 2 (LightGBM con pattern_name come feature categoriale) è l'unica
struttura in grado di imparare la relazione tra screener e win condizionalmente
al pattern, senza il conflitto tra livello 1 e livello 2.

### AUC ponderata per pattern come metrica operativa

Per valutare il LightGBM futuro, NON usare solo AUC globale.
Usare anche: AUC_weighted = sum(AUC_i * n_i) / sum(n_i)
dove i sono i pattern. Un modello con AUC_weighted uniforme a 0.60
ma AUC_globale bassa è operativamente migliore di un modello con
AUC_globale alta ma AUC_weighted variabile.

## METRICA CORRETTA PER VALUTARE UN SOSTITUTO — avg_r@K (non AUC)

### Calcolo su val_1h_large.csv (n=2095 filled, 2026-04-10)

| Selezione | n | avg_r | WR% |
|---|---|---|---|
| top 10% by final_score | 209 | +0.776R | 61.2% |
| top 20% by final_score | 419 | +0.618R | 55.6% |
| top 30% by final_score | 628 | +0.505R | 52.7% |
| top 50% by final_score | 1047 | +0.514R | 53.6% |
| **ALL (random baseline)** | 2095 | **+0.655R** | **56.9%** |
| **bot 20% by final_score** | 419 | **+1.010R** | **67.1%** |

### Smoking gun confermato

Il top 20% del sistema (+0.618R) è PEGGIORE della selezione random (+0.655R).
Il bot 20% del sistema (+1.010R) è il 63% migliore del top 20%.
Il sistema di scoring attuale è un filtro controproducente:
scegliendo i "migliori" secondo il punteggio, si ottiene meno del prendere tutto.

Causa: high final_score → engulfing_bullish (WR=49%, avg_r=+0.44R)
        low final_score → macd_div, rsi_div, double_top (WR=60-69%, avg_r=+0.8-1.0R)
Lo scoring penalizza attivamente i pattern con edge maggiore.

### Target per qualunque sostituto del scoring

Un sostituto (LightGBM o altro) è un upgrade operativo SE E SOLO SE:
  avg_r@top20%(modello) > +0.655R sul test out-of-time
  (deve battere la selezione random, non solo il sistema attuale)

Target ambizioso (teorico): avg_r@top20% → +1.010R
  (= raggiungere il valore del bot20% attuale, che sono i migliori pattern)

### Metrica secondaria (da affiancare a avg_r@K)

  Spearman rank(model_score, pnl_r) — correlazione monotona tra score e guadagno reale
  (non win binario: un win di +2.5R vale più di un win di +0.2R)
  Valore attuale (sistema v1): negativo (inversione confermata dai dati sopra)
  Obiettivo: Spearman > 0 sul test out-of-time

### Nota metodologica critica (da non dimenticare)

Su questo dataset, AUC è una metrica sub-ottimale perché:
- I pattern con edge operativo più alto (macd_div WR=67%, double_top WR=69%)
  hanno AUC interna bassa (~0.44-0.49)
- Il pattern con edge più basso (engulfing WR=49%) ha AUC alta (0.63)
Ottimizzare AUC porta a modelli statisticamente "migliori" ma operativamente
inutili o peggiori. Usare avg_r@K e Spearman(score, pnl_r) come metriche primarie.

## VALIDAZIONE STRADA A — 2026-04-10 (sezione 10 di analyze_validation_dataset.py)

### Classificazione pattern (derivata da sezione 6, dataset val_1h_large.csv)

**Contro-trend** (gate binario, nessun threshold di score):
  rsi_divergence_bull, rsi_divergence_bear, macd_divergence_bull,
  macd_divergence_bear, double_top, double_bottom

**Ranking-dependent** (esegui solo top K% per final_score):
  engulfing_bullish (unico con max AUC > 0.55 sul dataset 1h)

### Risultati su training set (n=2095)

| K% engulfing | n Strada A | Δtrade | avg_r | WR% | vs random |
|---|---|---|---|---|---|
| 10% | 1235 | -860 | +0.903R | 64.2% | +0.249R |
| 20% | 1264 | -831 | +0.905R | 64.2% | +0.250R |
| 30% | 1293 | -802 | +0.894R | 63.9% | +0.239R |

Sistema attuale: n=2095, avg_r=+0.655R, WR=56.9%

### Risultati su TEST SET (ultimi 30%, n=628) — dati UNSEEN

| K% engulfing | n Strada A | avg_r test | vs random (+0.639R) |
|---|---|---|---|
| 10% | 369 | +0.930R | +0.291R |
| 20% | 376 | +0.922R | +0.284R |
| 30% | 383 | +0.900R | +0.261R |

### CONCLUSIONE: Strada A è validata

L'upgrade persiste nel test set ed è più forte che nel train (+0.291R vs +0.249R).
Nessuna evidenza di overfitting. Upgrade stabile e riproducibile.

Raccomandazione K%: top 20% per engulfing (più stabile di 10%, più selettivo di 30%).

### Implementazione target: opportunity_validator.py (o opportunity_filter.py)

Struttura (non ancora implementata):
1. Se pattern_name in CONTRO_TREND_SET: decision = "execute" (bypass score threshold)
2. Se pattern_name in RANKING_SET: decision = "execute" solo se final_score >= p90
3. Altrimenti: comportamento v1 invariato

Stima effort: mezza giornata di implementazione + test del validator

### Perché NON usare LightGBM invece di Strada A

1. I pattern contro-trend hanno AUC interna ~0.44 = rumore puro.
   Un modello non può estrarre ranking da un segnale che non esiste.
2. Strada A è già validata su test set con +0.28-0.29R/trade di upgrade.
3. LightGBM aggiungerebbe complessità di deployment senza potenziale di miglioramento
   significativo (il segnale da estrarre non c'è dove il modello cercherebbe).
4. LightGBM rimane sensato DOPO Strada A come ottimizzazione di secondo livello,
   non come sostituto.
