$syms = @("GOOGL","TSLA","AMD","META","NVDA","NFLX","COIN","MSTR","HOOD","SHOP","SOFI","ZS","NET","CELH","RBLX","PLTR","MDB","SMCI","DELL","NVO","LLY","MRNA","NKE","TGT","SCHW","WMT","SPY","AAPL","AMZN","MSFT")
$logFile = "C:\Lavoro\Trading\intraday-market-screener\pipeline_ind_pat_log.txt"
$base    = "http://localhost:8000/api/v1/market-data"

function Log($msg) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $msg"
    Write-Host $line
    Add-Content -Path $logFile -Value $line
}

Log "=== FASE 3b: Indicator extraction 30 simboli Alpaca 5m (42000 barre) ==="
$ok = 0; $fail = 0
foreach ($sym in $syms) {
    $body = @{ provider="alpaca"; exchange="ALPACA_US"; symbol=$sym; timeframe="5m"; limit=42000 } | ConvertTo-Json -Compress
    try {
        $r = Invoke-RestMethod -Uri "$base/indicators/extract" -Method POST -Body $body -ContentType "application/json" -TimeoutSec 600
        Log "IND OK $sym candles=$($r.candles_read) upserted=$($r.indicators_upserted)"
        $ok++
    } catch {
        Log "IND FAIL $sym $($_.Exception.Message)"
        $fail++
    }
}
Log "FASE 3b completata: OK=$ok FAIL=$fail"

Log "=== FASE 4b: Pattern extraction 30 simboli Alpaca 5m (42000 barre, con indicatori aggiornati) ==="
$ok = 0; $fail = 0
foreach ($sym in $syms) {
    $body = @{ provider="alpaca"; exchange="ALPACA_US"; symbol=$sym; timeframe="5m"; limit=42000 } | ConvertTo-Json -Compress
    try {
        $r = Invoke-RestMethod -Uri "$base/patterns/extract" -Method POST -Body $body -ContentType "application/json" -TimeoutSec 300
        Log "PAT OK $sym rows=$($r.rows_read) patterns=$($r.patterns_upserted)"
        $ok++
    } catch {
        Log "PAT FAIL $sym $($_.Exception.Message)"
        $fail++
    }
}
Log "FASE 4b completata: OK=$ok FAIL=$fail"

Log "=== PIPELINE COMPLETATO ==="
