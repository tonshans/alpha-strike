from typing import Any, Dict, Optional

import numpy as np
import pandas as pd
import pandas_ta as ta

from core.config import get_config


def compute_indicators(
    df: pd.DataFrame,
    config: Optional[Dict[str, Any]] = None,
) -> pd.DataFrame:
    """
    Menghitung seluruh indikator baku secara vectorized (tanpa iterasi baris)
    sesuai ARCHITECTURE.md & PRD.md Bagian 2.A.

    Seluruh periode indikator (EMA, RSI, volume SMA, ATR, ADX, Bollinger Bands,
    dan lookback support/resistance) dibaca dari ``config.yaml`` agar pengguna
    dapat mengubahnya tanpa menyentuh kode.
    """
    if df is None or df.empty:
        raise ValueError("DataFrame kosong tidak dapat dihitung indikatornya.")

    cfg = config if config is not None else get_config()
    ind_cfg = cfg["indicators"]

    out = df.copy()

    # 1. Trend: EMA fast, slow, dan middle (untuk BB Squeeze)
    ema_cfg = ind_cfg["ema"]
    ema_fast_length = int(ema_cfg["fast"])
    ema_slow_length = int(ema_cfg["slow"])
    ema_mid_length = int(ema_cfg["mid"])

    out["EMA_FAST"] = ta.ema(out["close"], length=ema_fast_length)
    out["EMA_SLOW"] = ta.ema(out["close"], length=ema_slow_length)
    out["EMA_MID"] = ta.ema(out["close"], length=ema_mid_length)

    # 2. Momentum: RSI
    rsi_length = int(ind_cfg["rsi_length"])
    out["RSI"] = ta.rsi(out["close"], length=rsi_length)

    # 3. Volume: SMA volume untuk sinyal dan scanner
    volume_cfg = ind_cfg["volume_sma"]
    volume_signal_length = int(volume_cfg["signal"])
    volume_scanner_length = int(volume_cfg["scanner"])

    out["VOL_SMA_SIGNAL"] = ta.sma(out["volume"], length=volume_signal_length)
    out["VOL_SMA_SCANNER"] = ta.sma(out["volume"], length=volume_scanner_length)

    # 4. Volatilitas & filter: ATR, ADX, Bollinger Bands
    atr_length = int(ind_cfg["atr_length"])
    out["ATR"] = ta.atr(out["high"], out["low"], out["close"], length=atr_length)

    adx_length = int(ind_cfg["adx_length"])
    adx_df = ta.adx(out["high"], out["low"], out["close"], length=adx_length)
    if adx_df is not None and not adx_df.empty:
        adx_cols = [c for c in adx_df.columns if c.startswith("ADX_")]
        out["ADX"] = adx_df[adx_cols[0]] if adx_cols else np.nan
    else:
        out["ADX"] = np.nan

    bollinger_cfg = ind_cfg["bollinger"]
    bb_length = int(bollinger_cfg["length"])
    bb_std = float(bollinger_cfg["std"])
    bb_df = ta.bbands(out["close"], length=bb_length, std=bb_std)
    if bb_df is not None and not bb_df.empty:
        bbl_cols = [c for c in bb_df.columns if c.startswith("BBL_")]
        bbu_cols = [c for c in bb_df.columns if c.startswith("BBU_")]
        out["BB_LOWER"] = bb_df[bbl_cols[0]] if bbl_cols else np.nan
        out["BB_UPPER"] = bb_df[bbu_cols[0]] if bbu_cols else np.nan
    else:
        out["BB_LOWER"] = np.nan
        out["BB_UPPER"] = np.nan

    # 5. Support & Resistance dinamis
    sr_cfg = ind_cfg["support_resistance"]
    sr_lookback = int(sr_cfg["lookback"])
    sr_min_periods = int(sr_cfg["min_periods"])

    out["SUPPORT"] = out["low"].rolling(window=sr_lookback, min_periods=sr_min_periods).min()
    out["RESISTANCE"] = out["high"].rolling(window=sr_lookback, min_periods=sr_min_periods).max()

    # 6. Turunan vectorized untuk scanner & Smart Money
    out["BB_SQUEEZE_RATIO"] = (out["BB_UPPER"] - out["BB_LOWER"]) / out["EMA_MID"]
    out["QUOTE_VOLUME"] = out["volume"] * out["close"]

    return out
