import json

ANALYZE_MARKET_SCHEMA = {
    "type": "function",
    "function": {
        "name": "analyze_market",
        "description": (
            "Ekstrak data OHLCV dan jalankan Multi-Timeframe Analysis (MTFA), "
            "Regime Filter, King's Filter (korelasi BTC), serta kalkulasi target Entry/SL/TP1/TP2."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Simbol pasangan aset, contoh: 'SOL/USDT' atau 'BTC/IDR'.",
                },
                "exchange_id": {
                    "type": "string",
                    "enum": ["binance", "indodax"],
                    "default": "binance",
                    "description": "Nama bursa sumber data OHLCV.",
                },
                "macro_tf": {
                    "type": "string",
                    "enum": ["1h", "4h", "1d"],
                    "default": "4h",
                    "description": "Timeframe makro untuk penentuan tren utama dan King's Filter.",
                },
                "micro_tf": {
                    "type": "string",
                    "enum": ["5m", "15m", "30m", "1h"],
                    "default": "15m",
                    "description": "Timeframe mikro untuk pemicu eksekusi dan filter rezim.",
                },
                "strategy_mode": {
                    "type": "string",
                    "enum": ["AUTO", "FOMO", "SMART_MONEY"],
                    "default": "AUTO",
                    "description": "Mode eksekusi: FOMO (Market Breakout), SMART_MONEY (Limit Retest), atau AUTO.",
                },
            },
            "required": ["symbol"],
            "additionalProperties": False,
        },
    },
}

CREATE_SCAN_SCHEDULE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "create_scan_schedule",
        "description": (
            "Jadwalkan pemindaian pasar otomatis untuk mencari koin dengan likuiditas tinggi "
            "yang memenuhi kriteria Bollinger Band Squeeze (< 0.05) dan Volume Spike (> 3x SMA24)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "exchange_id": {
                    "type": "string",
                    "enum": ["binance", "indodax"],
                    "default": "binance",
                    "description": "Bursa target pemindaian ($1M min vol di Binance, Rp 1B di Indodax).",
                },
                "timeframe": {
                    "type": "string",
                    "enum": ["5m", "15m", "1h", "4h"],
                    "default": "15m",
                    "description": "Timeframe evaluasi Squeeze dan Volume Spike.",
                },
                "interval_minutes": {
                    "type": "integer",
                    "minimum": 1,
                    "default": 15,
                    "description": "Interval pengulangan jadwal scan dalam satuan menit.",
                },
                "top_n": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 10,
                    "default": 5,
                    "description": "Jumlah maksimal koin teratas yang dikembalikan.",
                },
            },
            "required": ["exchange_id", "timeframe", "interval_minutes"],
            "additionalProperties": False,
        },
    },
}

ADD_TO_MONITOR_SCHEMA = {
    "type": "function",
    "function": {
        "name": "add_to_monitor",
        "description": (
            "Tambahkan pasangan aset beserta level harga Entry, Stop Loss, TP1 (Auto-Breakeven), "
            "dan TP2 ke dalam pemantauan aktif."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Simbol pasangan aset yang dipantau, contoh: 'ETH/USDT'.",
                },
                "exchange_id": {
                    "type": "string",
                    "enum": ["binance", "indodax"],
                    "default": "binance",
                    "description": "Nama bursa tempat harga dipantau.",
                },
                "strategy_mode": {
                    "type": "string",
                    "enum": ["FOMO", "SMART_MONEY"],
                    "description": "Mode strategi yang digunakan pada posisi ini.",
                },
                "entry_price": {
                    "type": "number",
                    "description": "Harga titik masuk (Market atau Limit).",
                },
                "stop_loss": {
                    "type": "number",
                    "description": "Level Stop Loss (Support - 0.5 * ATR).",
                },
                "tp1": {
                    "type": "number",
                    "description": "Level Take Profit 1 pada RRR 1:1 (pemicu Auto-Breakeven).",
                },
                "tp2": {
                    "type": "number",
                    "description": "Level Take Profit 2 (Resistance - 0.1 * ATR).",
                },
            },
            "required": ["symbol", "strategy_mode", "entry_price", "stop_loss", "tp1", "tp2"],
            "additionalProperties": False,
        },
    },
}

HERMES_TOOLS = [
    ANALYZE_MARKET_SCHEMA,
    CREATE_SCAN_SCHEDULE_SCHEMA,
    ADD_TO_MONITOR_SCHEMA,
]


def get_schemas_json(indent: int = 2) -> str:
    return json.dumps(HERMES_TOOLS, indent=indent)



