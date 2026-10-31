import json
from typing import Any, Dict, List

from core.config import get_config


def format_analysis_output(result: Dict[str, Any], as_json: bool = False) -> str:
    """
    Mengubah hasil matriks keputusan menjadi JSON string atau ringkasan kuantitatif
    teks mentah yang padat untuk konsumsi LLM Agent / Trader CLI.
    """
    cfg = get_config()
    json_indent = int(cfg["output"]["json_indent"])

    if as_json:
        return json.dumps(result, indent=json_indent, ensure_ascii=False)

    ind_cfg = cfg["indicators"]

    scores = result.get("scores", {})
    filters = result.get("filters", {})
    ind = result.get("indicators", {})
    plan = result.get("execution_plan", {})

    reasons = filters.get("rejection_reasons", [])
    reason_str = ", ".join(reasons) if reasons else "Semua Filter Terpenuhi (Lolos)"

    ema_fast_length = ind.get("ema_fast_length", ind_cfg["ema"]["fast"])
    ema_slow_length = ind.get("ema_slow_length", ind_cfg["ema"]["slow"])
    rsi_length = ind.get("rsi_length", ind_cfg["rsi_length"])
    atr_length = ind.get("atr_length", ind_cfg["atr_length"])
    adx_length = filters.get("adx_length", ind_cfg["adx_length"])
    sr_lookback = ind_cfg["support_resistance"]["lookback"]

    lines = [
        f"=== ALPHA-STRIKE ENGINE REPORT: {result.get('symbol')} ===",
        f"KEPUTUSAN FINAL : {result.get('decision')}",
        f"Sinyal MTFA     : {result.get('raw_mtfa_signal')} (Macro: {scores.get('macro_score')}, Micro: {scores.get('micro_score')})",
        f"Status Filter   : {reason_str}",
        "--- Indikator Teknis (Micro) ---",
        f"Close: {ind.get('close')} | EMA{ema_fast_length}: {ind.get('ema_fast')} | EMA{ema_slow_length}: {ind.get('ema_slow')}",
        f"RSI({rsi_length}): {ind.get('rsi')} | ADX({adx_length}): {filters.get('adx')} | ATR({atr_length}): {ind.get('atr')}",
        f"Support({sr_lookback}): {ind.get('support')} | Resistance({sr_lookback}): {ind.get('resistance')}",
        "--- Rencana Eksekusi & Risiko ---",
        f"Mode Eksekusi   : {plan.get('mode')} ({plan.get('order_type')})",
        f"Smart Money Val : Liquidity Sweep={plan.get('liquidity_sweep_detected')} | Valid={plan.get('smart_money_valid')}",
        f"Entry           : {plan.get('entry')}",
        f"Stop Loss (SL)  : {plan.get('stop_loss')}",
        f"Take Profit 1   : {plan.get('tp1')} -> [{plan.get('tp1_instruction')}]",
        f"Take Profit 2   : {plan.get('tp2')} (RRR 1:{plan.get('rrr')})",
        f"Trailing Stop   : {plan.get('trailing_stop') if plan.get('trailing_stop') is not None else 'Belum Aktif (Tunggu > TP1)'}",
    ]
    return "\n".join(lines)


def format_scanner_output(results: List[Dict[str, Any]], as_json: bool = False) -> str:
    """
    Mengubah hasil Market Scanner menjadi JSON atau tabel ringkas.
    """
    cfg = get_config()
    json_indent = int(cfg["output"]["json_indent"])

    if as_json:
        return json.dumps({"top_candidates": results}, indent=json_indent, ensure_ascii=False)

    if not results:
        return "=== MARKET SCANNER ===\nTidak ada koin yang memenuhi kriteria BB Squeeze + Volume Spike saat ini."

    scanner_sma_length = cfg["indicators"]["volume_sma"]["scanner"]
    volume_decimals = int(cfg["output"]["volume_decimals"])

    lines = ["=== MARKET SCANNER: TOP SQUEEZE + SPIKE CANDIDATES ==="]
    for idx, item in enumerate(results, start=1):
        lines.append(
            f"{idx}. {item['symbol']} | Close: {item['close']} | "
            f"Vol24H: {item['quote_volume_24h']:,.{volume_decimals}f} | "
            f"BB Squeeze: {item['bb_squeeze_ratio']} | "
            f"Vol Spike: {item['volume_spike_ratio']}x SMA{scanner_sma_length} | RSI: {item['rsi']}"
        )
    return "\n".join(lines)
