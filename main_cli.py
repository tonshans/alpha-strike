# main_cli.py
import argparse
import json
import sys
import ccxt
import pandas as pd
import pandas_ta as ta

import core.indicators as ind_mod
import data.exchange_api as api_mod
from core.logic_matrix import evaluate_decision_matrix
from core.scanner import scan_market
from integrations.hermes_schemas import get_schemas_json
from integrations.llm_formatter import (
    format_as_json,
    format_decision_kv,
    format_scan_kv,
)


def _fetch_df(exchange_id: str, symbol: str, timeframe: str, limit: int = 100) -> pd.DataFrame:
    # Gunakan fungsi di data/exchange_api.py jika tersedia, fallback ke ccxt langsung
    for fn_name in ("fetch_ohlcv_df", "fetch_ohlcv", "get_ohlcv", "fetch_data"):
        fn = getattr(api_mod, fn_name, None)
        if callable(fn):
            res = fn(symbol=symbol, timeframe=timeframe, limit=limit, exchange_id=exchange_id)
            if isinstance(res, pd.DataFrame):
                return res
            if isinstance(res, list) and res:
                return pd.DataFrame(
                    res, columns=["timestamp", "open", "high", "low", "close", "volume"]
                )

    exchange_cls = getattr(ccxt, exchange_id.lower())
    exchange = exchange_cls({"enableRateLimit": True})
    raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    if not raw:
        raise ValueError(f"Data OHLCV kosong untuk {symbol} ({timeframe}) di {exchange_id}")
    return pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])


def _apply_indicators(df: pd.DataFrame) -> pd.DataFrame:
    # Panggil fungsi dari core/indicators.py jika tersedia
    for fn_name in ("calculate_indicators", "add_indicators", "apply_indicators", "compute_indicators"):
        fn = getattr(ind_mod, fn_name, None)
        if callable(fn):
            df = fn(df.copy())
            break
    else:
        df = df.copy()

    # Pastikan seluruh kolom wajib PRD tersedia secara vectorized
    if "EMA_21" not in df.columns:
        df["EMA_21"] = ta.ema(df["close"], length=21)
    if "EMA_50" not in df.columns:
        df["EMA_50"] = ta.ema(df["close"], length=50)
    if "RSI_14" not in df.columns:
        df["RSI_14"] = ta.rsi(df["close"], length=14)
    if "ATR_14" not in df.columns:
        df["ATR_14"] = ta.atr(df["high"], df["low"], df["close"], length=14)
    if "ADX_14" not in df.columns:
        adx_df = ta.adx(df["high"], df["low"], df["close"], length=14)
        adx_col = [c for c in adx_df.columns if c.startswith("ADX_")][0]
        df["ADX_14"] = adx_df[adx_col]
    if "Vol_SMA_20" not in df.columns:
        df["Vol_SMA_20"] = ta.sma(df["volume"], length=20)
    if "Support" not in df.columns:
        df["Support"] = df["low"].rolling(50).min()
    if "Resistance" not in df.columns:
        df["Resistance"] = df["high"].rolling(50).max()

    return df


def _resolve_btc_symbol(symbol: str, exchange_id: str) -> str | None:
    base = symbol.split("/")[0].upper() if "/" in symbol else symbol.upper()
    if base == "BTC":
        return None
    if exchange_id.lower() == "indodax" or symbol.upper().endswith("/IDR"):
        return "BTC/IDR"
    return "BTC/USDT"


def handle_analyze(args: argparse.Namespace) -> int:
    try:
        df_macro = _apply_indicators(
            _fetch_df(args.exchange, args.symbol, args.macro_tf, args.limit)
        )
        df_micro = _apply_indicators(
            _fetch_df(args.exchange, args.symbol, args.micro_tf, args.limit)
        )

        df_btc = None
        btc_symbol = _resolve_btc_symbol(args.symbol, args.exchange)
        if btc_symbol and not args.skip_btc:
            df_btc = _apply_indicators(
                _fetch_df(args.exchange, btc_symbol, args.macro_tf, args.limit)
            )

        decision = evaluate_decision_matrix(
            df_macro=df_macro,
            df_micro=df_micro,
            df_macro_btc=df_btc,
            strategy_mode=args.mode,
        )

        if args.json:
            print(format_as_json({"status": "ok", "symbol": args.symbol, **decision}))
        else:
            print(format_decision_kv(decision, symbol=args.symbol))
        return 0

    except Exception as exc:
        err_payload = {
            "status": "error",
            "command": "analyze",
            "symbol": args.symbol,
            "exchange": args.exchange,
            "error": str(exc),
        }
        if args.json:
            print(format_as_json(err_payload))
        else:
            print(f"STATUS: error\nSYMBOL: {args.symbol}\nERROR_MESSAGE: {exc}")
        return 1


def handle_scan(args: argparse.Namespace) -> int:
    res = scan_market(
        exchange_id=args.exchange,
        timeframe=args.timeframe,
        ohlcv_limit=args.limit,
        top_n=args.top,
    )
    if args.json:
        print(format_as_json(res))
    else:
        print(format_scan_kv(res))
    return 0 if res.get("status") == "ok" else 1


def handle_schemas(args: argparse.Namespace) -> int:
    print(get_schemas_json(indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="alpha-strike",
        description="Alpha-Strike Quantitative Trading Engine CLI",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Subcommand: analyze
    p_analyze = subparsers.add_parser(
        "analyze", help="Jalankan analisis MTFA, Regime Filter, King's Filter, dan kalkulasi RRR"
    )
    p_analyze.add_argument("symbol", type=str, help="Simbol pasangan aset (contoh: SOL/USDT)")
    p_analyze.add_argument(
        "-e", "--exchange", type=str, default="binance", choices=["binance", "indodax"],
        help="Bursa sumber data (default: binance)"
    )
    p_analyze.add_argument(
        "--macro-tf", type=str, default="4h", help="Timeframe Macro (default: 4h)"
    )
    p_analyze.add_argument(
        "--micro-tf", type=str, default="15m", help="Timeframe Micro (default: 15m)"
    )
    p_analyze.add_argument(
        "-m", "--mode", type=str, default="AUTO", choices=["AUTO", "FOMO", "SMART_MONEY"],
        help="Mode strategi eksekusi (default: AUTO)"
    )
    p_analyze.add_argument(
        "-l", "--limit", type=int, default=100,
        help="Jumlah candle OHLCV yang ditarik (default: 100, minimal 50 untuk S&R)"
    )
    p_analyze.add_argument(
        "--skip-btc", action="store_true", help="Lewati pengecekan korelasi BTC (King's Filter)"
    )
    p_analyze.add_argument(
        "--json", action="store_true", help="Cetak output dalam format JSON murni"
    )
    p_analyze.set_defaults(func=handle_analyze)

    # Subcommand: scan
    p_scan = subparsers.add_parser(
        "scan", help="Pindai pasar untuk mencari BB Squeeze (<0.05) dan Volume Spike (>3x SMA24)"
    )
    p_scan.add_argument(
        "-e", "--exchange", type=str, default="binance", choices=["binance", "indodax"],
        help="Bursa target pemindaian (default: binance)"
    )
    p_scan.add_argument(
        "-t", "--timeframe", type=str, default="15m", help="Timeframe pemindaian (default: 15m)"
    )
    p_scan.add_argument(
        "-n", "--top", type=int, default=5, help="Jumlah hasil teratas (default: 5)"
    )
    p_scan.add_argument(
        "-l", "--limit", type=int, default=50, help="Jumlah candle OHLCV per koin (default: 50)"
    )
    p_scan.add_argument(
        "--json", action="store_true", help="Cetak output dalam format JSON murni"
    )
    p_scan.set_defaults(func=handle_scan)

    # Subcommand: schemas
    p_schemas = subparsers.add_parser(
        "schemas", help="Cetak JSON Schema untuk integrasi LLM / Hermes Tool Calling"
    )
    p_schemas.set_defaults(func=handle_schemas)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    if len(sys.argv) == 1:
        # Self-check CLI parser saat dijalankan tanpa argumen
        test_parser = build_parser()
        parsed_a = test_parser.parse_args(["analyze", "SOL/USDT", "--mode", "FOMO", "--json"])
        assert parsed_a.command == "analyze" and parsed_a.symbol == "SOL/USDT"
        parsed_s = test_parser.parse_args(["scan", "--exchange", "indodax", "--top", "3"])
        assert parsed_s.command == "scan" and parsed_s.top == 3
        test_parser.print_help()
        sys.exit(0)

    sys.exit(main())
