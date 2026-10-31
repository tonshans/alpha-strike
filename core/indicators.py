import numpy as np
import pandas as pd
import pandas_ta as ta


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Menghitung seluruh indikator baku secara vectorized (tanpa iterasi baris)
    sesuai ARCHITECTURE.md & PRD.md Bagian 2.A:
      - EMA Fast (21), EMA Slow (50), EMA (20) untuk BB Squeeze
      - RSI (14)
      - SMA Volume (20) untuk sinyal, SMA Volume (24) untuk scanner
      - ATR (14), ADX (14), Bollinger Bands (20, 2)
      - S&R Dinamis: Support = Low.rolling(50).min(), Resistance = High.rolling(50).max()
    """
    if df is None or df.empty:
        raise ValueError("DataFrame kosong tidak dapat dihitung indikatornya.")

    out = df.copy()

    # 1. Trend: EMA 20, 21, 50
    out["EMA_20"] = ta.ema(out["close"], length=20)
    out["EMA_21"] = ta.ema(out["close"], length=21)
    out["EMA_50"] = ta.ema(out["close"], length=50)

    # 2. Momentum: RSI (14)
    out["RSI_14"] = ta.rsi(out["close"], length=14)

    # 3. Volume: SMA Volume (20) & SMA Volume (24)
    out["VOL_SMA_20"] = ta.sma(out["volume"], length=20)
    out["VOL_SMA_24"] = ta.sma(out["volume"], length=24)

    # 4. Volatilitas & Filter: ATR (14), ADX (14), Bollinger Bands (20, 2)
    atr_series = ta.atr(out["high"], out["low"], out["close"], length=14)
    out["ATR_14"] = atr_series

    adx_df = ta.adx(out["high"], out["low"], out["close"], length=14)
    if adx_df is not None and not adx_df.empty:
        adx_cols = [c for c in adx_df.columns if c.startswith("ADX_")]
        out["ADX_14"] = adx_df[adx_cols[0]] if adx_cols else np.nan
    else:
        out["ADX_14"] = np.nan

    bb_df = ta.bbands(out["close"], length=20, std=2)
    if bb_df is not None and not bb_df.empty:
        bbl_cols = [c for c in bb_df.columns if c.startswith("BBL_")]
        bbu_cols = [c for c in bb_df.columns if c.startswith("BBU_")]
        out["BB_LOWER"] = bb_df[bbl_cols[0]] if bbl_cols else np.nan
        out["BB_UPPER"] = bb_df[bbu_cols[0]] if bbu_cols else np.nan
    else:
        out["BB_LOWER"] = np.nan
        out["BB_UPPER"] = np.nan

    # 5. S&R Dinamis (Rolling 50)
    out["SUPPORT"] = out["low"].rolling(window=50, min_periods=1).min()
    out["RESISTANCE"] = out["high"].rolling(window=50, min_periods=1).max()

    # 6. Turunan Vectorized untuk Scanner & Smart Money
    out["BB_SQUEEZE_RATIO"] = (out["BB_UPPER"] - out["BB_LOWER"]) / out["EMA_20"]
    out["QUOTE_VOLUME"] = out["volume"] * out["close"]

    return out
