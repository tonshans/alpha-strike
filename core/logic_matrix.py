# core/logic_matrix.py
import pandas as pd


def evaluate_regime(df_micro: pd.DataFrame) -> dict:
    last = df_micro.iloc[-1]
    close = float(last["close"])
    adx = float(last["ADX_14"])
    ema_gap = abs(float(last["EMA_21"]) - float(last["EMA_50"]))
    min_gap = 0.005 * close

    adx_passed = adx >= 25.0
    ranging_passed = ema_gap >= min_gap
    passed = bool(adx_passed and ranging_passed)

    return {
        "passed": passed,
        "adx_value": adx,
        "adx_passed": bool(adx_passed),
        "ema_gap": ema_gap,
        "min_required_gap": min_gap,
        "ranging_passed": bool(ranging_passed),
        "signal": "PASS" if passed else "HOLD",
    }


def score_tf(df: pd.DataFrame, tf_type: str = "micro") -> dict:
    last = df.iloc[-1]
    close = float(last["close"])

    if tf_type == "macro":
        ema50 = float(last["EMA_50"])
        bullish = close > ema50
        bearish = close < ema50
        score = 1 if bullish else (-1 if bearish else 0)
        return {
            "tf_type": "macro",
            "trend_bullish": bool(bullish),
            "trend_bearish": bool(bearish),
            "score": score,
        }

    open_p = float(last["open"])
    ema21 = float(last["EMA_21"])
    rsi = float(last["RSI_14"])
    vol = float(last["volume"])
    vol_sma20 = float(last["Vol_SMA_20"])

    vol_passed = vol > (1.5 * vol_sma20)
    bull_trend = close > ema21
    bear_trend = close < ema21
    bull_rsi = 45.0 <= rsi <= 65.0
    bear_rsi = (rsi < 55.0) or (rsi > 70.0 and close < open_p)

    is_bullish = bull_trend and vol_passed and bull_rsi
    is_bearish = bear_trend and vol_passed and bear_rsi
    score = 1 if is_bullish else (-1 if is_bearish else 0)

    return {
        "tf_type": "micro",
        "bull_trend_passed": bool(bull_trend),
        "bear_trend_passed": bool(bear_trend),
        "volume_passed": bool(vol_passed),
        "bull_rsi_passed": bool(bull_rsi),
        "bear_rsi_passed": bool(bear_rsi),
        "rsi_value": rsi,
        "score": score,
    }


def check_btc_kings_filter(df_macro_btc: pd.DataFrame, altcoin_signal: int | str) -> dict:
    last = df_macro_btc.iloc[-1]
    btc_close = float(last["close"])
    btc_ema50 = float(last["EMA_50"])
    btc_dir = 1 if btc_close > btc_ema50 else (-1 if btc_close < btc_ema50 else 0)

    sig_map = {
        1: 1, "BUY": 1, "STRONG BUY": 1, "🟢 STRONG BUY": 1,
        -1: -1, "SELL": -1, "STRONG SELL": -1, "🔴 STRONG SELL": -1,
    }
    alt_dir = sig_map.get(altcoin_signal, 0)

    conflict = (alt_dir == 1 and btc_dir == -1) or (alt_dir == -1 and btc_dir == 1)
    passed = not conflict

    return {
        "passed": bool(passed),
        "btc_trend_score": btc_dir,
        "altcoin_direction": alt_dir,
        "status": "PASS" if passed else "HOLD (Correlated Risk)",
    }


def _calc_targets(entry: float, support: float, resistance: float, atr: float, high: float) -> dict:
    sl = support - (0.5 * atr)
    risk = entry - sl
    tp1 = entry + risk
    tp2 = resistance - (0.1 * atr)
    rrr = (tp2 - entry) / risk if risk > 0 else 0.0
    trailing_sl = high - (2.0 * atr)
    rrr_passed = rrr >= 1.5

    return {
        "Entry": entry,
        "SL": sl,
        "TP1": tp1,
        "TP2": tp2,
        "Trailing_SL": trailing_sl,
        "Risk": risk,
        "Reward_TP2": tp2 - entry,
        "RRR": rrr,
        "rrr_passed": bool(rrr_passed),
        "tp1_instruction": "Jual 50%, pindahkan SL ke titik Entry (Auto-Breakeven)",
    }


def evaluate_execution_modes(df_micro: pd.DataFrame, mtfa_signal: str, macro_score: int) -> dict:
    last = df_micro.iloc[-1]
    close = float(last["close"])
    low = float(last["low"])
    high = float(last["high"])
    vol = float(last["volume"])
    vol_sma20 = float(last["Vol_SMA_20"])
    ema21 = float(last["EMA_21"])
    support = float(last["Support"])
    resistance = float(last["Resistance"])
    atr = float(last["ATR_14"])

    # 1. FOMO Breakout Mode (Market Entry saat STRONG BUY)
    fomo_triggered = mtfa_signal == "🟢 STRONG BUY"
    fomo_targets = _calc_targets(close, support, resistance, atr, high)
    fomo_plan = {
        "mode": "FOMO",
        "order_type": "MARKET",
        "triggered": bool(fomo_triggered),
        **fomo_targets,
    }

    # 2. Smart Money Retest Mode (Limit di Support/EMA21, Vol < SMA20, Wick Sweep)
    vol_shrinking = vol < vol_sma20
    liquidity_sweep = (low < support) and (close > support)
    touched_zone = (low <= ema21 <= high) or liquidity_sweep
    sm_triggered = (macro_score == 1) and vol_shrinking and liquidity_sweep and touched_zone

    # Gunakan EMA_21 jika berada di antara Support dan Close, selain itu gunakan Support
    sm_entry = ema21 if (support <= ema21 <= close) else support
    sm_targets = _calc_targets(sm_entry, support, resistance, atr, high)
    smart_money_plan = {
        "mode": "SMART_MONEY",
        "order_type": "LIMIT",
        "triggered": bool(sm_triggered),
        "vol_shrinking_passed": bool(vol_shrinking),
        "liquidity_sweep_passed": bool(liquidity_sweep),
        "touched_zone_passed": bool(touched_zone),
        **sm_targets,
    }

    return {
        "FOMO": fomo_plan,
        "SMART_MONEY": smart_money_plan,
    }


def evaluate_decision_matrix(
    df_macro: pd.DataFrame,
    df_micro: pd.DataFrame,
    df_macro_btc: pd.DataFrame | None = None,
    strategy_mode: str = "AUTO",
) -> dict:
    regime = evaluate_regime(df_micro)
    macro_eval = score_tf(df_macro, "macro")
    micro_eval = score_tf(df_micro, "micro")

    m_score = macro_eval["score"]
    u_score = micro_eval["score"]

    matrix_map = {
        (1, 1): "🟢 STRONG BUY",
        (-1, -1): "🔴 STRONG SELL",
        (1, -1): "⚪ PULLBACK / HOLD",
        (-1, 1): "⚪ DEAD CAT BOUNCE / HOLD",
    }
    raw_mtfa_signal = matrix_map.get((m_score, u_score), "HOLD")

    modes = evaluate_execution_modes(df_micro, raw_mtfa_signal, m_score)

    if strategy_mode == "FOMO":
        active_plan = modes["FOMO"]
    elif strategy_mode == "SMART_MONEY":
        active_plan = modes["SMART_MONEY"]
    else:
        active_plan = (
            modes["SMART_MONEY"]
            if modes["SMART_MONEY"]["triggered"] and raw_mtfa_signal != "🟢 STRONG BUY"
            else modes["FOMO"]
        )

    final_signal = raw_mtfa_signal
    if active_plan["mode"] == "SMART_MONEY" and active_plan["triggered"]:
        final_signal = "🟢 SMART MONEY BUY (LIMIT)"

    kings = {
        "passed": True,
        "btc_trend_score": 0,
        "altcoin_direction": 0,
        "status": "SKIPPED (No BTC Data)",
    }
    if df_macro_btc is not None:
        alt_dir = 1 if "BUY" in final_signal else (-1 if "SELL" in final_signal else 0)
        kings = check_btc_kings_filter(df_macro_btc, alt_dir)

    # Urutan gerbang pembatalan sinyal sesuai PRD
    if not regime["passed"]:
        final_signal = "HOLD"
    elif not kings["passed"]:
        final_signal = "HOLD (Correlated Risk)"
    elif strategy_mode in ("FOMO", "SMART_MONEY") and not active_plan["triggered"]:
        final_signal = "HOLD"
    elif "BUY" in final_signal and not active_plan["rrr_passed"]:
        final_signal = "HOLD (RRR < 1:1.5)"

    return {
        "final_signal": final_signal,
        "raw_mtfa_signal": raw_mtfa_signal,
        "strategy_mode": active_plan["mode"],
        "regime_filter": regime,
        "kings_filter": kings,
        "mtfa_scores": {
            "macro": macro_eval,
            "micro": micro_eval,
        },
        "execution": active_plan,
        "all_modes": modes,
    }


if __name__ == "__main__":
    df_mac = pd.DataFrame([{"close": 110.0, "EMA_50": 100.0}])
    df_btc = pd.DataFrame([{"close": 65000.0, "EMA_50": 60000.0}])

    # Test 1: FOMO Breakout valid (STRONG BUY & RRR >= 1.5)
    df_mic_fomo = pd.DataFrame([{
        "open": 100.0, "high": 106.0, "low": 99.5, "close": 105.0, "volume": 2000.0,
        "EMA_21": 102.0, "EMA_50": 100.0, "ADX_14": 30.0, "RSI_14": 55.0,
        "Vol_SMA_20": 1000.0, "Support": 101.0, "Resistance": 120.0, "ATR_14": 2.0,
    }])
    res_fomo = evaluate_decision_matrix(df_mac, df_mic_fomo, df_btc, strategy_mode="FOMO")
    assert res_fomo["final_signal"] == "🟢 STRONG BUY"
    assert res_fomo["execution"]["SL"] == 100.0
    assert res_fomo["execution"]["TP1"] == 110.0
    assert res_fomo["execution"]["TP2"] == 119.8
    assert res_fomo["execution"]["RRR"] >= 1.5

    # Test 2: Filter RRR membatalkan sinyal jika Resistance terlalu dekat
    df_mic_low_rrr = df_mic_fomo.copy()
    df_mic_low_rrr["Resistance"] = 108.0
    res_low_rrr = evaluate_decision_matrix(df_mac, df_mic_low_rrr, df_btc, strategy_mode="FOMO")
    assert res_low_rrr["final_signal"] == "HOLD (RRR < 1:1.5)"

    # Test 3: Smart Money Retest valid (Vol < SMA20, Low < Support < Close)
    df_mic_sm = pd.DataFrame([{
        "open": 102.0, "high": 103.0, "low": 99.5, "close": 101.0, "volume": 800.0,
        "EMA_21": 101.5, "EMA_50": 100.0, "ADX_14": 28.0, "RSI_14": 48.0,
        "Vol_SMA_20": 1000.0, "Support": 100.0, "Resistance": 110.0, "ATR_14": 2.0,
    }])
    res_sm = evaluate_decision_matrix(df_mac, df_mic_sm, df_btc, strategy_mode="SMART_MONEY")
    assert res_sm["final_signal"] == "🟢 SMART MONEY BUY (LIMIT)"
    assert res_sm["execution"]["Entry"] == 100.0
    assert res_sm["execution"]["SL"] == 99.0
    assert res_sm["execution"]["TP1"] == 101.0
