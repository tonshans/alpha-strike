import copy
import unittest

from core.universe import select_dynamic_symbols


BASE_CONFIG = {
    "exchange": {"default_quote_currency": "USDT"},
    "scanner": {
        "universe": {
            "quote_currencies": {
                "binance": ["USDT"],
                "indodax": ["IDR"],
            },
            "default_quote_currencies": ["USDT"],
            "max_pairs": {"binance": 40, "indodax": 25, "default": 30},
            "min_quote_volume_24h": {
                "USDT": 10_000_000,
                "IDR": 500_000_000,
                "default": 5_000_000,
            },
            "max_spread_pct": {"USDT": 0.5, "IDR": 2.0, "default": 1.0},
            "exclude_bases": ["USDT", "USDC", "EUR"],
            "exclude_symbol_patterns": ["(3L|3S|5L|5S|BULL|BEAR)$"],
            "fallback_to_watchlist": True,
        }
    },
}


def market(symbol, base, quote="USDT", active=True, spot=True):
    return {
        "symbol": symbol,
        "base": base,
        "quote": quote,
        "active": active,
        "spot": spot,
        "type": "spot",
    }


def ticker(quote_volume, last=1.0, bid=None, ask=None):
    bid = last if bid is None else bid
    ask = last if ask is None else ask
    return {
        "quoteVolume": quote_volume,
        "baseVolume": quote_volume / last if last else 0,
        "last": last,
        "bid": bid,
        "ask": ask,
        "high": last * 1.02,
        "low": last * 0.98,
    }


class DynamicUniverseTest(unittest.TestCase):
    def setUp(self):
        self.config = copy.deepcopy(BASE_CONFIG)

    def test_filters_quotes_blacklist_liquidity_and_spread(self):
        markets = {
            "BTC/USDT": market("BTC/USDT", "BTC"),
            "ETH/USDT": market("ETH/USDT", "ETH"),
            "USDT/USDT": market("USDT/USDT", "USDT"),
            "EUR/USDT": market("EUR/USDT", "EUR"),
            "BTC3L/USDT": market("BTC3L/USDT", "BTC3L"),
            "DEAD/USDT": market("DEAD/USDT", "DEAD"),
            "WIDE/USDT": market("WIDE/USDT", "WIDE"),
            "OLD/USDT": market("OLD/USDT", "OLD", active=False),
            "BTC/BTC": market("BTC/BTC", "BTC", quote="BTC"),
        }
        tickers = {
            "BTC/USDT": ticker(500_000_000, last=60_000),
            "ETH/USDT": ticker(100_000_000, last=3_000),
            "USDT/USDT": ticker(900_000_000),
            "EUR/USDT": ticker(900_000_000),
            "BTC3L/USDT": ticker(900_000_000),
            "DEAD/USDT": ticker(1_000),
            "WIDE/USDT": ticker(50_000_000, bid=0.9, ask=1.1),
            "OLD/USDT": ticker(900_000_000),
            "BTC/BTC": ticker(900_000_000),
        }

        result = select_dynamic_symbols(markets, tickers, "binance", self.config)

        self.assertEqual(result.symbols, ["BTC/USDT", "ETH/USDT"])
        self.assertEqual(result.stats["markets_total"], 9)
        self.assertEqual(result.stats["eligible_markets"], 4)
        self.assertEqual(result.stats["after_volume"], 3)
        self.assertEqual(result.stats["after_spread"], 2)
        self.assertEqual(result.stats["selected"], 2)

    def test_quote_specific_gate_for_indodax(self):
        markets = {
            "BTC/IDR": market("BTC/IDR", "BTC", quote="IDR"),
            "ETH/IDR": market("ETH/IDR", "ETH", quote="IDR"),
            "SOL/USDT": market("SOL/USDT", "SOL", quote="USDT"),
        }
        tickers = {
            "BTC/IDR": ticker(600_000_000),
            "ETH/IDR": ticker(100_000_000),
            "SOL/USDT": ticker(900_000_000),
        }

        result = select_dynamic_symbols(markets, tickers, "indodax", self.config)

        self.assertEqual(result.symbols, ["BTC/IDR"])
        self.assertEqual(result.stats["min_quote_volume_24h"], {"IDR": 500_000_000.0})

    def test_dedupes_base_and_caps_selected_pairs(self):
        self.config["scanner"]["universe"]["quote_currencies"]["binance"] = [
            "USDT",
            "USD",
        ]
        self.config["scanner"]["universe"]["min_quote_volume_24h"]["USD"] = 1
        markets = {
            "BTC/USDT": market("BTC/USDT", "BTC", quote="USDT"),
            "BTC/USD": market("BTC/USD", "BTC", quote="USD"),
            "ETH/USDT": market("ETH/USDT", "ETH"),
            "SOL/USDT": market("SOL/USDT", "SOL"),
        }
        tickers = {
            "BTC/USDT": ticker(500_000_000),
            "BTC/USD": ticker(400_000_000),
            "ETH/USDT": ticker(300_000_000),
            "SOL/USDT": ticker(200_000_000),
        }
        self.config["scanner"]["universe"]["max_pairs"]["binance"] = 2

        result = select_dynamic_symbols(markets, tickers, "binance", self.config)

        self.assertEqual(result.symbols, ["BTC/USDT", "ETH/USDT"])
        self.assertEqual(result.stats["after_dedupe"], 3)
        self.assertEqual(result.stats["selected"], 2)

    def test_jup_is_not_treated_as_leveraged_token(self):
        markets = {"JUP/USDT": market("JUP/USDT", "JUP")}
        tickers = {"JUP/USDT": ticker(50_000_000)}

        result = select_dynamic_symbols(markets, tickers, "binance", self.config)

        self.assertEqual(result.symbols, ["JUP/USDT"])


if __name__ == "__main__":
    unittest.main()
