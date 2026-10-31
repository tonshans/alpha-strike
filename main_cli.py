import argparse
import sys
from core.logic_matrix import evaluate_mtfa_and_risk
from core.scanner import MarketScanner
from data.exchange_api import ExchangeAPI
from integrations.hermes_schemas import get_hermes_tools
from integrations.llm_formatter import format_analysis_output, format_scanner_output

DEFAULT_SCAN_SYMBOLS = [
    "BTC/USDT",
    "ETH/USDT",
    "SOL/USDT",
    "BNB/USDT",
    "XRP/USDT",
    "ADA/USDT",
    "DOGE/USDT",
    "AVAX/USDT",
    "LINK/USDT",
    "SUI/USDT",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="alpha-strike",
        description="Alpha-Strike Quantitative Trading Engine CLI (MTFA + Smart Money + Scanner)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Subcommand: analyze
    analyze_parser = subparsers.add_parser("analyze", help="Analisis MTFA & Risk untuk 1 simbol")
    analyze_parser.add_argument("--symbol", "-s", type=str, required=True, help="Contoh: SOL/USDT atau BTC/IDR")
    analyze_parser.add_argument("--exchange", "-e", type=str, default="binance", help="binance atau indodax")
    analyze_parser.add_argument("--macro-tf", type=str, default="4h", help="Timeframe Macro (default: 4h)")
    analyze_parser.add_argument("--micro-tf", type=str, default="15m", help="Timeframe Micro (default: 15m)")
    analyze_parser.add_argument(
        "--mode",
        type=str,
        choices=["FOMO", "SMART_MONEY"],
        default="FOMO",
        help="Mode eksekusi: FOMO atau SMART_MONEY",
    )
    analyze_parser.add_argument("--json", action="store_true", help="Output dalam format JSON")

    # Subcommand: scan
    scan_parser = subparsers.add_parser("scan", help="Pindai koin dengan BB Squeeze + Volume Spike")
    scan_parser.add_argument("--exchange", "-e", type=str, default="binance", help="binance atau indodax")
    scan_parser.add_argument("--timeframe", "-t", type=str, default="1h", help="Timeframe scan (default: 1h)")
    scan_parser.add_argument(
        "--symbols",
        nargs="+",
        default=DEFAULT_SCAN_SYMBOLS,
        help="Daftar simbol yang akan dipindai (pisahkan dengan spasi)",
    )
    scan_parser.add_argument("--json", action="store_true", help="Output dalam format JSON")

    # Subcommand: schemas
    subparsers.add_parser("schemas", help="Tampilkan JSON Schema untuk Hermes / LangChain Tools")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "schemas":
        import json
        print(json.dumps(get_hermes_tools(), indent=2, ensure_ascii=False))
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
                include_btc_macro=True,
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
