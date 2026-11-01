from typing import Any, Dict, List, Optional

import pandas as pd

from core.config import get_config
from core.indicators import compute_indicators
from core.universe import build_dynamic_universe
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
        # Statistik funnel scan terakhir, dipakai formatter/CLI untuk observability.
        self.last_scan_stats: Dict[str, Any] = {}

    def get_liquidity_threshold(
        self,
        symbol: str,
        config: Optional[Dict[str, Any]] = None,
    ) -> float:
        """
        Mengembalikan ambang quote volume 24 jam sesuai quote pair.

        Quote harus dicek lebih dulu daripada nama exchange. Contoh: pair
        ``BTC/USDT`` di Indodax memakai ambang USD, bukan ambang Rupiah.
        """
        cfg = config if config is not None else self.config
        thresholds = cfg["scanner"]["liquidity_threshold"]
        default = float(thresholds["default"])

        quote = (
            symbol.rsplit("/", 1)[-1].split(":", 1)[0].upper()
            if "/" in symbol
            else ""
        )
        if quote == "IDR":
            return float(thresholds.get("idr_quote", thresholds.get("indodax", default)))

        usd_quotes = {"USDT", "USDC", "FDUSD", "BUSD", "TUSD", "DAI", "USDP", "USD"}
        if quote in usd_quotes:
            if self.api.exchange_id == "binance":
                return float(thresholds.get("binance", thresholds.get("usd_quote", default)))
            return float(thresholds.get("usd_quote", default))

        if self.api.exchange_id == "indodax":
            return float(thresholds.get("indodax", default))
        return float(thresholds.get(self.api.exchange_id, default))

    def get_watchlist_symbols(
        self,
        config: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        """Ambil watchlist untuk exchange aktif, dengan fallback ke ``symbols``."""
        cfg = config if config is not None else self.config
        scanner_cfg = cfg["scanner"]

        by_exchange = scanner_cfg.get("watchlist_by_exchange") or {}
        if isinstance(by_exchange, dict):
            normalized = {
                str(key).strip().lower(): value for key, value in by_exchange.items()
            }
            symbols = normalized.get(self.api.exchange_id)
            if symbols is not None:
                return self._clean_symbols(symbols)

        return self._clean_symbols(scanner_cfg.get("symbols", []))

    @staticmethod
    def _clean_symbols(symbols: Any) -> List[str]:
        if isinstance(symbols, str):
            symbols = [symbols]
        if not isinstance(symbols, (list, tuple, set)):
            return []
        return [str(symbol).strip() for symbol in symbols if str(symbol).strip()]

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
        symbols: Optional[List[str]] = None,
        timeframe: Optional[str] = None,
        top_n: Optional[int] = None,
        scan_all: bool = False,
        config: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Memindai pair dan mengembalikan kandidat Squeeze + Spike.

        Mode pemilihan pair:
        - ``symbols`` diisi: scan daftar eksplisit tersebut.
        - ``scan_all=True``: bangun universe dynamic dari seluruh market exchange.
        - default: scan watchlist exchange (``watchlist_by_exchange``/``symbols``).
        """
        cfg = config if config is not None else self.config
        scanner_cfg = cfg["scanner"]
        self.last_scan_stats = {}

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

        universe_cfg = scanner_cfg.get("universe", {}) or {}
        fallback_enabled = bool(universe_cfg.get("fallback_to_watchlist", True))

        selected_symbols: List[str] = []
        selected_tickers: Optional[Dict[str, Any]] = None
        universe_stats: Dict[str, Any] = {}
        scope = "watchlist"

        if symbols:
            selected_symbols = self._clean_symbols(symbols)
            scope = "explicit"
        elif scan_all:
            scope = "dynamic"
            try:
                universe = build_dynamic_universe(self.api, cfg)
                selected_symbols = universe.symbols
                selected_tickers = universe.tickers
                universe_stats = dict(universe.stats)
            except Exception as exc:
                universe_stats = {
                    "scope": "dynamic",
                    "error": str(exc),
                    "fallback_to_watchlist": fallback_enabled,
                }
                if not fallback_enabled:
                    raise

            if not selected_symbols and fallback_enabled:
                selected_symbols = self.get_watchlist_symbols(cfg)
                selected_tickers = None
                scope = "watchlist-fallback"
                universe_stats["fallback_to_watchlist"] = True
                if not universe_stats.get("fallback_reason"):
                    universe_stats["fallback_reason"] = (
                        "dynamic_universe_failed"
                        if universe_stats.get("error")
                        else "dynamic_universe_empty"
                    )
        else:
            selected_symbols = self.get_watchlist_symbols(cfg)
            scope = "watchlist"

        if selected_tickers is None:
            if selected_symbols:
                try:
                    selected_tickers = self.api.fetch_tickers(selected_symbols)
                except Exception:
                    selected_tickers = {}
            else:
                selected_tickers = {}
        if not isinstance(selected_tickers, dict):
            selected_tickers = {}

        stats: Dict[str, Any] = dict(universe_stats)
        stats.update(
            {
                "scope": scope,
                "exchange": self.api.exchange_id,
                "requested_symbols": len(selected_symbols),
                "ohlcv_ok": 0,
                "ohlcv_error": 0,
                "liquidity_prefiltered": 0,
                "matches": 0,
                "returned": 0,
            }
        )

        # Pada mode dynamic, gate universe menjadi ambang final agar pair yang
        # lolos seleksi tidak dibuang lagi oleh ambang watchlist yang berbeda.
        dynamic_gates: Dict[str, float] = {}
        if scope == "dynamic":
            raw_gates = universe_stats.get("min_quote_volume_24h")
            if isinstance(raw_gates, dict):
                for key, value in raw_gates.items():
                    try:
                        dynamic_gates[str(key).upper()] = float(value)
                    except (TypeError, ValueError):
                        continue

        matches: List[Dict[str, Any]] = []
        for sym in selected_symbols:
            threshold = self.get_liquidity_threshold(sym, config=cfg)
            quote = (
                sym.rsplit("/", 1)[-1].split(":", 1)[0].upper()
                if "/" in sym
                else ""
            )
            if quote in dynamic_gates:
                threshold = dynamic_gates[quote]
            ticker_qv = None
            ticker = selected_tickers.get(sym)
            if isinstance(ticker, dict) and ticker.get("quoteVolume") is not None:
                try:
                    ticker_qv = float(ticker["quoteVolume"])
                except (TypeError, ValueError):
                    ticker_qv = None
                if ticker_qv is not None and ticker_qv < threshold:
                    stats["liquidity_prefiltered"] += 1
                    continue  # Pre-filter likuiditas tanpa tarik OHLCV

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
                stats["ohlcv_ok"] += 1
                if res is not None:
                    matches.append(res)
            except Exception:
                stats["ohlcv_error"] += 1
                continue

        # Urutkan berdasarkan rasio Volume Spike tertinggi
        matches.sort(key=lambda x: x["volume_spike_ratio"], reverse=True)
        limit = max(top_n_min, min(top_n, top_n_max))
        results = matches[:limit]

        stats["matches"] = len(matches)
        stats["returned"] = len(results)
        self.last_scan_stats = stats
        return results
