from typing import Any, Dict, Optional
import numpy as np
import pandas as pd
from core.indicators import compute_indicators


def compute_macro_score_series(df_macro: pd.DataFrame) -> pd.Series:
    """
    Vectorized Macro Score:
      +1 (Bullish) : Close_Macro > EMA_50_Macro
      -1 (Bearish) : Close_Macro < EMA_50_Macro
       0 (Neutral) : Close_Macro == EMA_50_Macro
    """
    conditions = [
        df_macro["close"] > df_macro["EMA_50"],
        df_macro["close"] < df_macro["EMA_50"],
    ]
    choices = [1, -1]
    return pd.Series(np.select(conditions, choices, default=0), index=df_macro.index)


def compute_micro_score_series(df_micro: pd.DataFrame) -> pd.Series:
    """
    Vectorized Micro Score sesuai PRD Bagian 2.C:
      +1 (Bullish) : Close_Micro > EMA_21_Micro, Volume_Micro > 1.5 * Vol_SMA_20, RSI_Micro 45-65.
      -1 (Bearish) : Close_Micro < EMA_21_Micro, Volume_Micro > 1.5 * Vol_SMA_20,
                     RSI_Micro < 55 (atau > 70 dgn rejection).
    """
    vol_surge = df_micro["volume"] > (1.5 * df_micro["VOL_SMA_20"])

    bull_cond = (
        (df_micro["close"] > df_micro["EMA_21"])
        & vol_surge
        & (df_micro["RSI_14"] >= 45.0)
        & (df_micro["RSI_14"] <= 65.0)
    )

    # Rejection saat RSI > 70: upper wick signifikan atau gagal tembus Resistance
    upper_wick = df_micro["high"] - np.maximum(df_micro["open"], df_micro["close"])
    candle_body = (df_micro["close"] - df_micro["open"]).abs()
    rsi_overbought_rejection = (df_micro["RSI_14"] > 70.0) & (
        (upper_wick > candle_body) | (df_micro["close"] < df_micro["open"])
    )

    bear_cond = (
        (df_micro["close"] < df_micro["EMA_21"])
        & vol_surge
        & ((df_micro["RSI_14"] < 55.0) | rsi_overbought_rejection)
    )

    conditions = [bull_cond, bear_cond]
    choices = [1, -1]
    return pd.Series(np.select(conditions, choices, default=0), index=df_micro.index)


def evaluate_mtfa_and_risk(
    symbol: str,
    df_macro: pd.DataFrame,
    df_micro: pd.DataFrame,
    df_btc_macro: Optional[pd.DataFrame] = None,
    execution_mode: str = "FOMO",
    current_highest_high: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Mengeksekusi algoritma keputusan penuh sesuai PRD Bagian 2.B, 2.C, dan 2.D.
    """
    macro = compute_indicators(df_macro)
    micro = compute_indicators(df_micro)

    macro["MACRO_SCORE"] = compute_macro_score_series(macro)
    micro["MICRO_SCORE"] = compute_micro_score_series(micro)

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
    adx_val = float(last_micro["ADX_14"]) if pd.notna(last_micro["ADX_14"]) else 0.0
    close_price = float(last_micro["close"])
    ema_21 = float(last_micro["EMA_21"])
    ema_50 = float(last_micro["EMA_50"])
    ema_gap = abs(ema_21 - ema_50)
    ranging_threshold = 0.005 * close_price  # 0.5% * Harga Close

    # 1. Market Regime (ADX Filter)
    if adx_val < 25.0:
        final_signal = "⚪ HOLD (Choppy Market: ADX < 25)"
        filter_reasons.append(f"ADX({adx_val:.2f}) < 25")
        direction = 0

    # 2. Ranging Filter
    if ema_gap < ranging_threshold:
        final_signal = "⚪ HOLD (Ranging Consolidation: |EMA21-EMA50| < 0.5% Close)"
        filter_reasons.append(f"|EMA21 - EMA50| ({ema_gap:.4f}) < 0.5% Close ({ranging_threshold:.4f})")
        direction = 0

    # 3. King's Filter (Korelasi BTC) - Jika menganalisis Altcoin
    btc_trend = None
    base_coin = symbol.split("/")[0].upper() if "/" in symbol else symbol.upper()
    if base_coin != "BTC" and df_btc_macro is not None and not df_btc_macro.empty:
        btc_ind = compute_indicators(df_btc_macro)
        last_btc = btc_ind.iloc[-1]
        btc_trend = 1 if float(last_btc["close"]) > float(last_btc["EMA_50"]) else -1

        # Jika arah sinyal Altcoin berlawanan dengan tren BTC, atau jika tren Macro Altcoin berlawanan dgn BTC
        active_dir = direction if direction != 0 else macro_score
        if active_dir != 0 and btc_trend != active_dir:
            final_signal = "⚪ HOLD (Correlated Risk)"
            filter_reasons.append(
                f"King's Filter: BTC Macro Trend ({'Bullish' if btc_trend == 1 else 'Bearish'}) "
                f"berlawanan dengan arah sinyal Altcoin."
            )
            direction = 0

    # =========================================================================
    # SPESIFIKASI EKSEKUSI & MANAJEMEN RISIKO (PRD Bagian 2.D)
    # =========================================================================
    support = float(last_micro["SUPPORT"])
    resistance = float(last_micro["RESISTANCE"])
    atr = float(last_micro["ATR_14"]) if pd.notna(last_micro["ATR_14"]) else (0.01 * close_price)
    vol_now = float(last_micro["volume"])
    vol_sma_20 = float(last_micro["VOL_SMA_20"])
    low_now = float(last_micro["low"])

    # Validasi Smart Money Mode (Liquidity Sweep & Low Volume Pullback)
    liquidity_sweep = (low_now < support) and (close_price > support)
    low_vol_pullback = (vol_now < vol_sma_20) and (
        abs(close_price - ema_21) / close_price <= 0.01 or abs(close_price - support) / close_price <= 0.01
    )
    smart_money_triggered = bool(liquidity_sweep and low_vol_pullback)

    mode_upper = execution_mode.strip().upper()
    if mode_upper == "SMART_MONEY":
        # Limit Order di area Support / EMA_21
        entry_price = max(support, min(ema_21, close_price))
        order_type = "LIMIT BUY (Area Support / EMA_21)"
    else:
        # FOMO Mode (Momentum Breakout): Market order di Close saat ini
        entry_price = close_price
        order_type = "MARKET ORDER (Close Price)"

    # Auto-Calculation Target sesuai formula PRD Bagian 2.D:
    # SL = Support - (0.5 * ATR(14))
    # TP1 = Entry + Risk (RRR 1:1)
    # TP2 = Resistance - (0.1 * ATR(14))
    stop_loss = support - (0.5 * atr)
    risk = entry_price - stop_loss

    # Pengaman jika harga tepat di bawah/sama dengan stop_loss agar tidak terjadi div-by-zero
    if risk <= 0:
        risk = 0.5 * atr
        stop_loss = entry_price - risk

    tp1 = entry_price + risk
    tp2 = resistance - (0.1 * atr)
    reward_tp2 = tp2 - entry_price
    rrr_tp2 = reward_tp2 / risk if risk > 0 else 0.0

    # Trailing Stop (Opsional di tengah jalan jika harga melewati TP1 menuju TP2)
    ref_high = current_highest_high if current_highest_high is not None else float(last_micro["high"])
    trailing_stop = (ref_high - (2.0 * atr)) if ref_high >= tp1 else None

    # Filter RRR (PRD Bagian 2.D): Jika (TP2-Entry)/(Entry-SL) < 1.5 -> HOLD (RRR < 1:1.5)
    if rrr_tp2 < 1.5:
        final_signal = "⚪ HOLD (RRR < 1:1.5)"
        filter_reasons.append(f"RRR ({rrr_tp2:.2f}) di bawah batas minimum 1.5")
        direction = 0

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
            "adx_14": round(adx_val, 2),
            "adx_passed": adx_val >= 25.0,
            "ema_gap_pct": round((ema_gap / close_price) * 100, 4),
            "ranging_passed": ema_gap >= ranging_threshold,
            "kings_filter_passed": "King's Filter" not in " ".join(filter_reasons),
            "rrr_passed": rrr_tp2 >= 1.5,
            "rejection_reasons": filter_reasons,
        },
        "indicators": {
            "close": round(close_price, 6),
            "ema_21": round(ema_21, 6),
            "ema_50": round(ema_50, 6),
            "rsi_14": round(float(last_micro["RSI_14"]), 2),
            "atr_14": round(atr, 6),
            "volume": round(vol_now, 2),
            "vol_sma_20": round(vol_sma_20, 2),
            "support": round(support, 6),
            "resistance": round(resistance, 6),
        },
        "execution_plan": {
            "mode": mode_upper,
            "order_type": order_type,
            "smart_money_valid": smart_money_triggered,
            "liquidity_sweep_detected": bool(liquidity_sweep),
            "entry": round(entry_price, 6),
            "stop_loss": round(stop_loss, 6),
            "tp1": round(tp1, 6),
            "tp1_instruction": "Jual 50%, pindahkan SL ke titik Entry (Auto-Breakeven)",
            "tp2": round(tp2, 6),
            "rrr": round(rrr_tp2, 2),
            "trailing_stop": round(trailing_stop, 6) if trailing_stop is not None else None,
        },
    }
