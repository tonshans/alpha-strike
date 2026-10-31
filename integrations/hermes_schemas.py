from typing import Any, Dict, List

from core.config import get_config

# Definisi JSON Schema Native untuk LangChain / Hermes / Gemini Function Calling.
# Nilai default, enum, dan angka pada deskripsi dibaca dari config.yaml agar
# schema selalu sinkron dengan konfigurasi engine.

_CFG = get_config()
_EXCHANGE_CFG = _CFG["exchange"]
_ANALYZE_CFG = _CFG["analyze"]
_SCANNER_CFG = _CFG["scanner"]
_LOGIC_CFG = _CFG["logic"]

_EXCHANGE_ENUM = [str(exchange) for exchange in _EXCHANGE_CFG["supported"]]
_MODE_ENUM = [str(mode) for mode in _ANALYZE_CFG["execution_modes"]]
_VOLUME_SPIKE_MULTIPLIER = float(_SCANNER_CFG["volume_spike_multiplier"])
_SCANNER_SMA_LENGTH = int(_CFG["indicators"]["volume_sma"]["scanner"])
_TOP_N_MIN = int(_SCANNER_CFG["top_n_min"])
_TOP_N_MAX = int(_SCANNER_CFG["top_n_max"])
_BINANCE_LIQUIDITY = float(_SCANNER_CFG["liquidity_threshold"]["binance"])
_INDODAX_LIQUIDITY = float(_SCANNER_CFG["liquidity_threshold"]["indodax"])
_TRAILING_ATR_MULTIPLIER = float(_LOGIC_CFG["risk"]["trailing_stop_atr_multiplier"])

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
                    "enum": _EXCHANGE_ENUM,
                    "default": str(_EXCHANGE_CFG["default"]),
                    "description": "Nama bursa kripto sumber data OHLCV.",
                },
                "macro_tf": {
                    "type": "string",
                    "default": str(_ANALYZE_CFG["macro_timeframe"]),
                    "description": "Timeframe makro untuk identifikasi tren utama (misal '4h', '1d').",
                },
                "micro_tf": {
                    "type": "string",
                    "default": str(_ANALYZE_CFG["micro_timeframe"]),
                    "description": "Timeframe mikro untuk pemicu eksekusi (misal '15m', '1h').",
                },
                "mode": {
                    "type": "string",
                    "enum": _MODE_ENUM,
                    "default": str(_ANALYZE_CFG["execution_mode"]),
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
            f"Memindai pasar untuk mencari Top {_TOP_N_MIN}-{_TOP_N_MAX} koin yang mengalami "
            f"Bollinger Band Squeeze dan Volume Spike (>{_VOLUME_SPIKE_MULTIPLIER:g}x "
            f"SMA{_SCANNER_SMA_LENGTH}) secara bersamaan dengan likuiditas tinggi."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "exchange": {
                    "type": "string",
                    "enum": _EXCHANGE_ENUM,
                    "default": str(_EXCHANGE_CFG["default"]),
                    "description": (
                        "Bursa target pemindaian "
                        f"(min vol 24 jam: {_BINANCE_LIQUIDITY:,.0f} untuk Binance, "
                        f"{_INDODAX_LIQUIDITY:,.0f} untuk Indodax)."
                    ),
                },
                "symbols": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Daftar pasangan simbol yang akan dipindai.",
                },
                "timeframe": {
                    "type": "string",
                    "default": str(_SCANNER_CFG["timeframe"]),
                    "description": f"Timeframe pemindaian (default '{_SCANNER_CFG['timeframe']}').",
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
            f"dan menghitung Trailing Stop (High Tertinggi Baru - "
            f"{_TRAILING_ATR_MULTIPLIER:g}*ATR) menuju TP2."
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
                    "description": "Target Take Profit 1.",
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
