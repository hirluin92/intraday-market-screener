$syms = @("GOOGL","TSLA","AMD","META","NVDA","NFLX","COIN","MSTR","HOOD","SHOP","SOFI","ZS","NET","CELH","RBLX","PLTR","MDB","SMCI","DELL","NVO","LLY","MRNA","NKE","TGT","SCHW","WMT","SPY","AAPL","AMZN","MSFT")
$logFile = "C:\Lavoro\Trading\intraday-market-screener\pipeline_backfill_log.txt"
$base = "http://localhost:8000/api/v1"

function Log($msg) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $msg"
    Write-Host $line
    Add-Content -Path $logFile -Value $line
}

Log "=== INIZIO PIPELINE BACKFILL 2 ANNI ALPACA 5m ==="

# FASE 1: BACKFILL CANDLES 2 ANNI
Log "FASE 1: Download candle 2 anni per 30 simboli..."
$symQS = ($syms | ForEach-Object { "symbols=$_" }) -join "&"
$bfUrl = "$base/backtest/alpaca-backfill?timeframes=5m&years=2&$symQS"
try {
    $bf = Invoke-RestMethod -Uri $bfUrl -Method POST -TimeoutSec 14400
    Log "BACKFILL OK: candles_received=$($bf.candles_received) rows_inserted=$($bf.rows_inserted)"
} catch {
    Log "BACKFILL ERRORE: $($_.Exception.Message)"
}

# FASE 2: FEATURE EXTRACTION (42000 barre coprono ~2 anni a 5m)
Log "FASE 2: Feature extraction..."
foreach ($sym in $syms) {
    $body = @{ provider="alpaca"; exchange="ALPACA_US"; symbol=$sym; timeframe="5m"; limit=42000 } | ConvertTo-Json -Compress
    try {
        $r = Invoke-RestMethod -Uri "$base/features/extract" -Method POST -Body $body -ContentType "application/json" -TimeoutSec 600
        Log "FE OK $sym series=$($r.series_processed) candles=$($r.candles_read)"
    } catch {
        Log "FE FAIL $sym $($_.Exception.Message)"
    }
}

# FASE 3: CONTEXT EXTRACTION
Log "FASE 3: Context extraction..."
foreach ($sym in $syms) {
    $body = @{ provider="alpaca"; exchange="ALPACA_US"; symbol=$sym; timeframe="5m"; limit=42000; lookback=100 } | ConvertTo-Json -Compress
    try {
        $r = Invoke-RestMethod -Uri "$base/context/extract" -Method POST -Body $body -ContentType "application/json" -TimeoutSec 600
        Log "CTX OK $sym features=$($r.features_read) upserted=$($r.contexts_upserted)"
    } catch {
        Log "CTX FAIL $sym $($_.Exception.Message)"
    }
}

# FASE 4: PATTERN EXTRACTION
Log "FASE 4: Pattern extraction..."
foreach ($sym in $syms) {
    $body = @{ provider="alpaca"; exchange="ALPACA_US"; symbol=$sym; timeframe="5m"; limit=42000 } | ConvertTo-Json -Compress
    try {
        $r = Invoke-RestMethod -Uri "$base/patterns/extract" -Method POST -Body $body -ContentType "application/json" -TimeoutSec 1200
        Log "PAT OK $sym rows=$($r.rows_read) patterns=$($r.patterns_upserted)"
    } catch {
        Log "PAT FAIL $sym $($_.Exception.Message)"
    }
}

Log "=== PIPELINE COMPLETATO ==="
