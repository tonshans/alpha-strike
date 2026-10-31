import argparse
import sys

from core.config import get_config
from core.logic_matrix import evaluate_mtfa_and_risk
from core.scanner import MarketScanner
from data.exchange_api import ExchangeAPI
from integrations.hermes_schemas import get_hermes_tools
from integrations.llm_formatter import format_analysis_output, format_scanner_output


def build_parser() -> argparse.ArgumentParser:
    cfg = get_config()
    app_cfg = cfg["app"]
    exchange_cfg = cfg["exchange"]
    analyze_cfg = cfg["analyze"]
    scanner_cfg = cfg["scanner"]

    default_exchange = str(exchange_cfg["default"])
    default_execution_mode = str(analyze_cfg["execution_mode"])
    execution_modes = [str(mode) for mode in analyze_cfg["execution_modes"]]

    parser = argparse.ArgumentParser(
        prog=str(app_cfg["name"]),
        description=str(app_cfg["description"]),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Subcommand: analyze
    analyze_parser = subparsers.add_parser("analyze", help="Analisis MTFA & Risk untuk 1 simbol")
    analyze_parser.add_argument("--symbol", "-s", type=str, required=True, help="Contoh: SOL/USDT atau BTC/IDR")
    analyze_parser.add_argument(
        "--exchange",
        "-e",
        type=str,
        default=default_exchange,
        help=f"Exchange ccxt (default dari config: {default_exchange})",
    )
    analyze_parser.add_argument(
        "--macro-tf",
        type=str,
        default=str(analyze_cfg["macro_timeframe"]),
        help=f"Timeframe Macro (default: {analyze_cfg['macro_timeframe']})",
    )
    analyze_parser.add_argument(
        "--micro-tf",
        type=str,
        default=str(analyze_cfg["micro_timeframe"]),
        help=f"Timeframe Micro (default: {analyze_cfg['micro_timeframe']})",
    )
    analyze_parser.add_argument(
        "--mode",
        type=str,
        choices=execution_modes,
        default=default_execution_mode,
        help=f"Mode eksekusi (default: {default_execution_mode})",
    )
    analyze_parser.add_argument(
        "--json",
        action=argparse.BooleanOptionalAction,
        default=bool(analyze_cfg["output_json"]),
        help="Output dalam format JSON (default dari config)",
    )

    # Subcommand: scan
    scan_parser = subparsers.add_parser("scan", help="Pindai koin dengan BB Squeeze + Volume Spike")
    scan_parser.add_argument(
        "--exchange",
        "-e",
        type=str,
        default=default_exchange,
        help=f"Exchange ccxt (default dari config: {default_exchange})",
    )
    scan_parser.add_argument(
        "--timeframe",
        "-t",
        type=str,
        default=str(scanner_cfg["timeframe"]),
        help=f"Timeframe scan (default: {scanner_cfg['timeframe']})",
    )
    scan_parser.add_argument(
        "--symbols",
        nargs="+",
        default=list(scanner_cfg["symbols"]),
        help="Daftar simbol yang akan dipindai (pisahkan dengan spasi)",
    )
    scan_parser.add_argument(
        "--json",
        action=argparse.BooleanOptionalAction,
        default=bool(scanner_cfg["output_json"]),
        help="Output dalam format JSON (default dari config)",
    )

    # Subcommand: schemas
    subparsers.add_parser("schemas", help="Tampilkan JSON Schema untuk Hermes / LangChain Tools")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "schemas":
        import json

        json_indent = int(get_config()["output"]["json_indent"])
        print(json.dumps(get_hermes_tools(), indent=json_indent, ensure_ascii=False))
        return 0

    try:
        api = ExchangeAPI(exchange_id=args.exchange)
    except Exception as exc:
        print(f"[ERROR] Gagal menginisialisasi exchange '{args.exchange}': {exc}", file=sys.stderr)
        return 1

    if args.command == "analyze":
        try:
            data = api.fetch_mtfa_data(
                symbol=args.symbol,
                macro_tf=args.macro_tf,
                micro_tf=args.micro_tf,
            )
            result = evaluate_mtfa_and_risk(
                symbol=args.symbol,
                df_macro=data["macro"],
                df_micro=data["micro"],
                df_btc_macro=data["btc_macro"],
                execution_mode=args.mode,
            )
            print(format_analysis_output(result, as_json=args.json))
            return 0
        except Exception as exc:
            print(f"[ERROR] Gagal menganalisis {args.symbol}: {exc}", file=sys.stderr)
            return 1

    if args.command == "scan":
        try:
            scanner = MarketScanner(api=api)
            results = scanner.scan_market(symbols=args.symbols, timeframe=args.timeframe)
            print(format_scanner_output(results, as_json=args.json))
            return 0
        except Exception as exc:
            print(f"[ERROR] Gagal menjalankan market scanner: {exc}", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
