from typing import Any, Dict, List

# Definisi JSON Schema Native untuk LangChain / Hermes / Gemini Function Calling
# Sesuai ARCHITECTURE.md Bagian 2 (analyze, scan, monitor)

ANALYZE_SCHEMA: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "analyze_asset",
        "description": (
            "Menjalankan Multi-Timeframe Analysis (MTFA), 3-Layer Regime Filter (ADX, Ranging, King's Filter), "
            "serta menghitung titik Entry, Stop Loss, TP1, TP2, dan RRR secara kuantitatif."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Simbol pasangan aset, misal 'SOL/USDT' atau 'BTC/IDR'.",
                },
                "exchange": {
                    "type": "string",
                    "enum": ["binance", "indodax"],
                    "default": "binance",
                    "description": "Nama bursa kripto sumber data OHLCV.",
                },
                "macro_tf": {
                    "type": "string",
                    "default": "4h",
                    "description": "Timeframe makro untuk identifikasi tren utama (misal '4h', '1d').",
                },
                "micro_tf": {
                    "type": "string",
                    "default": "15m",
                    "description": "Timeframe mikro untuk pemicu eksekusi (misal '15m', '1h').",
                },
                "mode": {
                    "type": "string",
                    "enum": ["FOMO", "SMART_MONEY"],
                    "default": "FOMO",
                    "description": "Mode eksekusi: FOMO (Market Order) atau SMART_MONEY (Limit Retest/Liquidity Sweep).",
                },
            },
            "required": ["symbol"],
        },
    },
}

SCAN_SCHEMA: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "scan_market",
        "description": (
            "Memindai pasar untuk mencari Top 3-5 koin yang mengalami Bollinger Band Squeeze "
            "dan Volume Spike (>3x SMA24) secara bersamaan dengan likuiditas tinggi."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "exchange": {
                    "type": "string",
                    "enum": ["binance", "indodax"],
                    "default": "binance",
                    "description": "Bursa target pemindaian ($1M min vol untuk Binance, Rp 1B untuk Indodax).",
                },
                "symbols": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Daftar pasangan simbol yang akan dipindai.",
                },
                "timeframe": {
                    "type": "string",
                    "default": "1h",
                    "description": "Timeframe pemindaian (default '1h').",
                },
            },
            "required": ["symbols"],
        },
    },
}

MONITOR_SCHEMA: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "monitor_position",
        "description": (
            "Memantau posisi aktif untuk menginstruksikan Auto-Breakeven saat TP1 tercapai "
            "dan menghitung Trailing Stop (High Tertinggi Baru - 2*ATR) menuju TP2."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Simbol pasangan aset yang sedang berjalan.",
                },
                "entry_price": {
                    "type": "number",
                    "description": "Harga Entry posisi saat ini.",
                },
                "stop_loss": {
                    "type": "number",
                    "description": "Harga Stop Loss awal.",
                },
                "tp1": {
                    "type": "number",
                    "description": "Target Take Profit 1 (RRR 1:1).",
                },
                "tp2": {
                    "type": "number",
                    "description": "Target Take Profit 2.",
                },
                "highest_high": {
                    "type": "number",
                    "description": "Harga tertinggi baru yang dicapai sejak entry.",
                },
            },
            "required": ["symbol", "entry_price", "stop_loss", "tp1", "tp2"],
        },
    },
}


def get_hermes_tools() -> List[Dict[str, Any]]:
    """Mengembalikan daftar lengkap skema fungsi untuk integrasi LLM Agent."""
    return [ANALYZE_SCHEMA, SCAN_SCHEMA, MONITOR_SCHEMA]
