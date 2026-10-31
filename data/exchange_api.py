from typing import Dict, List, Optional
import ccxt
import pandas as pd


class ExchangeAPI:
    """
    ccxt wrapper untuk menarik data OHLCV multi-timeframe dengan enableRateLimit=True
    sesuai spesifikasi ARCHITECTURE.md.
    """

    def __init__(self, exchange_id: str = "binance", api_key: str = "", secret: str = ""):
        self.exchange_id = exchange_id.lower()
        if not hasattr(ccxt, self.exchange_id):
            raise ValueError(f"Exchange '{exchange_id}' tidak didukung oleh ccxt.")

        exchange_class = getattr(ccxt, self.exchange_id)
        config = {
            "enableRateLimit": True,
            "options": {"defaultType": "spot"},
        }
        if api_key and secret:
            config["apiKey"] = api_key
            config["secret"] = secret

        self.exchange: ccxt.Exchange = exchange_class(config)

    def fetch_ohlcv_df(self, symbol: str, timeframe: str = "15m", limit: int = 150) -> pd.DataFrame:
        """
        Menarik data OHLCV dari exchange dan mengonversinya menjadi pandas DataFrame.
        """
        if limit < 60:
            limit = 100  # Minimal 60+ candle agar rolling(50) dan EMA(50) terhitung valid

        raw_ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        if not raw_ohlcv:
            raise ValueError(f"Data OHLCV kosong untuk {symbol} ({timeframe}).")

        df = pd.DataFrame(
            raw_ohlcv,
            columns=["timestamp", "open", "high", "low", "close", "volume"],
        )
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        numeric_cols = ["open", "high", "low", "close", "volume"]
        df[numeric_cols] = df[numeric_cols].astype(float)
        return df

    def fetch_mtfa_data(
        self,
        symbol: str,
        macro_tf: str = "4h",
        micro_tf: str = "15m",
        limit: int = 150,
        include_btc_macro: bool = True,
    ) -> Dict[str, Optional[pd.DataFrame]]:
        """
        Menarik data Macro, Micro, dan opsional BTC Macro untuk King's Filter.
        """
        macro_df = self.fetch_ohlcv_df(symbol, timeframe=macro_tf, limit=limit)
        micro_df = self.fetch_ohlcv_df(symbol, timeframe=micro_tf, limit=limit)

        btc_df = None
        base_coin = symbol.split("/")[0].upper() if "/" in symbol else symbol.upper()
        if include_btc_macro and base_coin != "BTC":
            quote_coin = symbol.split("/")[1].upper() if "/" in symbol else "USDT"
            btc_symbol = f"BTC/{quote_coin}"
            try:
                btc_df = self.fetch_ohlcv_df(btc_symbol, timeframe=macro_tf, limit=limit)
            except Exception:
                # Fallback ke BTC/USDT jika pair quote lokal tidak tersedia
                try:
                    btc_df = self.fetch_ohlcv_df("BTC/USDT", timeframe=macro_tf, limit=limit)
                except Exception:
                    btc_df = None

        return {
            "macro": macro_df,
            "micro": micro_df,
            "btc_macro": btc_df,
        }

    def fetch_tickers(self, symbols: Optional[List[str]] = None) -> Dict:
        """
        Menarik informasi ticker 24 jam (termasuk quoteVolume) untuk efisiensi pre-filter scanner.
        """
        if self.exchange.has.get("fetchTickers"):
            return self.exchange.fetch_tickers(symbols)
        return {}
