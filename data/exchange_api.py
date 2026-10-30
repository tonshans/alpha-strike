import ccxt
import pandas as pd

OHLCV_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]


def _fetch_df(exchange: ccxt.Exchange, symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
    raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    if not raw:
        raise ValueError(f"Empty OHLCV data for {symbol} ({timeframe})")
    df = pd.DataFrame(raw, columns=OHLCV_COLUMNS)
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df[OHLCV_COLUMNS[1:]] = df[OHLCV_COLUMNS[1:]].astype(float)
    return df


def fetch_mtfa_ohlcv(
    exchange_id: str,
    symbol: str,
    micro_tf: str,
    macro_tf: str,
    limit: int = 100,
) -> dict:
    try:
        exchange_cls = getattr(ccxt, exchange_id.lower())
        exchange = exchange_cls({"enableRateLimit": True})

        data = {
            "micro": _fetch_df(exchange, symbol, micro_tf, limit),
            "macro": _fetch_df(exchange, symbol, macro_tf, limit),
        }

        # shortcut: hardcodes BTC/USDT for King's Filter, fallback to BTC/IDR if local exchange lacks USDT pair
        if symbol.upper().split("/")[0] != "BTC":
            data["btc_macro"] = _fetch_df(exchange, "BTC/USDT", macro_tf, limit)

        return data
    except Exception as exc:
        return {"error": f"[{exchange_id}:{symbol}] {type(exc).__name__}: {exc}"}


if __name__ == "__main__":
    err_res = fetch_mtfa_ohlcv("invalid_exchange", "ETH/USDT", "15m", "4h")
    assert "error" in err_res, "Expected controlled error dict on invalid exchange"
