"""Pemilih universe dynamic untuk Market Scanner.

Modul ini hanya memakai metadata market dan ticker 24 jam, sehingga tidak ada
request OHLCV sampai daftar pair final ditentukan. Dengan begitu jumlah request
mahal selalu dibatasi oleh ``scanner.universe.max_pairs``.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, TYPE_CHECKING

from core.config import get_config

if TYPE_CHECKING:  # pragma: no cover - hanya untuk type checker
    from data.exchange_api import ExchangeAPI


@dataclass
class UniverseResult:
    """Hasil seleksi universe dynamic."""

    symbols: List[str]
    tickers: Dict[str, Dict[str, Any]]
    stats: Dict[str, Any]


def _as_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _lookup(mapping: Any, keys: Sequence[str], default: Any = None) -> Any:
    """Cari nilai pada mapping dengan key case-insensitive."""
    if not isinstance(mapping, dict):
        return default
    normalized = {str(key).strip().lower(): value for key, value in mapping.items()}
    for key in keys:
        normalized_key = str(key).strip().lower()
        if normalized_key in normalized and normalized[normalized_key] is not None:
            return normalized[normalized_key]
    return default


def _lookup_number(
    mapping: Any,
    keys: Sequence[str],
    default: Optional[float] = None,
) -> Optional[float]:
    return _as_float(_lookup(mapping, keys, default))


def _is_spot_active(market: Dict[str, Any]) -> bool:
    if market.get("active") is False:
        return False
    if market.get("spot") is False:
        return False
    market_type = str(market.get("type") or "").strip().lower()
    if market_type and market_type != "spot":
        return False
    return True


def _is_excluded(
    symbol: str,
    base: str,
    exclude_bases: set[str],
    patterns: List[re.Pattern[str]],
) -> bool:
    if base in exclude_bases:
        return True
    for pattern in patterns:
        if pattern.search(base) or pattern.search(symbol):
            return True
    return False


def select_dynamic_symbols(
    markets: Dict[str, Dict[str, Any]],
    tickers: Dict[str, Dict[str, Any]],
    exchange_id: str,
    config: Optional[Dict[str, Any]] = None,
) -> UniverseResult:
    """
    Memilih pair likuid dari seluruh market exchange.

    Filter berjalan berurutan: metadata market -> quote whitelist -> blacklist
    base -> volume 24 jam -> spread -> deduplikasi base -> hard cap.
    """
    cfg = config if config is not None else get_config()
    exchange_id = str(exchange_id).strip().lower()
    markets = markets if isinstance(markets, dict) else {}
    tickers = tickers if isinstance(tickers, dict) else {}
    scanner_cfg = cfg.get("scanner", {}) if isinstance(cfg, dict) else {}
    universe_cfg = scanner_cfg.get("universe", {}) or {}
    exchange_cfg = cfg.get("exchange", {}) if isinstance(cfg, dict) else {}

    quote_map = universe_cfg.get("quote_currencies", {})
    raw_quotes = _lookup(quote_map, [exchange_id], None)
    if raw_quotes is None:
        raw_quotes = universe_cfg.get("default_quote_currencies")
    allowed_quotes = {quote.upper() for quote in _as_list(raw_quotes)}
    if not allowed_quotes:
        fallback_quote = str(exchange_cfg.get("default_quote_currency", "USDT"))
        allowed_quotes = {fallback_quote.upper()}

    exclude_bases = {
        base.upper() for base in _as_list(universe_cfg.get("exclude_bases"))
    }
    patterns: List[re.Pattern[str]] = []
    for raw_pattern in _as_list(universe_cfg.get("exclude_symbol_patterns")):
        try:
            patterns.append(re.compile(raw_pattern, re.IGNORECASE))
        except re.error:
            continue

    max_pairs_raw = _lookup(
        universe_cfg.get("max_pairs"),
        [exchange_id, "default"],
        30,
    )
    try:
        max_pairs = max(1, int(float(max_pairs_raw)))
    except (TypeError, ValueError):
        max_pairs = 30

    volume_gates = {
        quote: _lookup_number(
            universe_cfg.get("min_quote_volume_24h"),
            [quote, exchange_id, "default"],
            0.0,
        )
        for quote in allowed_quotes
    }
    spread_gates = {
        quote: _lookup_number(
            universe_cfg.get("max_spread_pct"),
            [quote, exchange_id, "default"],
            None,
        )
        for quote in allowed_quotes
    }
    min_range_pct = _lookup_number(
        universe_cfg.get("min_24h_range_pct"),
        ["default"],
        0.0,
    ) or 0.0

    markets_total = len(markets)
    eligible_markets = 0
    with_ticker = 0
    after_volume = 0
    after_spread = 0
    after_range = 0
    candidates: List[Dict[str, Any]] = []

    for market_symbol, market in markets.items():
        if not isinstance(market, dict) or not _is_spot_active(market):
            continue

        symbol = str(market.get("symbol") or market_symbol or "").strip()
        base = str(market.get("base") or "").strip().upper()
        quote = str(market.get("quote") or "").strip().upper()
        if not symbol or not base or not quote:
            continue
        if quote not in allowed_quotes:
            continue
        if _is_excluded(symbol, base, exclude_bases, patterns):
            continue

        eligible_markets += 1

        ticker = tickers.get(symbol)
        if not isinstance(ticker, dict):
            continue
        with_ticker += 1

        last = _as_float(ticker.get("last"))
        if last is None:
            last = _as_float(ticker.get("close"))
        if last is None or last <= 0:
            continue

        quote_volume = _as_float(ticker.get("quoteVolume"))
        if quote_volume is None:
            base_volume = _as_float(ticker.get("baseVolume"))
            if base_volume is not None:
                quote_volume = base_volume * last
        if quote_volume is None or quote_volume <= 0:
            continue

        min_volume = volume_gates.get(quote)
        if min_volume is not None and quote_volume < min_volume:
            continue
        after_volume += 1

        max_spread_pct = spread_gates.get(quote)
        bid = _as_float(ticker.get("bid"))
        ask = _as_float(ticker.get("ask"))
        spread_pct: Optional[float] = None
        if bid is not None and ask is not None and bid > 0 and ask > 0 and ask >= bid:
            mid = (bid + ask) / 2.0
            if mid > 0:
                spread_pct = ((ask - bid) / mid) * 100.0
                if max_spread_pct is not None and spread_pct > max_spread_pct:
                    continue
        after_spread += 1

        if min_range_pct > 0:
            high = _as_float(ticker.get("high"))
            low = _as_float(ticker.get("low"))
            if high is not None and low is not None and high >= low:
                range_pct = ((high - low) / last) * 100.0
                if range_pct < min_range_pct:
                    continue
        after_range += 1

        candidates.append(
            {
                "symbol": symbol,
                "base": base,
                "quote": quote,
                "quote_volume": quote_volume,
                "spread_pct": spread_pct,
                "last": last,
            }
        )

    # Pair dengan base sama hanya diambil yang volume 24 jam-nya tertinggi.
    candidates.sort(key=lambda item: item["quote_volume"], reverse=True)
    unique_candidates: List[Dict[str, Any]] = []
    seen_bases: set[str] = set()
    for candidate in candidates:
        base = candidate["base"]
        if base in seen_bases:
            continue
        seen_bases.add(base)
        unique_candidates.append(candidate)

    selected_candidates = unique_candidates[:max_pairs]
    selected_symbols = [candidate["symbol"] for candidate in selected_candidates]
    selected_tickers = {
        symbol: tickers[symbol]
        for symbol in selected_symbols
        if isinstance(tickers.get(symbol), dict)
    }

    stats: Dict[str, Any] = {
        "scope": "dynamic",
        "exchange": exchange_id,
        "quote_currencies": sorted(allowed_quotes),
        "max_pairs": max_pairs,
        "min_quote_volume_24h": volume_gates,
        "max_spread_pct": spread_gates,
        "markets_total": markets_total,
        "eligible_markets": eligible_markets,
        "with_ticker": with_ticker,
        "after_volume": after_volume,
        "after_spread": after_spread,
        "after_range": after_range,
        "after_dedupe": len(unique_candidates),
        "selected": len(selected_symbols),
    }

    return UniverseResult(
        symbols=selected_symbols,
        tickers=selected_tickers,
        stats=stats,
    )


def build_dynamic_universe(
    api: "ExchangeAPI",
    config: Optional[Dict[str, Any]] = None,
) -> UniverseResult:
    """Ambil market + ticker dari exchange, lalu jalankan seleksi universe."""
    cfg = config if config is not None else get_config()
    markets = api.load_markets()
    if not markets:
        raise ValueError("Metadata market exchange kosong; dynamic universe tidak bisa dibuat.")
    tickers = api.fetch_all_tickers()
    if not tickers:
        raise ValueError("Ticker seluruh market kosong; dynamic universe tidak bisa dibuat.")
    return select_dynamic_symbols(
        markets=markets,
        tickers=tickers,
        exchange_id=api.exchange_id,
        config=cfg,
    )
