# core/scanner.py
import ccxt
import pandas as pd
import pandas_ta as ta


def evaluate_squeeze_and_spike(df: pd.DataFrame) -> dict:
    if len(df) < 24:
        return {"passed": False, "reason": "Insufficient OHLCV rows (< 24)"}

    work = df.copy()

    if "EMA_20" not in work.columns:
        work["EMA_20"] = ta.ema(work["close"], length=20)

    if "BB_Upper" not in work.columns or "BB_Lower" not in work.columns:
        bb = ta.bbands(work["close"], length=20, std=2)
        bbu_col = [c for c in bb.columns if c.startswith("BBU_")][0]
        bbl_col = [c for c in bb.columns if c.startswith("BBL_")][0]
        work["BB_Upper"] = bb[bbu_col]
        work["BB_Lower"] = bb[bbl_col]

    if "Vol_SMA_24" not in work.columns:
        work["Vol_SMA_24"] = ta.sma(work["volume"], length=24)

    last = work.iloc[-1]
    bb_upper = float(last["BB_Upper"])
    bb_lower = float(last["BB_Lower"])
    ema_20 = float(last["EMA_20"])
    vol_last = float(last["volume"])
    vol_sma_24 = float(last["Vol_SMA_24"])

    if pd.isna(ema_20) or ema_20 == 0.0 or pd.isna(vol_sma_24) or vol_sma_24 == 0.0:
        return {"passed": False, "reason": "NaN or zero indicator value"}

    squeeze_ratio = (bb_upper - bb_lower) / ema_20
    spike_threshold = 3.0 * vol_sma_24
    spike_ratio = vol_last / vol_sma_24

    is_squeeze = squeeze_ratio < 0.05
    is_spike = vol_last > spike_threshold
    passed = bool(is_squeeze and is_spike)

    return {
        "passed": passed,
        "is_squeeze": bool(is_squeeze),
        "is_spike": bool(is_spike),
        "squeeze_ratio": squeeze_ratio,
        "spike_ratio": spike_ratio,
        "volume_last": vol_last,
        "vol_sma_24": vol_sma_24,
        "close": float(last["close"]),
    }


def _extract_quote_volume(ticker: dict) -> float:
    qv = ticker.get("quoteVolume")
    if qv is not None:
        return float(qv)
    bv = ticker.get("baseVolume")
    last = ticker.get("last")
    if bv is not None and last is not None:
        return float(bv) * float(last)
    return 0.0


def scan_market(
    exchange_id: str = "binance",
    timeframe: str = "15m",
    ohlcv_limit: int = 50,
    top_n: int = 5,
) -> dict:
    ex_id = exchange_id.lower()
    is_indodax = ex_id == "indodax"
    quote_currency = "IDR" if is_indodax else "USDT"
    min_quote_vol = 1_000_000_000.0 if is_indodax else 1_000_000.0

    try:
        exchange_cls = getattr(ccxt, ex_id)
        exchange = exchange_cls({"enableRateLimit": True})
        tickers = exchange.fetch_tickers()
    except Exception as exc:
        return {
            "status": "error",
            "exchange": ex_id,
            "error": f"Failed to fetch tickers: {exc}",
            "top_results": [],
        }

    # Filter pasangan mata uang utama dan likuiditas minimum 24H
    liquid_symbols = []
    suffix = f"/{quote_currency}"
    for symbol, t_data in tickers.items():
        if not symbol.endswith(suffix):
            continue
        q_vol = _extract_quote_volume(t_data)
        if q_vol >= min_quote_vol:
            liquid_symbols.append((symbol, q_vol))

    matches = []
    errors = []

    for symbol, q_vol in liquid_symbols:
        try:
            raw_ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=ohlcv_limit)
            if not raw_ohlcv or len(raw_ohlcv) < 24:
                continue

            df = pd.DataFrame(
                raw_ohlcv,
                columns=["timestamp", "open", "high", "low", "close", "volume"],
            )
            eval_res = evaluate_squeeze_and_spike(df)
            if eval_res.get("passed"):
                matches.append({
                    "symbol": symbol,
                    "quote_volume_24h": q_vol,
                    **eval_res,
                })
        except Exception as exc:
            errors.append({"symbol": symbol, "error": str(exc)})

    # Urutkan dari rasio lonjakan volume tertinggi dan ambil Top 5
    matches.sort(key=lambda x: x["spike_ratio"], reverse=True)
    top_results = matches[:top_n]

    return {
        "status": "ok",
        "exchange": ex_id,
        "timeframe": timeframe,
        "min_quote_volume_threshold": min_quote_vol,
        "scanned_liquid_pairs": len(liquid_symbols),
        "matched_count": len(matches),
        "top_results": top_results,
        "errors": errors,
    }


if __name__ == "__main__":
    # Self-check: 29 candle stabil + 1 candle terakhir dengan BB Squeeze (<0.05) & Volume Spike (>3x SMA24)
    rows = [
        {"open": 100.0, "high": 100.2, "low": 99.8, "close": 100.0, "volume": 100.0}
        for _ in range(29)
    ]
    rows.append({"open": 100.0, "high": 100.5, "low": 99.9, "close": 100.3, "volume": 500.0})
    df_test = pd.DataFrame(rows)

    res = evaluate_squeeze_and_spike(df_test)
    assert res["is_squeeze"] is True, f"Expected squeeze, got {res['squeeze_ratio']}"
    assert res["is_spike"] is True, f"Expected spike, got {res['spike_ratio']}"
    assert res["passed"] is True
