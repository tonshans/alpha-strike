from typing import Any, Dict, List, Optional
import pandas as pd
from core.indicators import compute_indicators
from data.exchange_api import ExchangeAPI


class MarketScanner:
    """
    Modul Market Scanner sesuai PRD Bagian 2.E:
      - Filter Likuiditas: Drop koin dengan Quote Volume 24H < $1 Juta (Binance)
        atau < Rp 1 Miliar (Indodax).
      - BB Squeeze: (BB_Upper(20,2) - BB_Lower(20,2)) / EMA(20) < 0.05
      - Volume Spike: Volume(1 candle terakhir) > 3 * Vol_SMA(24)
      - Output: List Top 3-5 koin yang memenuhi kriteria Squeeze + Spike secara bersamaan.
    """

    def __init__(self, api: ExchangeAPI):
        self.api = api

    def get_liquidity_threshold(self, symbol: str) -> float:
        if self.api.exchange_id == "indodax" or symbol.endswith("/IDR"):
            return 1_000_000_000.0  # Rp 1 Miliar
        return 1_000_000.0  # $1 Juta (Binance / USDT)

    @staticmethod
    def evaluate_symbol_df(
        symbol: str,
        df: pd.DataFrame,
        min_quote_vol_24h: float,
        candles_per_24h: int = 24,
        ticker_quote_vol_24h: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Mengevaluasi satu DataFrame OHLCV apakah lolos Filter Likuiditas, BB Squeeze, dan Volume Spike.
        """
        ind = compute_indicators(df)
        last = ind.iloc[-1]

        # Hitung Quote Volume 24H dari ticker atau jumlah 24H candle terakhir
        if ticker_quote_vol_24h is not None and ticker_quote_vol_24h > 0:
            quote_vol_24h = float(ticker_quote_vol_24h)
        else:
            quote_vol_24h = float(ind["QUOTE_VOLUME"].tail(candles_per_24h).sum())

        if quote_vol_24h < min_quote_vol_24h:
            return None

        bb_squeeze_val = float(last["BB_SQUEEZE_RATIO"]) if pd.notna(last["BB_SQUEEZE_RATIO"]) else 999.0
        vol_now = float(last["volume"])
        vol_sma_24 = float(last["VOL_SMA_24"]) if pd.notna(last["VOL_SMA_24"]) else 0.0

        is_squeeze = bb_squeeze_val < 0.05
        is_spike = vol_sma_24 > 0 and (vol_now > 3.0 * vol_sma_24)

        if is_squeeze and is_spike:
            spike_ratio = vol_now / vol_sma_24
            return {
                "symbol": symbol,
                "close": round(float(last["close"]), 6),
                "quote_volume_24h": round(quote_vol_24h, 2),
                "bb_squeeze_ratio": round(bb_squeeze_val, 4),
                "volume_spike_ratio": round(spike_ratio, 2),
                "rsi_14": round(float(last["RSI_14"]), 2),
            }
        return None

    def scan_market(
        self,
        symbols: List[str],
        timeframe: str = "1h",
        top_n: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Memindai daftar simbol dan mengembalikan Top 3-5 koin yang memenuhi Squeeze + Spike.
        """
        tf_map = {"15m": 96, "30m": 48, "1h": 24, "4h": 6, "1d": 1}
        candles_24h = tf_map.get(timeframe.lower(), 24)

        tickers = {}
        try:
            tickers = self.api.fetch_tickers(symbols)
        except Exception:
            tickers = {}

        matches: List[Dict[str, Any]] = []
        for sym in symbols:
            threshold = self.get_liquidity_threshold(sym)
            ticker_qv = None
            if sym in tickers and tickers[sym].get("quoteVolume") is not None:
                ticker_qv = float(tickers[sym]["quoteVolume"])
                if ticker_qv < threshold:
                    continue  # Pre-filter likuiditas instan tanpa perlu tarik OHLCV

            try:
                df = self.api.fetch_ohlcv_df(sym, timeframe=timeframe, limit=max(60, candles_24h + 30))
                res = self.evaluate_symbol_df(
                    symbol=sym,
                    df=df,
                    min_quote_vol_24h=threshold,
                    candles_per_24h=candles_24h,
                    ticker_quote_vol_24h=ticker_qv,
                )
                if res is not None:
                    matches.append(res)
            except Exception:
                continue

        # Urutkan berdasarkan rasio Volume Spike tertinggi
        matches.sort(key=lambda x: x["volume_spike_ratio"], reverse=True)
        return matches[: max(3, min(top_n, 5))]
