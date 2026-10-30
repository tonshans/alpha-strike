import json


def _fmt_num(val: float | int | None) -> str:
    if val is None:
        return "N/A"
    if isinstance(val, bool):
        return str(val)
    if isinstance(val, int):
        return str(val)
    abs_v = abs(val)
    if abs_v >= 1000:
        return f"{val:.2f}"
    if abs_v >= 1:
        return f"{val:.4f}"
    return f"{val:.6f}"


def format_decision_kv(decision: dict, symbol: str = "UNKNOWN") -> str:
    regime = decision.get("regime_filter", {})
    kings = decision.get("kings_filter", {})
    mtfa = decision.get("mtfa_scores", {})
    macro = mtfa.get("macro", {})
    micro = mtfa.get("micro", {})
    exec_plan = decision.get("execution", {})

    lines = [
        f"SYMBOL: {symbol}",
        f"FINAL_SIGNAL: {decision.get('final_signal', 'HOLD')}",
        f"RAW_MTFA_SIGNAL: {decision.get('raw_mtfa_signal', 'HOLD')}",
        f"STRATEGY_MODE: {decision.get('strategy_mode', 'N/A')}",
        f"REGIME_PASSED: {regime.get('passed', False)}",
        f"ADX_14: {_fmt_num(regime.get('adx_value'))}",
        f"ADX_PASSED: {regime.get('adx_passed', False)}",
        f"EMA_GAP: {_fmt_num(regime.get('ema_gap'))}",
        f"MIN_REQUIRED_GAP: {_fmt_num(regime.get('min_required_gap'))}",
        f"RANGING_PASSED: {regime.get('ranging_passed', False)}",
        f"KINGS_FILTER_PASSED: {kings.get('passed', False)}",
        f"KINGS_FILTER_STATUS: {kings.get('status', 'N/A')}",
        f"BTC_MACRO_TREND: {kings.get('btc_trend_score', 0)}",
        f"MACRO_SCORE: {macro.get('score', 0)}",
        f"MICRO_SCORE: {micro.get('score', 0)}",
        f"MICRO_RSI_14: {_fmt_num(micro.get('rsi_value'))}",
        f"MICRO_VOLUME_PASSED: {micro.get('volume_passed', False)}",
        f"ORDER_TYPE: {exec_plan.get('order_type', 'N/A')}",
        f"MODE_TRIGGERED: {exec_plan.get('triggered', False)}",
        f"ENTRY_PRICE: {_fmt_num(exec_plan.get('Entry'))}",
        f"STOP_LOSS: {_fmt_num(exec_plan.get('SL'))}",
        f"TAKE_PROFIT_1: {_fmt_num(exec_plan.get('TP1'))}",
        f"TAKE_PROFIT_2: {_fmt_num(exec_plan.get('TP2'))}",
        f"TRAILING_SL: {_fmt_num(exec_plan.get('Trailing_SL'))}",
        f"RISK_PER_UNIT: {_fmt_num(exec_plan.get('Risk'))}",
        f"REWARD_TP2_PER_UNIT: {_fmt_num(exec_plan.get('Reward_TP2'))}",
        f"RRR_RATIO: {_fmt_num(exec_plan.get('RRR'))}",
        f"RRR_PASSED: {exec_plan.get('rrr_passed', False)}",
        f"TP1_ACTION: {exec_plan.get('tp1_instruction', 'N/A')}",
    ]
    return "\n".join(lines)


def format_scan_kv(scan_result: dict) -> str:
    lines = [
        f"SCAN_STATUS: {scan_result.get('status', 'error')}",
        f"EXCHANGE: {scan_result.get('exchange', 'N/A')}",
        f"TIMEFRAME: {scan_result.get('timeframe', 'N/A')}",
        f"SCANNED_LIQUID_PAIRS: {scan_result.get('scanned_liquid_pairs', 0)}",
        f"MATCHED_COUNT: {scan_result.get('matched_count', 0)}",
    ]

    if scan_result.get("error"):
        lines.append(f"ERROR_MESSAGE: {scan_result['error']}")

    for idx, item in enumerate(scan_result.get("top_results", []), start=1):
        lines.extend([
            f"RESULT_{idx}_SYMBOL: {item.get('symbol', 'N/A')}",
            f"RESULT_{idx}_CLOSE: {_fmt_num(item.get('close'))}",
            f"RESULT_{idx}_QUOTE_VOL_24H: {_fmt_num(item.get('quote_volume_24h'))}",
            f"RESULT_{idx}_SQUEEZE_RATIO: {_fmt_num(item.get('squeeze_ratio'))}",
            f"RESULT_{idx}_SPIKE_RATIO: {_fmt_num(item.get('spike_ratio'))}",
        ])

    return "\n".join(lines)


def format_as_json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


if __name__ == "__main__":
    # Self-check schema validation
    assert len(HERMES_TOOLS) == 3
    names = [t["function"]["name"] for t in HERMES_TOOLS]
    assert names == ["analyze_market", "create_scan_schedule", "add_to_monitor"]
    assert isinstance(get_schemas_json(), str)

    # Self-check formatter Key-Value output
    sample_decision = {
        "final_signal": "🟢 STRONG BUY",
        "raw_mtfa_signal": "🟢 STRONG BUY",
        "strategy_mode": "FOMO",
        "regime_filter": {
            "passed": True, "adx_value": 31.2, "adx_passed": True,
            "ema_gap": 1.25, "min_required_gap": 0.5, "ranging_passed": True,
        },
        "kings_filter": {"passed": True, "btc_trend_score": 1, "status": "PASS"},
        "mtfa_scores": {
            "macro": {"score": 1},
            "micro": {"score": 1, "rsi_value": 58.4, "volume_passed": True},
        },
        "execution": {
            "order_type": "MARKET", "triggered": True,
            "Entry": 105.0, "SL": 100.0, "TP1": 110.0, "TP2": 119.8,
            "Trailing_SL": 102.0, "Risk": 5.0, "Reward_TP2": 14.8,
            "RRR": 2.96, "rrr_passed": True,
            "tp1_instruction": "Jual 50%, pindahkan SL ke titik Entry (Auto-Breakeven)",
        },
    }
    kv_out = format_decision_kv(sample_decision, symbol="SOL/USDT")
    assert "SYMBOL: SOL/USDT" in kv_out
    assert "FINAL_SIGNAL: 🟢 STRONG BUY" in kv_out
    assert "RRR_RATIO: 2.9600" in kv_out
