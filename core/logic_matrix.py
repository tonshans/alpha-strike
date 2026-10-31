from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from core.config import get_config
from core.indicators import compute_indicators


def compute_macro_score_series(
    df_macro: pd.DataFrame,
    config: Optional[Dict[str, Any]] = None,
) -> pd.Series:
    """
    Vectorized Macro Score:
      +1 (Bullish) : Close_Macro > EMA slow
      -1 (Bearish) : Close_Macro < EMA slow
       0 (Neutral) : Close_Macro == EMA slow

    Periode EMA slow dibaca dari ``config.yaml`` (``indicators.ema.slow``).
    """
    slow_ema_col = "EMA_SLOW"

    conditions = [
        df_macro["close"] > df_macro[slow_ema_col],
        df_macro["close"] < df_macro[slow_ema_col],
    ]
    choices = [1, -1]
    return pd.Series(np.select(conditions, choices, default=0), index=df_macro.index)


def compute_micro_score_series(
    df_micro: pd.DataFrame,
    config: Optional[Dict[str, Any]] = None,
) -> pd.Series:
    """
    Vectorized Micro Score sesuai PRD Bagian 2.C. Semua ambang batas dibaca
    dari ``config.yaml`` pada bagian ``logic.micro_score``.
    """
    cfg = config if config is not None else get_config()
    micro_cfg = cfg["logic"]["micro_score"]

    volume_surge_multiplier = float(micro_cfg["volume_surge_multiplier"])
    bull_rsi_min = float(micro_cfg["bull_rsi_min"])
    bull_rsi_max = float(micro_cfg["bull_rsi_max"])
    overbought_rsi = float(micro_cfg["overbought_rsi"])
    bear_rsi_max = float(micro_cfg["bear_rsi_max"])
    rejection_ratio = float(micro_cfg["rejection_wick_body_ratio"])

    vol_surge = df_micro["volume"] > (volume_surge_multiplier * df_micro["VOL_SMA_SIGNAL"])

    bull_cond = (
        (df_micro["close"] > df_micro["EMA_FAST"])
        & vol_surge
        & (df_micro["RSI"] >= bull_rsi_min)
        & (df_micro["RSI"] <= bull_rsi_max)
    )

    # Rejection saat RSI overbought: upper wick signifikan atau candle bearish
    upper_wick = df_micro["high"] - np.maximum(df_micro["open"], df_micro["close"])
    candle_body = (df_micro["close"] - df_micro["open"]).abs()
    rsi_overbought_rejection = (df_micro["RSI"] > overbought_rsi) & (
        (upper_wick > (rejection_ratio * candle_body))
        | (df_micro["close"] < df_micro["open"])
    )

    bear_cond = (
        (df_micro["close"] < df_micro["EMA_FAST"])
        & vol_surge
        & ((df_micro["RSI"] < bear_rsi_max) | rsi_overbought_rejection)
    )

    conditions = [bull_cond, bear_cond]
    choices = [1, -1]
    return pd.Series(np.select(conditions, choices, default=0), index=df_micro.index)


def evaluate_mtfa_and_risk(
    symbol: str,
    df_macro: pd.DataFrame,
    df_micro: pd.DataFrame,
    df_btc_macro: Optional[pd.DataFrame] = None,
    execution_mode: Optional[str] = None,
    current_highest_high: Optional[float] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Mengeksekusi algoritma keputusan penuh sesuai PRD Bagian 2.B, 2.C, dan 2.D.

    Semua ambang filter dan formula risiko dibaca dari ``config.yaml`` agar
    pengguna dapat mengubah perilaku engine tanpa mengedit kode.
    """
    cfg = config if config is not None else get_config()
    ind_cfg = cfg["indicators"]
    output_cfg = cfg["output"]
    filters_cfg = cfg["logic"]["filters"]
    smart_money_cfg = cfg["logic"]["smart_money"]
    kings_filter_cfg = cfg["logic"]["kings_filter"]
    risk_cfg = cfg["logic"]["risk"]

    macro = compute_indicators(df_macro, config=cfg)
    micro = compute_indicators(df_micro, config=cfg)

    macro["MACRO_SCORE"] = compute_macro_score_series(macro, config=cfg)
    micro["MICRO_SCORE"] = compute_micro_score_series(micro, config=cfg)

    last_macro = macro.iloc[-1]
    last_micro = micro.iloc[-1]

    macro_score = int(last_macro["MACRO_SCORE"])
    micro_score = int(last_micro["MICRO_SCORE"])

    # Matriks Keputusan Awal (PRD 2.C)
    if macro_score == 1 and micro_score == 1:
        raw_signal = "🟢 STRONG BUY"
        direction = 1
    elif macro_score == -1 and micro_score == -1:
        raw_signal = "🔴 STRONG SELL"
        direction = -1
    elif macro_score == 1 and micro_score == -1:
        raw_signal = "⚪ PULLBACK / HOLD"
        direction = 0
    elif macro_score == -1 and micro_score == 1:
        raw_signal = "⚪ DEAD CAT BOUNCE / HOLD"
        direction = 0
    else:
        raw_signal = "⚪ HOLD (Neutral Micro/Macro)"
        direction = 0

    final_signal = raw_signal
    filter_reasons = []

    # =========================================================================
    # 3 LAPIS FILTER MAKRO & REZIM PASAR (PRD Bagian 2.B)
    # =========================================================================
    adx_min = float(filters_cfg["adx_min"])
    ranging_threshold_pct = float(filters_cfg["ranging_threshold_pct"])

    price_decimals = int(output_cfg["price_decimals"])
    indicator_decimals = int(output_cfg["indicator_decimals"])
    volume_decimals = int(output_cfg["volume_decimals"])
    percent_decimals = int(output_cfg["percent_decimals"])
    ratio_decimals = int(output_cfg["ratio_decimals"])

    adx_val = float(last_micro["ADX"]) if pd.notna(last_micro["ADX"]) else 0.0
    close_price = float(last_micro["close"])
    ema_fast = float(last_micro["EMA_FAST"])
    ema_slow = float(last_micro["EMA_SLOW"])
    ema_gap = abs(ema_fast - ema_slow)
    ranging_threshold = (ranging_threshold_pct / 100.0) * close_price

    # 1. Market Regime (ADX Filter)
    if adx_val < adx_min:
        final_signal = f"⚪ HOLD (Choppy Market: ADX < {adx_min:g})"
        filter_reasons.append(f"ADX({adx_val:.2f}) < {adx_min:g}")
        direction = 0

    # 2. Ranging Filter
    if ema_gap < ranging_threshold:
        final_signal = (
            f"⚪ HOLD (Ranging Consolidation: |EMA fast-EMA slow| < "
            f"{ranging_threshold_pct:g}% Close)"
        )
        filter_reasons.append(
            f"|EMA fast - EMA slow| ({ema_gap:.4f}) < "
            f"{ranging_threshold_pct:g}% Close ({ranging_threshold:.4f})"
        )
        direction = 0

    # 3. King's Filter (Korelasi aset acuan) - Jika menganalisis Altcoin
    reference_asset = str(kings_filter_cfg["reference_asset"]).upper()
    btc_trend = None
    base_coin = symbol.split("/")[0].upper() if "/" in symbol else symbol.upper()
    if base_coin != reference_asset and df_btc_macro is not None and not df_btc_macro.empty:
        btc_ind = compute_indicators(df_btc_macro, config=cfg)
        last_btc = btc_ind.iloc[-1]
        btc_trend = 1 if float(last_btc["close"]) > float(last_btc["EMA_SLOW"]) else -1

        # Jika arah sinyal Altcoin berlawanan dengan tren aset acuan
        active_dir = direction if direction != 0 else macro_score
        if active_dir != 0 and btc_trend != active_dir:
            final_signal = "⚪ HOLD (Correlated Risk)"
            filter_reasons.append(
                f"King's Filter: {reference_asset} Macro Trend "
                f"({'Bullish' if btc_trend == 1 else 'Bearish'}) "
                f"berlawanan dengan arah sinyal Altcoin."
            )
            direction = 0

    # =========================================================================
    # SPESIFIKASI EKSEKUSI & MANAJEMEN RISIKO (PRD Bagian 2.D)
    # =========================================================================
    atr_fallback_pct = float(risk_cfg["atr_fallback_pct"])
    stop_loss_atr_multiplier = float(risk_cfg["stop_loss_atr_multiplier"])
    tp1_rrr = float(risk_cfg["tp1_rrr"])
    tp2_atr_offset_multiplier = float(risk_cfg["tp2_atr_offset_multiplier"])
    risk_fallback_atr_multiplier = float(risk_cfg["risk_fallback_atr_multiplier"])
    trailing_stop_atr_multiplier = float(risk_cfg["trailing_stop_atr_multiplier"])
    min_rrr = float(risk_cfg["min_rrr"])
    tp1_close_percent = float(risk_cfg["tp1_close_percent"])
    pullback_distance_pct = float(smart_money_cfg["pullback_distance_pct"])

    support = float(last_micro["SUPPORT"])
    resistance = float(last_micro["RESISTANCE"])
    atr = (
        float(last_micro["ATR"])
        if pd.notna(last_micro["ATR"])
        else ((atr_fallback_pct / 100.0) * close_price)
    )
    vol_now = float(last_micro["volume"])
    vol_sma_signal = float(last_micro["VOL_SMA_SIGNAL"])
    low_now = float(last_micro["low"])

    # Validasi Smart Money Mode (Liquidity Sweep & Low Volume Pullback)
    pullback_distance = pullback_distance_pct / 100.0
    liquidity_sweep = (low_now < support) and (close_price > support)
    low_vol_pullback = (vol_now < vol_sma_signal) and (
        abs(close_price - ema_fast) / close_price <= pullback_distance
        or abs(close_price - support) / close_price <= pullback_distance
    )
    smart_money_triggered = bool(liquidity_sweep and low_vol_pullback)

    resolved_execution_mode = execution_mode or cfg["analyze"]["execution_mode"]
    mode_upper = resolved_execution_mode.strip().upper()
    if mode_upper == "SMART_MONEY":
        # Limit Order di area Support / EMA fast
        entry_price = max(support, min(ema_fast, close_price))
        order_type = "LIMIT BUY (Area Support / EMA fast)"
    else:
        # FOMO Mode (Momentum Breakout): Market order di Close saat ini
        entry_price = close_price
        order_type = "MARKET ORDER (Close Price)"

    # Auto-Calculation Target sesuai formula PRD Bagian 2.D:
    # SL = Support - (N * ATR)
    # TP1 = Entry + (N * Risk)
    # TP2 = Resistance - (N * ATR)
    stop_loss = support - (stop_loss_atr_multiplier * atr)
    risk = entry_price - stop_loss

    # Pengaman jika harga tepat di bawah/sama dengan stop_loss agar tidak terjadi div-by-zero
    if risk <= 0:
        risk = risk_fallback_atr_multiplier * atr
        stop_loss = entry_price - risk

    tp1 = entry_price + (tp1_rrr * risk)
    tp2 = resistance - (tp2_atr_offset_multiplier * atr)
    reward_tp2 = tp2 - entry_price
    rrr_tp2 = reward_tp2 / risk if risk > 0 else 0.0

    # Trailing Stop (Opsional di tengah jalan jika harga melewati TP1 menuju TP2)
    ref_high = current_highest_high if current_highest_high is not None else float(last_micro["high"])
    trailing_stop = (
        (ref_high - (trailing_stop_atr_multiplier * atr)) if ref_high >= tp1 else None
    )

    # Filter RRR (PRD Bagian 2.D): Jika RRR < min_rrr -> HOLD
    if rrr_tp2 < min_rrr:
        final_signal = f"⚪ HOLD (RRR < 1:{min_rrr:g})"
        filter_reasons.append(f"RRR ({rrr_tp2:.2f}) di bawah batas minimum {min_rrr:g}")
        direction = 0

    ema_fast_length = int(ind_cfg["ema"]["fast"])
    ema_slow_length = int(ind_cfg["ema"]["slow"])
    rsi_length = int(ind_cfg["rsi_length"])
    atr_length = int(ind_cfg["atr_length"])
    adx_length = int(ind_cfg["adx_length"])
    volume_signal_length = int(ind_cfg["volume_sma"]["signal"])

    return {
        "symbol": symbol,
        "decision": final_signal,
        "raw_mtfa_signal": raw_signal,
        "scores": {
            "macro_score": macro_score,
            "micro_score": micro_score,
            "btc_macro_trend": btc_trend,
        },
        "filters": {
            "adx": round(adx_val, indicator_decimals),
            "adx_length": adx_length,
            "adx_min": adx_min,
            "adx_passed": adx_val >= adx_min,
            "ema_gap_pct": round((ema_gap / close_price) * 100, percent_decimals),
            "ranging_threshold_pct": ranging_threshold_pct,
            "ranging_passed": ema_gap >= ranging_threshold,
            "kings_filter_passed": "King's Filter" not in " ".join(filter_reasons),
            "min_rrr": min_rrr,
            "rrr_passed": rrr_tp2 >= min_rrr,
            "rejection_reasons": filter_reasons,
        },
        "indicators": {
            "close": round(close_price, price_decimals),
            "ema_fast": round(ema_fast, price_decimals),
            "ema_fast_length": ema_fast_length,
            "ema_slow": round(ema_slow, price_decimals),
            "ema_slow_length": ema_slow_length,
            "rsi": round(float(last_micro["RSI"]), indicator_decimals),
            "rsi_length": rsi_length,
            "atr": round(atr, price_decimals),
            "atr_length": atr_length,
            "volume": round(vol_now, volume_decimals),
            "vol_sma_signal": round(vol_sma_signal, volume_decimals),
            "volume_signal_length": volume_signal_length,
            "support": round(support, price_decimals),
            "resistance": round(resistance, price_decimals),
        },
        "execution_plan": {
            "mode": mode_upper,
            "order_type": order_type,
            "smart_money_valid": smart_money_triggered,
            "liquidity_sweep_detected": bool(liquidity_sweep),
            "entry": round(entry_price, price_decimals),
            "stop_loss": round(stop_loss, price_decimals),
            "tp1": round(tp1, price_decimals),
            "tp1_instruction": (
                f"Jual {tp1_close_percent:g}%, pindahkan SL ke titik Entry (Auto-Breakeven)"
            ),
            "tp2": round(tp2, price_decimals),
            "rrr": round(rrr_tp2, ratio_decimals),
            "trailing_stop": (
                round(trailing_stop, price_decimals) if trailing_stop is not None else None
            ),
        },
    }
