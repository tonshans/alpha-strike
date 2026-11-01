import copy
import unittest
from unittest.mock import patch

from core.scanner import MarketScanner
from core.universe import UniverseResult

BASE_CONFIG = {
    "exchange": {"default_quote_currency": "USDT"},
    "scanner": {
        "timeframe": "4h",
        "top_n": 5,
        "top_n_min": 3,
        "top_n_max": 5,
        "default_candles_per_24h": 24,
        "candles_per_24h": {"4h": 6},
        "fetch_limit_min": 60,
        "fetch_limit_buffer": 30,
        "symbols": ["FALLBACK/USDT"],
        "watchlist_by_exchange": {"binance": ["BTC/USDT", "ETH/USDT"]},
        "liquidity_threshold": {
            "binance": 1_000_000,
            "indodax": 1_000_000_000,
            "idr_quote": 1_000_000_000,
            "usd_quote": 1_000_000,
            "default": 1_000_000,
        },
        "universe": {
            "fallback_to_watchlist": True,
            "min_quote_volume_24h": {"USDT": 10_000_000},
        },
    },
}


class FakeAPI:
    exchange_id = "binance"

    def __init__(self):
        self.ohlcv_symbols = []
        self.ticker_calls = []

    def fetch_tickers(self, symbols=None):
        self.ticker_calls.append(list(symbols or []))
        return {
            symbol: {"quoteVolume": 1_000_000_000.0}
            for symbol in (symbols or [])
        }

    def fetch_ohlcv_df(self, symbol, timeframe=None, limit=None):
        self.ohlcv_symbols.append(symbol)
        return object()


class ScannerModeTest(unittest.TestCase):
    def setUp(self):
        self.config = copy.deepcopy(BASE_CONFIG)
        self.api = FakeAPI()
        self.scanner = MarketScanner(self.api, self.config)

    @patch.object(MarketScanner, "evaluate_symbol_df", return_value=None)
    def test_default_is_watchlist(self, _evaluate):
        self.scanner.scan_market()

        self.assertEqual(self.api.ohlcv_symbols, ["BTC/USDT", "ETH/USDT"])
        self.assertEqual(self.scanner.last_scan_stats["scope"], "watchlist")

    @patch.object(MarketScanner, "evaluate_symbol_df", return_value=None)
    def test_explicit_symbols_override_watchlist(self, _evaluate):
        self.scanner.scan_market(symbols=["SOL/USDT"])

        self.assertEqual(self.api.ohlcv_symbols, ["SOL/USDT"])
        self.assertEqual(self.scanner.last_scan_stats["scope"], "explicit")

    @patch("core.scanner.build_dynamic_universe")
    @patch.object(MarketScanner, "evaluate_symbol_df", return_value=None)
    def test_all_uses_dynamic_universe(self, _evaluate, build_universe):
        build_universe.return_value = UniverseResult(
            symbols=["DYN/USDT"],
            tickers={"DYN/USDT": {"quoteVolume": 50_000_000.0}},
            stats={
                "scope": "dynamic",
                "selected": 1,
                "min_quote_volume_24h": {"USDT": 10_000_000.0},
            },
        )

        self.scanner.scan_market(scan_all=True)

        self.assertEqual(self.api.ohlcv_symbols, ["DYN/USDT"])
        self.assertEqual(self.scanner.last_scan_stats["scope"], "dynamic")
        build_universe.assert_called_once()

    @patch("core.scanner.build_dynamic_universe")
    @patch.object(MarketScanner, "evaluate_symbol_df", return_value=None)
    def test_empty_dynamic_universe_falls_back_to_watchlist(self, _evaluate, build_universe):
        build_universe.return_value = UniverseResult(
            symbols=[],
            tickers={},
            stats={"scope": "dynamic", "selected": 0},
        )

        self.scanner.scan_market(scan_all=True)

        self.assertEqual(self.api.ohlcv_symbols, ["BTC/USDT", "ETH/USDT"])
        self.assertEqual(
            self.scanner.last_scan_stats["scope"],
            "watchlist-fallback",
        )
        self.assertEqual(
            self.scanner.last_scan_stats["fallback_reason"],
            "dynamic_universe_empty",
        )

    @patch("core.scanner.build_dynamic_universe", side_effect=RuntimeError("boom"))
    @patch.object(MarketScanner, "evaluate_symbol_df", return_value=None)
    def test_dynamic_failure_falls_back_to_watchlist(self, _evaluate, _build_universe):
        self.scanner.scan_market(scan_all=True)

        self.assertEqual(self.api.ohlcv_symbols, ["BTC/USDT", "ETH/USDT"])
        self.assertEqual(
            self.scanner.last_scan_stats["scope"],
            "watchlist-fallback",
        )
        self.assertEqual(
            self.scanner.last_scan_stats["fallback_reason"],
            "dynamic_universe_failed",
        )


if __name__ == "__main__":
    unittest.main()
