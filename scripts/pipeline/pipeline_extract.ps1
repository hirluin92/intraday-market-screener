$syms = @("GOOGL","TSLA","AMD","META","NVDA","NFLX","COIN","MSTR","HOOD","SHOP","SOFI","ZS","NET","CELH","RBLX","PLTR","MDB","SMCI","DELL","NVO","LLY","MRNA","NKE","TGT","SCHW","WMT","SPY","AAPL","AMZN","MSFT")
$logFile = "C:\Lavoro\Trading\intraday-market-screener\pipeline_extract_log.txt"
$base = "http://localhost:8000/api/v1/market-data"

function Log($msg) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $msg"
    Write-Host $line
    Add-Content -Path $logFile -Value $line
}

Log "=== INIZIO ESTRAZIONE 2 ANNI ALPACA 5m (42000 barre/simbolo) ==="
Log "Candles gia presenti nel DB dal backfill 3 anni precedente."

# FASE 2: FEATURE EXTRACTION
Log "FASE 2: Feature extraction (42000 barre per simbolo)..."
$ok2 = 0; $fail2 = 0
foreach ($sym in $syms) {
    $body = @{ provider="alpaca"; exchange="ALPACA_US"; symbol=$sym; timeframe="5m"; limit=42000 } | ConvertTo-Json -Compress
    try {
        $r = Invoke-RestMethod -Uri "$base/features/extract" -Method POST -Body $body -ContentType "application/json" -TimeoutSec 600
        Log "FE OK $sym series=$($r.series_processed) candles=$($r.candles_read)"
        $ok2++
    } catch {
        Log "FE FAIL $sym $($_.Exception.Message)"
        $fail2++
    }
}
Log "FASE 2 completata: OK=$ok2 FAIL=$fail2"

# FASE 3: CONTEXT EXTRACTION
Log "FASE 3: Context extraction (42000 barre per simbolo)..."
$ok3 = 0; $fail3 = 0
foreach ($sym in $syms) {
    $body = @{ provider="alpaca"; exchange="ALPACA_US"; symbol=$sym; timeframe="5m"; limit=42000; lookback=100 } | ConvertTo-Json -Compress
    try {
        $r = Invoke-RestMethod -Uri "$base/context/extract" -Method POST -Body $body -ContentType "application/json" -TimeoutSec 600
        Log "CTX OK $sym features=$($r.features_read) upserted=$($r.contexts_upserted)"
        $ok3++
    } catch {
        Log "CTX FAIL $sym $($_.Exception.Message)"
        $fail3++
    }
}
Log "FASE 3 completata: OK=$ok3 FAIL=$fail3"

# FASE 4: PATTERN EXTRACTION
Log "FASE 4: Pattern extraction (42000 barre per simbolo)..."
$ok4 = 0; $fail4 = 0
foreach ($sym in $syms) {
    $body = @{ provider="alpaca"; exchange="ALPACA_US"; symbol=$sym; timeframe="5m"; limit=42000 } | ConvertTo-Json -Compress
    try {
        $r = Invoke-RestMethod -Uri "$base/patterns/extract" -Method POST -Body $body -ContentType "application/json" -TimeoutSec 1200
        Log "PAT OK $sym rows=$($r.rows_read) patterns=$($r.patterns_upserted)"
        $ok4++
    } catch {
        Log "PAT FAIL $sym $($_.Exception.Message)"
        $fail4++
    }
}
Log "FASE 4 completata: OK=$ok4 FAIL=$fail4"

Log "=== PIPELINE ESTRAZIONE COMPLETATO ==="
