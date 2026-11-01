"""Tool handlers for the Alpha-Strike Hermes plugin.

Every handler follows the Hermes contract: accept ``params, **kwargs`` and
always return a JSON string, including on failure. Exceptions are converted to
an ``{"ok": false, ...}`` envelope so Hermes never sees a crashing tool.
"""

from __future__ import annotations

import logging
import math
import re
from typing import Any, Dict, List, Optional

from . import client

logger = logging.getLogger(__name__)

TOOL_ANALYZE = "alpha_strike_analyze_asset"
TOOL_SCAN = "alpha_strike_scan_market"
TOOL_MONITOR = "alpha_strike_monitor_position"

_SYMBOL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{1,31}$")
_EXCHANGE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,31}$")
_TIMEFRAME_RE = re.compile(r"^[0-9]{1,4}[mhdwM]$")
_ALLOWED_MODES = {"FOMO", "SMART_MONEY"}


class InvalidInput(ValueError):
    """User/model supplied an argument that cannot be used safely."""


def _string_param(
    params: Dict[str, Any],
    key: str,
    *,
    required: bool = False,
    pattern: Optional[re.Pattern[str]] = None,
    label: Optional[str] = None,
) -> Optional[str]:
    value = params.get(key)
    if value is None:
        if required:
            raise InvalidInput(f"Parameter '{key}' wajib diisi.")
        return None
    if not isinstance(value, str):
        raise InvalidInput(f"Parameter '{key}' harus berupa string.")
    text = value.strip()
    if not text:
        if required:
            raise InvalidInput(f"Parameter '{key}' tidak boleh kosong.")
        return None
    if pattern is not None and not pattern.match(text):
        raise InvalidInput(
            f"Nilai '{key}' tidak valid: {text!r}. "
            f"Format yang diterima: {label or 'string yang sesuai'}."
        )
    return text


def _number_param(
    params: Dict[str, Any], key: str, *, required: bool = False
) -> Optional[float]:
    value = params.get(key)
    if value is None or value == "":
        if required:
            raise InvalidInput(f"Parameter '{key}' wajib diisi.")
        return None
    if isinstance(value, bool):
        raise InvalidInput(f"Parameter '{key}' harus berupa angka.")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise InvalidInput(f"Parameter '{key}' harus berupa angka.") from exc
    if not math.isfinite(number) or number <= 0:
        raise InvalidInput(f"Parameter '{key}' harus berupa angka positif yang valid.")
    return number


def _symbols_param(params: Dict[str, Any]) -> Optional[List[str]]:
    value = params.get("symbols")
    if value is None:
        return None
    if not isinstance(value, list):
        raise InvalidInput("Parameter 'symbols' harus berupa array string.")
    if len(value) > 50:
        raise InvalidInput("Parameter 'symbols' maksimal berisi 50 simbol per pemindaian.")

    symbols: List[str] = []
    for item in value:
        if not isinstance(item, str):
            raise InvalidInput("Setiap item di 'symbols' harus berupa string.")
        symbol = item.strip()
        if not symbol:
            continue
        if not _SYMBOL_RE.match(symbol):
            raise InvalidInput(f"Simbol tidak valid: {symbol!r}. Contoh: 'BTC/USDT'.")
        if symbol not in symbols:
            symbols.append(symbol)

    if value and not symbols:
        raise InvalidInput("Parameter 'symbols' tidak boleh berisi string kosong.")
    return symbols or None


def _mode_param(params: Dict[str, Any]) -> Optional[str]:
    value = params.get("mode")
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidInput("Parameter 'mode' harus berupa string.")
    mode = value.strip().upper()
    if not mode:
        return None
    if mode not in _ALLOWED_MODES:
        raise InvalidInput(
            f"Mode tidak valid: {value!r}. Pilihan yang tersedia: FOMO atau SMART_MONEY."
        )
    return mode


def _handle_error(tool: str, exc: Exception) -> str:
    if isinstance(exc, (InvalidInput, client.AlphaStrikeError)):
        return client.failure(tool, str(exc))
    logger.exception("Unexpected error in %s", tool)
    return client.failure(
        tool,
        f"Terjadi error internal pada plugin Alpha-Strike: {exc}",
        hint="Periksa log Hermes dan jalankan installer ulang bila masalah berlanjut.",
    )


def analyze_asset(ctx: Any, params: Dict[str, Any], **kwargs: Any) -> str:
    """Run MTFA analysis for one symbol through ``main_cli.py``."""
    del kwargs
    try:
        symbol = _string_param(params, "symbol", required=True, pattern=_SYMBOL_RE, label="'BTC/USDT'")
        exchange = _string_param(params, "exchange", pattern=_EXCHANGE_RE, label="'binance' atau 'indodax'")
        macro_tf = _string_param(params, "macro_tf", pattern=_TIMEFRAME_RE, label="'4h', '1d'")
        micro_tf = _string_param(params, "micro_tf", pattern=_TIMEFRAME_RE, label="'15m', '1h'")
        mode = _mode_param(params)

        args = ["analyze", "--symbol", symbol, "--json"]
        if exchange:
            args += ["--exchange", exchange]
        if macro_tf:
            args += ["--macro-tf", macro_tf]
        if micro_tf:
            args += ["--micro-tf", micro_tf]
        if mode:
            args += ["--mode", mode]

        data, meta = client.run_cli(ctx, args, tool=TOOL_ANALYZE)
        return client.success(TOOL_ANALYZE, data, meta)
    except Exception as exc:  # noqa: BLE001 - handler must never raise
        return _handle_error(TOOL_ANALYZE, exc)


def scan_market(ctx: Any, params: Dict[str, Any], **kwargs: Any) -> str:
    """Run the BB Squeeze + Volume Spike scanner through ``main_cli.py``."""
    del kwargs
    try:
        exchange = _string_param(params, "exchange", pattern=_EXCHANGE_RE, label="'binance' atau 'indodax'")
        timeframe = _string_param(params, "timeframe", pattern=_TIMEFRAME_RE, label="'1h', '4h'")
        symbols = _symbols_param(params)

        args = ["scan", "--json"]
        if exchange:
            args += ["--exchange", exchange]
        if timeframe:
            args += ["--timeframe", timeframe]
        if symbols:
            args += ["--symbols", *symbols]

        data, meta = client.run_cli(ctx, args, tool=TOOL_SCAN)
        return client.success(TOOL_SCAN, data, meta)
    except Exception as exc:  # noqa: BLE001 - handler must never raise
        return _handle_error(TOOL_SCAN, exc)


def monitor_position(ctx: Any, params: Dict[str, Any], **kwargs: Any) -> str:
    """Fetch the latest ATR/price and compute long-position management levels."""
    del kwargs
    try:
        symbol = _string_param(params, "symbol", required=True, pattern=_SYMBOL_RE, label="'SOL/USDT'")
        entry_price = _number_param(params, "entry_price", required=True)
        stop_loss = _number_param(params, "stop_loss", required=True)
        tp1 = _number_param(params, "tp1", required=True)
        tp2 = _number_param(params, "tp2", required=True)
        highest_high = _number_param(params, "highest_high")
        current_price = _number_param(params, "current_price")
        exchange = _string_param(params, "exchange", pattern=_EXCHANGE_RE, label="'binance'")
        timeframe = _string_param(params, "timeframe", pattern=_TIMEFRAME_RE, label="'15m'")

        # Basic sanity checks for a long position. The bridge repeats these so a
        # direct invocation gets the same protection.
        if stop_loss >= entry_price:
            raise InvalidInput("Untuk posisi long, stop_loss harus lebih kecil dari entry_price.")
        if tp1 <= entry_price:
            raise InvalidInput("tp1 harus lebih besar dari entry_price.")
        if tp2 <= tp1:
            raise InvalidInput("tp2 harus lebih besar dari tp1.")
        if highest_high is not None and highest_high < entry_price:
            raise InvalidInput("highest_high tidak boleh lebih kecil dari entry_price.")

        root = client.resolve_root(ctx)
        args = [
            "monitor",
            "--root",
            str(root),
            "--symbol",
            symbol,
            "--entry-price",
            str(entry_price),
            "--stop-loss",
            str(stop_loss),
            "--tp1",
            str(tp1),
            "--tp2",
            str(tp2),
        ]
        if highest_high is not None:
            args += ["--highest-high", str(highest_high)]
        if current_price is not None:
            args += ["--current-price", str(current_price)]
        if exchange:
            args += ["--exchange", exchange]
        if timeframe:
            args += ["--timeframe", timeframe]

        payload, meta = client.run_bridge(ctx, args, tool=TOOL_MONITOR)
        if payload.get("ok") is False:
            return client.failure(
                TOOL_MONITOR,
                str(payload.get("error") or "Bridge monitor mengembalikan error."),
                hint=payload.get("hint"),
            )
        return client.success(TOOL_MONITOR, payload.get("data", payload), meta)
    except Exception as exc:  # noqa: BLE001 - handler must never raise
        return _handle_error(TOOL_MONITOR, exc)
