import json
from typing import Any, Dict, List


def format_analysis_output(result: Dict[str, Any], as_json: bool = False) -> str:
    """
    Mengubah hasil matriks keputusan menjadi JSON string atau ringkasan kuantitatif
    teks mentah yang padat untuk konsumsi LLM Agent / Trader CLI.
    """
    if as_json:
        return json.dumps(result, indent=2, ensure_ascii=False)

    scores = result.get("scores", {})
    filters = result.get("filters", {})
    ind = result.get("indicators", {})
    plan = result.get("execution_plan", {})

    reasons = filters.get("rejection_reasons", [])
    reason_str = ", ".join(reasons) if reasons else "Semua Filter Terpenuhi (Lolos)"

    lines = [
        f"=== ALPHA-STRIKE ENGINE REPORT: {result.get('symbol')} ===",
        f"KEPUTUSAN FINAL : {result.get('decision')}",
        f"Sinyal MTFA     : {result.get('raw_mtfa_signal')} (Macro: {scores.get('macro_score')}, Micro: {scores.get('micro_score')})",
        f"Status Filter   : {reason_str}",
        "--- Indikator Teknis (Micro) ---",
        f"Close: {ind.get('close')} | EMA21: {ind.get('ema_21')} | EMA50: {ind.get('ema_50')}",
        f"RSI(14): {ind.get('rsi_14')} | ADX(14): {filters.get('adx_14')} | ATR(14): {ind.get('atr_14')}",
        f"Support(50): {ind.get('support')} | Resistance(50): {ind.get('resistance')}",
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
    if as_json:
        return json.dumps({"top_candidates": results}, indent=2, ensure_ascii=False)

    if not results:
        return "=== MARKET SCANNER ===\nTidak ada koin yang memenuhi kriteria BB Squeeze + Volume Spike saat ini."

    lines = ["=== MARKET SCANNER: TOP SQUEEZE + SPIKE CANDIDATES ==="]
    for idx, item in enumerate(results, start=1):
        lines.append(
            f"{idx}. {item['symbol']} | Close: {item['close']} | "
            f"Vol24H: {item['quote_volume_24h']:,.0f} | "
            f"BB Squeeze: {item['bb_squeeze_ratio']} | "
            f"Vol Spike: {item['volume_spike_ratio']}x SMA24 | RSI: {item['rsi_14']}"
        )
    return "\n".join(lines)
