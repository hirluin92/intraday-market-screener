# OOS Regime Analysis - Alpaca 5m - tutti i pattern x 4 condizioni (universal + bull + bear + neutral)
$logFile = "C:\Lavoro\Trading\intraday-market-screener\oos_regime_log.txt"
$csvFile = "C:\Lavoro\Trading\intraday-market-screener\oos_regime_results.csv"
$base    = "http://localhost:8000/api/v1/backtest/out-of-sample"

function Log($msg) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $msg"
    Write-Host $line
    Add-Content -Path $logFile -Value $line
}

$patterns = @(
    "double_top",
    "double_bottom",
    "macd_divergence_bull",
    "macd_divergence_bear",
    "rsi_momentum_continuation",
    "compression_to_expansion_transition",
    "engulfing_bullish",
    "engulfing_bearish",
    "trend_continuation_pullback",
    "breakout_with_retest",
    "fibonacci_bounce",
    "impulsive_bullish_candle",
    "impulsive_bearish_candle",
    "inside_bar_breakout_bull",
    "resistance_rejection",
    "ema_pullback_to_support",
    "ema_pullback_to_resistance",
    "fvg_retest_bull",
    "fvg_retest_bear",
    "shooting_star_reversal",
    "hammer_reversal",
    "support_bounce",
    "vwap_bounce_bull",
    "vwap_bounce_bear",
    "nr7_breakout",
    "bull_flag",
    "bear_flag",
    "morning_star",
    "evening_star",
    "ob_retest_bull",
    "ob_retest_bear"
)

$regimes = @("", "bull", "bear", "neutral")
$cutoff  = "2025-06-01"

Log "=== OOS REGIME ANALYSIS - Alpaca 5m - cutoff=$cutoff ==="
Log "Pattern: $($patterns.Count) | Regimi: universal + bull + bear + neutral"

# Intestazione CSV
"pattern,regime,train_trades,train_wr,train_ev,test_trades,test_wr,test_ev,degradation_ev,promoted" | Out-File -FilePath $csvFile -Encoding utf8

$total = $patterns.Count * $regimes.Count
$done  = 0

foreach ($pat in $patterns) {
    foreach ($regime in $regimes) {
        $done++
        $regLabel = if ($regime -eq "") { "universal" } else { $regime }
        Log "[$done/$total] $pat | regime=$regLabel"

        $url = "${base}?provider=alpaca&timeframe=5m&pattern_names=${pat}&cutoff_date=${cutoff}&use_regime_filter=true&include_trades=false&min_trades=5"
        if ($regime -ne "") {
            $url = "${url}&only_regime=${regime}"
        }

        try {
            $r = Invoke-RestMethod -Uri $url -Method GET -TimeoutSec 300

            $trTrades = $r.train_set.total_trades
            $trWr     = [math]::Round($r.train_set.win_rate * 100, 1)
            $trEv     = [math]::Round($r.train_set.expectancy_r, 4)
            $teTrades = $r.test_set.total_trades
            $teWr     = [math]::Round($r.test_set.win_rate * 100, 1)
            $teEv     = [math]::Round($r.test_set.expectancy_r, 4)
            $degEv    = if ($trTrades -gt 0) { [math]::Round($teEv - $trEv, 4) } else { "N/A" }
            $prom     = $r.promoted

            Log "  train=$trTrades EV=$trEv | test=$teTrades EV=$teEv | deg=$degEv | promoted=$prom"
            "$pat,$regLabel,$trTrades,$trWr,$trEv,$teTrades,$teWr,$teEv,$degEv,$prom" | Add-Content -Path $csvFile -Encoding utf8
        } catch {
            Log "  FAIL: $($_.Exception.Message)"
            "$pat,$regLabel,ERR,ERR,ERR,ERR,ERR,ERR,ERR,ERR" | Add-Content -Path $csvFile -Encoding utf8
        }
    }
}

Log "=== COMPLETATO - risultati in $csvFile ==="
