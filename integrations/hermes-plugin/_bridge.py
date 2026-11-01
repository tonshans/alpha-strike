#!/usr/bin/env python3
"""Alpha-Strike bridge used by the Hermes plugin.

This file runs inside the Alpha-Strike interpreter (not Hermes' venv). It keeps
the plugin free of third-party imports while still reusing the engine's config,
exchange wrapper, and indicators.

Usage (normally invoked by ``client.py``, not by a user)::

    python _bridge.py health --root /path/to/alpha-strike
    python _bridge.py monitor --root /path/to/alpha-strike \
        --symbol SOL/USDT --entry-price 100 --stop-loss 95 \
        --tp1 110 --tp2 120
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


def _bootstrap(root: str) -> Path:
    root_path = Path(root).expanduser().resolve()
    if not (root_path / "main_cli.py").is_file() or not (root_path / "config.yaml").is_file():
        raise RuntimeError(
            f"Folder '{root_path}' bukan root alpha-strike "
            "(main_cli.py dan config.yaml tidak ditemukan)."
        )
    sys.path.insert(0, str(root_path))
    return root_path


def _finite(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _round(value: Any, decimals: int) -> Optional[float]:
    number = _finite(value)
    return round(number, decimals) if number is not None else None


def _pct(value: float, reference: float) -> Optional[float]:
    if reference == 0:
        return None
    return round((value - reference) / reference * 100.0, 4)


def compute_monitor(
    *,
    symbol: str,
    entry_price: float,
    stop_loss: float,
    tp1: float,
    tp2: float,
    current_price: float,
    highest_high: float,
    atr: float,
    trailing_atr_multiplier: float,
    tp1_close_percent: float,
    price_decimals: int,
    exchange: str,
    timeframe: str,
    candle_time: Optional[str] = None,
    candle_high: Optional[float] = None,
) -> Dict[str, Any]:
    """Pure monitor calculation (kept separate so it is easy to test)."""
    warnings: List[str] = []

    if entry_price <= 0 or stop_loss <= 0 or tp1 <= 0 or tp2 <= 0:
        raise ValueError("entry_price, stop_loss, tp1, dan tp2 harus lebih besar dari 0.")
    if current_price <= 0:
        raise ValueError("current_price harus lebih besar dari 0.")

    if stop_loss >= entry_price:
        warnings.append(
            "stop_loss >= entry_price: ini bukan struktur posisi long yang valid."
        )
    if tp1 <= entry_price:
        warnings.append("tp1 <= entry_price: TP1 belum menghasilkan profit.")
    if tp2 <= tp1:
        warnings.append("tp2 <= tp1: urutan target take profit tidak valid.")
    if highest_high < entry_price:
        warnings.append(
            "highest_high < entry_price; nilai highest_high dinaikkan ke entry_price."
        )
        highest_high = entry_price

    high_reference = max(highest_high, current_price)
    trailing_stop: Optional[float] = None
    if atr <= 0:
        warnings.append("ATR tidak tersedia/0; trailing stop tidak dapat dihitung.")

    tp1_hit = high_reference >= tp1
    tp2_hit = current_price >= tp2

    breakeven_stop = entry_price if tp1_hit else None
    if tp1_hit and atr > 0:
        trailing_stop = high_reference - (trailing_atr_multiplier * atr)

    effective_stop = stop_loss
    if breakeven_stop is not None:
        effective_stop = max(effective_stop, breakeven_stop)
    if trailing_stop is not None:
        effective_stop = max(effective_stop, trailing_stop)

    risk_per_unit = entry_price - stop_loss
    if risk_per_unit <= 0:
        risk_per_unit = 0.0
    original_rrr = ((tp2 - entry_price) / risk_per_unit) if risk_per_unit > 0 else None

    if current_price <= effective_stop:
        recommended_action = "EXIT_STOP_LOSS"
    elif tp2_hit:
        recommended_action = "TP2_REACHED"
    elif tp1_hit:
        recommended_action = "TRAIL_TO_TP2"
    else:
        recommended_action = "HOLD"

    instructions: List[str] = []
    if recommended_action == "EXIT_STOP_LOSS":
        instructions.append(
            f"Harga {_round(current_price, price_decimals)} menyentuh stop efektif "
            f"{_round(effective_stop, price_decimals)}; pertimbangkan keluar posisi."
        )
    elif recommended_action == "TP2_REACHED":
        instructions.append(
            f"TP2 {_round(tp2, price_decimals)} tercapai; tutup sisa posisi atau "
            "kunci profit dengan trailing stop."
        )
    elif recommended_action == "TRAIL_TO_TP2":
        instructions.append(
            f"Jual {tp1_close_percent:g}% posisi di TP1 bila belum dieksekusi."
        )
        instructions.append(
            f"Pindahkan stop loss ke entry {_round(entry_price, price_decimals)} (breakeven)."
        )
        if trailing_stop is not None:
            instructions.append(
                f"Trailing stop aktif di {_round(trailing_stop, price_decimals)}; "
                f"target akhir TP2 {_round(tp2, price_decimals)}."
            )
    else:
        instructions.append(
            f"Tahan posisi; stop loss awal tetap di {_round(stop_loss, price_decimals)}."
        )
        instructions.append(
            f"Pantau TP1 di {_round(tp1, price_decimals)} untuk auto-breakeven."
        )

    remaining_rrr = None
    if current_price > effective_stop and current_price < tp2:
        remaining_rrr = round((tp2 - current_price) / (current_price - effective_stop), 4)

    return {
        "symbol": symbol,
        "exchange": exchange,
        "timeframe": timeframe,
        "market": {
            "current_price": _round(current_price, price_decimals),
            "candle_high": _round(candle_high, price_decimals) if candle_high is not None else None,
            "atr": _round(atr, price_decimals),
            "candle_time": candle_time,
        },
        "position": {
            "entry_price": _round(entry_price, price_decimals),
            "stop_loss": _round(stop_loss, price_decimals),
            "tp1": _round(tp1, price_decimals),
            "tp2": _round(tp2, price_decimals),
            "highest_high": _round(high_reference, price_decimals),
            "risk_per_unit": _round(risk_per_unit, price_decimals),
            "original_rrr": round(original_rrr, 4) if original_rrr is not None else None,
        },
        "monitor": {
            "tp1_hit": tp1_hit,
            "tp2_hit": tp2_hit,
            "auto_breakeven_triggered": tp1_hit,
            "breakeven_stop": _round(breakeven_stop, price_decimals),
            "trailing_stop": _round(trailing_stop, price_decimals),
            "effective_stop_loss": _round(effective_stop, price_decimals),
            "recommended_action": recommended_action,
            "instructions": instructions,
            "unrealized_pnl_pct": _pct(current_price, entry_price),
            "distance_to_tp1_pct": _pct(tp1, current_price),
            "distance_to_tp2_pct": _pct(tp2, current_price),
            "remaining_rrr": remaining_rrr,
        },
        "settings": {
            "trailing_atr_multiplier": trailing_atr_multiplier,
            "tp1_close_percent": tp1_close_percent,
        },
        "warnings": warnings,
    }


def _load_engine_config():
    from core.config import get_config

    return get_config()


def _cmd_health(args: argparse.Namespace) -> Dict[str, Any]:
    root = _bootstrap(args.root)

    import ccxt
    import pandas
    import pandas_ta
    import yaml

    cfg = _load_engine_config()
    exchange_cfg = cfg.get("exchange", {})
    analyze_cfg = cfg.get("analyze", {})

    return {
        "root": str(root),
        "python": sys.executable,
        "config_path": os.environ.get("ALPHA_STRIKE_CONFIG") or str(root / "config.yaml"),
        "dependencies": {
            "ccxt": getattr(ccxt, "__version__", "unknown"),
            "pandas": getattr(pandas, "__version__", "unknown"),
            "pandas_ta": getattr(pandas_ta, "__version__", "unknown"),
            "PyYAML": getattr(yaml, "__version__", "unknown"),
        },
        "default_exchange": exchange_cfg.get("default"),
        "supported_exchanges": exchange_cfg.get("supported", []),
        "default_macro_timeframe": analyze_cfg.get("macro_timeframe"),
        "default_micro_timeframe": analyze_cfg.get("micro_timeframe"),
        "default_execution_mode": analyze_cfg.get("execution_mode"),
    }


def _cmd_monitor(args: argparse.Namespace) -> Dict[str, Any]:
    root = _bootstrap(args.root)

    from data.exchange_api import ExchangeAPI
    from core.indicators import compute_indicators

    cfg = _load_engine_config()
    exchange_cfg = cfg.get("exchange", {})
    analyze_cfg = cfg.get("analyze", {})
    risk_cfg = cfg.get("logic", {}).get("risk", {})
    output_cfg = cfg.get("output", {})

    exchange = args.exchange or str(exchange_cfg.get("default", "binance"))
    timeframe = args.timeframe or str(analyze_cfg.get("micro_timeframe", "15m"))
    limit = int(exchange_cfg.get("ohlcv_limit", 150))

    api = ExchangeAPI(exchange_id=exchange)
    df = api.fetch_ohlcv_df(args.symbol, timeframe=timeframe, limit=limit)
    indicators = compute_indicators(df)
    last = indicators.iloc[-1]

    close = _finite(last["close"])
    if close is None or close <= 0:
        raise RuntimeError("Harga close terbaru tidak valid.")
    current_price = float(args.current_price) if args.current_price is not None else close
    candle_high = _finite(last.get("high"))

    atr_value = _finite(last.get("ATR"))
    if atr_value is None:
        fallback_pct = float(risk_cfg.get("atr_fallback_pct", 1.0))
        atr_value = (fallback_pct / 100.0) * close

    highest_high = (
        float(args.highest_high)
        if args.highest_high is not None
        else max(current_price, candle_high or current_price, float(args.entry_price))
    )

    trailing_multiplier = float(risk_cfg.get("trailing_stop_atr_multiplier", 2.0))
    tp1_close_percent = float(risk_cfg.get("tp1_close_percent", 50.0))
    price_decimals = int(output_cfg.get("price_decimals", 6))

    candle_time = None
    if "timestamp" in last:
        try:
            candle_time = last["timestamp"].isoformat()
        except (AttributeError, TypeError, ValueError):
            candle_time = str(last["timestamp"])

    return compute_monitor(
        symbol=args.symbol,
        entry_price=float(args.entry_price),
        stop_loss=float(args.stop_loss),
        tp1=float(args.tp1),
        tp2=float(args.tp2),
        current_price=current_price,
        highest_high=highest_high,
        atr=atr_value,
        trailing_atr_multiplier=trailing_multiplier,
        tp1_close_percent=tp1_close_percent,
        price_decimals=price_decimals,
        exchange=exchange,
        timeframe=timeframe,
        candle_time=candle_time,
        candle_high=candle_high,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Alpha-Strike <-> Hermes bridge")
    subparsers = parser.add_subparsers(dest="command", required=True)

    health = subparsers.add_parser("health", help="Validate the engine installation")
    health.add_argument("--root", required=True, help="Path to the alpha-strike repository")
    health.set_defaults(func=_cmd_health)

    monitor = subparsers.add_parser("monitor", help="Monitor a long position")
    monitor.add_argument("--root", required=True, help="Path to the alpha-strike repository")
    monitor.add_argument("--symbol", required=True)
    monitor.add_argument("--entry-price", required=True, type=float)
    monitor.add_argument("--stop-loss", required=True, type=float)
    monitor.add_argument("--tp1", required=True, type=float)
    monitor.add_argument("--tp2", required=True, type=float)
    monitor.add_argument("--highest-high", type=float, default=None)
    monitor.add_argument("--current-price", type=float, default=None)
    monitor.add_argument("--exchange", default=None)
    monitor.add_argument("--timeframe", default=None)
    monitor.set_defaults(func=_cmd_monitor)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        data = args.func(args)
        result: Dict[str, Any] = {"ok": True, "data": data}
    except Exception as exc:  # noqa: BLE001 - always return structured JSON
        result = {"ok": False, "error": str(exc), "type": type(exc).__name__}
        if os.environ.get("ALPHA_STRIKE_BRIDGE_DEBUG") == "1":
            import traceback

            result["traceback"] = traceback.format_exc()

    print(json.dumps(result, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
