from typing import Any, Dict, List, Optional

import ccxt
import pandas as pd

from core.config import get_config


class ExchangeAPI:
    """
    ccxt wrapper untuk menarik data OHLCV multi-timeframe.

    Pengaturan exchange (default exchange, rate limit, market type, API key,
    limit candle, dan pair BTC cadangan) dibaca dari ``config.yaml``.
    """

    def __init__(
        self,
        exchange_id: Optional[str] = None,
        api_key: Optional[str] = None,
        secret: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        self.config = config if config is not None else get_config()
        self.exchange_cfg = self.config["exchange"]

        self.exchange_id = (exchange_id or self.exchange_cfg["default"]).lower()
        if not hasattr(ccxt, self.exchange_id):
            raise ValueError(f"Exchange '{exchange_id}' tidak didukung oleh ccxt.")

        resolved_api_key = (
            api_key if api_key is not None else str(self.exchange_cfg.get("api_key", ""))
        )
        resolved_secret = (
            secret if secret is not None else str(self.exchange_cfg.get("api_secret", ""))
        )

        exchange_class = getattr(ccxt, self.exchange_id)
        exchange_options = {
            "enableRateLimit": bool(self.exchange_cfg["enable_rate_limit"]),
            "options": {"defaultType": str(self.exchange_cfg["market_type"])},
        }
        if resolved_api_key and resolved_secret:
            exchange_options["apiKey"] = resolved_api_key
            exchange_options["secret"] = resolved_secret

        self.exchange: ccxt.Exchange = exchange_class(exchange_options)

    def fetch_ohlcv_df(
        self,
        symbol: str,
        timeframe: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> pd.DataFrame:
        """
        Menarik data OHLCV dari exchange dan mengonversinya menjadi pandas DataFrame.
        """
        if timeframe is None:
            timeframe = str(self.exchange_cfg["default_timeframe"])
        if limit is None:
            limit = int(self.exchange_cfg["ohlcv_limit"])

        min_ohlcv_limit = int(self.exchange_cfg["min_ohlcv_limit"])
        if limit < min_ohlcv_limit:
            # Minimal candle agar rolling window dan EMA long-period terhitung valid
            limit = int(self.exchange_cfg["min_ohlcv_limit_fallback"])

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
        macro_tf: Optional[str] = None,
        micro_tf: Optional[str] = None,
        limit: Optional[int] = None,
        include_btc_macro: Optional[bool] = None,
    ) -> Dict[str, Optional[pd.DataFrame]]:
        """
        Menarik data Macro, Micro, dan opsional data aset acuan untuk King's Filter.
        """
        analyze_cfg = self.config["analyze"]
        reference_asset = str(self.config["logic"]["kings_filter"]["reference_asset"]).upper()
        default_quote_currency = str(self.exchange_cfg["default_quote_currency"]).upper()
        if macro_tf is None:
            macro_tf = str(analyze_cfg["macro_timeframe"])
        if micro_tf is None:
            micro_tf = str(analyze_cfg["micro_timeframe"])
        if limit is None:
            limit = int(self.exchange_cfg["ohlcv_limit"])
        if include_btc_macro is None:
            include_btc_macro = bool(analyze_cfg["include_btc_macro"])

        macro_df = self.fetch_ohlcv_df(symbol, timeframe=macro_tf, limit=limit)
        micro_df = self.fetch_ohlcv_df(symbol, timeframe=micro_tf, limit=limit)

        btc_df = None
        base_coin = symbol.split("/")[0].upper() if "/" in symbol else symbol.upper()
        if include_btc_macro and base_coin != reference_asset:
            quote_coin = (
                symbol.split("/")[1].upper() if "/" in symbol else default_quote_currency
            )
            btc_symbol = f"{reference_asset}/{quote_coin}"
            fallback_symbol = str(self.exchange_cfg["btc_fallback_symbol"])
            try:
                btc_df = self.fetch_ohlcv_df(btc_symbol, timeframe=macro_tf, limit=limit)
            except Exception:
                # Fallback ke pair acuan cadangan jika pair quote lokal tidak tersedia
                try:
                    btc_df = self.fetch_ohlcv_df(
                        fallback_symbol, timeframe=macro_tf, limit=limit
                    )
                except Exception:
                    btc_df = None

        return {
            "macro": macro_df,
            "micro": micro_df,
            "btc_macro": btc_df,
        }

    def load_markets(self, reload: bool = False) -> Dict[str, Any]:
        """
        Memuat metadata seluruh market exchange (spot/future, quote, status aktif).
        Hasilnya di-cache oleh ccxt sehingga pemanggilan berikutnya murah.
        """
        return self.exchange.load_markets(reload)

    def fetch_tickers(self, symbols: Optional[List[str]] = None) -> Dict:
        """
        Menarik informasi ticker 24 jam (termasuk quoteVolume) untuk efisiensi pre-filter scanner.
        """
        if self.exchange.has.get("fetchTickers"):
            return self.exchange.fetch_tickers(symbols)
        return {}

    def fetch_all_tickers(self) -> Dict:
        """
        Menarik ticker seluruh market dalam satu request untuk dynamic universe.

        Berbeda dari ``fetch_tickers``, method ini melempar error bila exchange
        tidak mendukung daftar ticker sekaligus, agar scanner bisa memutuskan
        fallback ke watchlist secara eksplisit.
        """
        if not self.exchange.has.get("fetchTickers"):
            raise ValueError(
                f"Exchange '{self.exchange_id}' tidak mendukung fetchTickers sekaligus."
            )
        return self.exchange.fetch_tickers()
