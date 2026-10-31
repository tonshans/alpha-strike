from typing import Any, Dict, List, Optional

import pandas as pd

from core.config import get_config
from core.indicators import compute_indicators
from data.exchange_api import ExchangeAPI


class MarketScanner:
    """
    Modul Market Scanner sesuai PRD Bagian 2.E.

    Seluruh ambang batas (likuiditas, BB Squeeze, volume spike, jumlah hasil,
    dan peta candle per 24 jam) dibaca dari ``config.yaml``.
    """

    def __init__(self, api: ExchangeAPI, config: Optional[Dict[str, Any]] = None):
        self.api = api
        self.config = config if config is not None else get_config()

    def get_liquidity_threshold(
        self,
        symbol: str,
        config: Optional[Dict[str, Any]] = None,
    ) -> float:
        """Mengembalikan ambang quote volume 24 jam sesuai exchange/quote pair."""
        cfg = config if config is not None else self.config
        thresholds = cfg["scanner"]["liquidity_threshold"]

        if self.api.exchange_id == "indodax":
            return float(thresholds["indodax"])
        if symbol.upper().endswith("/IDR"):
            return float(thresholds["idr_quote"])
        return float(thresholds.get(self.api.exchange_id, thresholds["default"]))

    @staticmethod
    def evaluate_symbol_df(
        symbol: str,
        df: pd.DataFrame,
        min_quote_vol_24h: float,
        candles_per_24h: Optional[int] = None,
        ticker_quote_vol_24h: Optional[float] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Mengevaluasi satu DataFrame OHLCV apakah lolos Filter Likuiditas,
        BB Squeeze, dan Volume Spike.
        """
        cfg = config if config is not None else get_config()
        scanner_cfg = cfg["scanner"]

        if candles_per_24h is None:
            candles_per_24h = int(scanner_cfg["default_candles_per_24h"])

        squeeze_threshold = float(scanner_cfg["squeeze_threshold"])
        volume_spike_multiplier = float(scanner_cfg["volume_spike_multiplier"])
        invalid_squeeze_fallback = float(scanner_cfg["squeeze_invalid_fallback"])

        output_cfg = cfg["output"]
        price_decimals = int(output_cfg["price_decimals"])
        volume_decimals = int(output_cfg["volume_decimals"])
        indicator_decimals = int(output_cfg["indicator_decimals"])
        squeeze_decimals = int(output_cfg["squeeze_decimals"])
        ratio_decimals = int(output_cfg["ratio_decimals"])

        ind = compute_indicators(df, config=cfg)
        last = ind.iloc[-1]

        # Hitung Quote Volume 24H dari ticker atau jumlah 24H candle terakhir
        if ticker_quote_vol_24h is not None and ticker_quote_vol_24h > 0:
            quote_vol_24h = float(ticker_quote_vol_24h)
        else:
            quote_vol_24h = float(ind["QUOTE_VOLUME"].tail(candles_per_24h).sum())

        if quote_vol_24h < min_quote_vol_24h:
            return None

        bb_squeeze_val = (
            float(last["BB_SQUEEZE_RATIO"])
            if pd.notna(last["BB_SQUEEZE_RATIO"])
            else invalid_squeeze_fallback
        )
        vol_now = float(last["volume"])
        vol_sma_scanner = (
            float(last["VOL_SMA_SCANNER"]) if pd.notna(last["VOL_SMA_SCANNER"]) else 0.0
        )

        is_squeeze = bb_squeeze_val < squeeze_threshold
        is_spike = (
            vol_sma_scanner > 0
            and (vol_now > volume_spike_multiplier * vol_sma_scanner)
        )

        if is_squeeze and is_spike:
            spike_ratio = vol_now / vol_sma_scanner
            return {
                "symbol": symbol,
                "close": round(float(last["close"]), price_decimals),
                "quote_volume_24h": round(quote_vol_24h, volume_decimals),
                "bb_squeeze_ratio": round(bb_squeeze_val, squeeze_decimals),
                "volume_spike_ratio": round(spike_ratio, ratio_decimals),
                "rsi": round(float(last["RSI"]), indicator_decimals),
            }
        return None

    def scan_market(
        self,
        symbols: List[str],
        timeframe: Optional[str] = None,
        top_n: Optional[int] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Memindai daftar simbol dan mengembalikan kandidat yang memenuhi
        Squeeze + Spike, diurutkan berdasarkan rasio volume spike tertinggi.
        """
        cfg = config if config is not None else self.config
        scanner_cfg = cfg["scanner"]

        if timeframe is None:
            timeframe = str(scanner_cfg["timeframe"])
        if top_n is None:
            top_n = int(scanner_cfg["top_n"])

        default_candles_24h = int(scanner_cfg["default_candles_per_24h"])
        tf_map = {
            str(tf).lower(): int(candles)
            for tf, candles in scanner_cfg["candles_per_24h"].items()
        }
        candles_24h = tf_map.get(timeframe.lower(), default_candles_24h)

        fetch_limit_min = int(scanner_cfg["fetch_limit_min"])
        fetch_limit_buffer = int(scanner_cfg["fetch_limit_buffer"])
        top_n_min = int(scanner_cfg["top_n_min"])
        top_n_max = int(scanner_cfg["top_n_max"])

        tickers = {}
        try:
            tickers = self.api.fetch_tickers(symbols)
        except Exception:
            tickers = {}

        matches: List[Dict[str, Any]] = []
        for sym in symbols:
            threshold = self.get_liquidity_threshold(sym, config=cfg)
            ticker_qv = None
            if sym in tickers and tickers[sym].get("quoteVolume") is not None:
                ticker_qv = float(tickers[sym]["quoteVolume"])
                if ticker_qv < threshold:
                    continue  # Pre-filter likuiditas instan tanpa perlu tarik OHLCV

            try:
                df = self.api.fetch_ohlcv_df(
                    sym,
                    timeframe=timeframe,
                    limit=max(fetch_limit_min, candles_24h + fetch_limit_buffer),
                )
                res = self.evaluate_symbol_df(
                    symbol=sym,
                    df=df,
                    min_quote_vol_24h=threshold,
                    candles_per_24h=candles_24h,
                    ticker_quote_vol_24h=ticker_qv,
                    config=cfg,
                )
                if res is not None:
                    matches.append(res)
            except Exception:
                continue

        # Urutkan berdasarkan rasio Volume Spike tertinggi
        matches.sort(key=lambda x: x["volume_spike_ratio"], reverse=True)
        return matches[: max(top_n_min, min(top_n, top_n_max))]
