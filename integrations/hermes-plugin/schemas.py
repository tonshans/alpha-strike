"""JSON schemas exposed by the Alpha-Strike Hermes plugin.

Keep the ``name`` of every schema identical to the name passed to
``ctx.register_tool()`` in :mod:`__init__`. The model sees the schema
``description`` fields, so they explain both what the tool returns and the
important limitations (for example that position monitoring is long-only).
"""

ANALYZE_ASSET = {
    "name": "alpha_strike_analyze_asset",
    "description": (
        "Jalankan analisis Multi-Timeframe Analysis (MTFA) Alpha-Strike untuk satu "
        "pasangan aset. Menghitung skor Macro/Micro, filter rezim pasar (ADX, "
        "Ranging, King's Filter BTC), indikator utama, serta rencana eksekusi "
        "(entry, stop loss, TP1, TP2, RRR). Mengembalikan JSON berisi keputusan "
        "final BUY/SELL/HOLD beserta alasannya. Data OHLCV diambil langsung dari "
        "exchange melalui ccxt; pasangan harus tersedia di exchange tersebut."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "symbol": {
                "type": "string",
                "description": "Simbol pasangan aset, misal 'SOL/USDT', 'BTC/IDR', atau 'BTC/USDT:USDT'.",
            },
            "exchange": {
                "type": "string",
                "description": (
                    "Nama exchange ccxt sumber OHLCV, misal 'binance' atau 'indodax'. "
                    "Bila dikosongkan, nilai default dari config.yaml Alpha-Strike dipakai."
                ),
            },
            "macro_tf": {
                "type": "string",
                "description": "Timeframe makro untuk tren utama, misal '4h' atau '1d'. Default: config.yaml.",
            },
            "micro_tf": {
                "type": "string",
                "description": "Timeframe mikro untuk pemicu eksekusi, misal '15m' atau '1h'. Default: config.yaml.",
            },
            "mode": {
                "type": "string",
                "enum": ["FOMO", "SMART_MONEY"],
                "description": (
                    "Mode eksekusi: FOMO (market order saat breakout momentum) atau "
                    "SMART_MONEY (limit order di area support/EMA fast saat pullback). "
                    "Default: config.yaml."
                ),
            },
        },
        "required": ["symbol"],
    },
}

SCAN_MARKET = {
    "name": "alpha_strike_scan_market",
    "description": (
        "Pindai pasar untuk mencari kandidat dengan Bollinger Band Squeeze dan "
        "Volume Spike secara bersamaan, setelah filter likuiditas 24 jam. "
        "Mengembalikan JSON berisi daftar kandidat teratas yang diurutkan "
        "berdasarkan rasio volume spike. Bila 'symbols' dikosongkan, daftar "
        "watchlist default dari config.yaml Alpha-Strike yang dipakai."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "exchange": {
                "type": "string",
                "description": "Nama exchange ccxt, misal 'binance' atau 'indodax'. Default: config.yaml.",
            },
            "symbols": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 50,
                "description": (
                    "Daftar pasangan yang akan dipindai, misal ['BTC/USDT', 'ETH/USDT']. "
                    "Kosongkan untuk memakai watchlist default config.yaml (maksimal 50 simbol)."
                ),
            },
            "timeframe": {
                "type": "string",
                "description": "Timeframe pemindaian, misal '15m', '1h', atau '4h'. Default: config.yaml.",
            },
        },
    },
}

MONITOR_POSITION = {
    "name": "alpha_strike_monitor_position",
    "description": (
        "Pantau posisi LONG yang sedang berjalan memakai harga terbaru dan ATR "
        "dari Alpha-Strike. Menentukan apakah TP1 sudah tersentuh (sinyal "
        "auto-breakeven), menghitung trailing stop, dan memberi instruksi "
        "manajemen posisi menuju TP2. Hanya untuk posisi long/buy; bukan untuk "
        "posisi short."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "symbol": {
                "type": "string",
                "description": "Simbol pasangan aset yang sedang dipantau, misal 'SOL/USDT'.",
            },
            "entry_price": {
                "type": "number",
                "description": "Harga entry rata-rata posisi long.",
            },
            "stop_loss": {
                "type": "number",
                "description": "Harga stop loss awal (harus di bawah entry).",
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
                "description": (
                    "Harga tertinggi yang sudah dicapai sejak entry. Bila "
                    "dikosongkan, dipakai max(harga terbaru, entry_price)."
                ),
            },
            "current_price": {
                "type": "number",
                "description": (
                    "Harga terbaru saat ini. Bila diisi, nilai ini dipakai "
                    "sebagai harga berjalan; bila kosong, close candle terbaru "
                    "dari exchange yang dipakai."
                ),
            },
            "exchange": {
                "type": "string",
                "description": "Exchange ccxt untuk mengambil ATR dan candle terbaru. Default: config.yaml.",
            },
            "timeframe": {
                "type": "string",
                "description": "Timeframe untuk perhitungan ATR, misal '15m'. Default: micro_timeframe config.yaml.",
            },
        },
        "required": ["symbol", "entry_price", "stop_loss", "tp1", "tp2"],
    },
}

ALL_SCHEMAS = [ANALYZE_ASSET, SCAN_MARKET, MONITOR_POSITION]
