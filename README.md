# Alpha-Strike Engine

Alpha-Strike Engine adalah *Quantitative Trading Engine* murni berbasis Python (tanpa GUI/Chart visual) yang mengekstrak data pasar OHLCV menjadi keputusan trading absolut (BUY/SELL/HOLD). Sistem ini menggunakan pendekatan *Multi-Timeframe Analysis* (MTFA), deteksi likuiditas (Smart Money), dan terintegrasi sebagai fungsi API otonom untuk LLM Agent (Hermes/Gemini).

## Fitur Utama
* **Multi-Timeframe Analysis (MTFA)**: Menganalisis kondisi pasar dengan matriks skor pada timeframe Macro dan Micro.
* **Filter Makro & Anti-Whipsaw**: Dilengkapi dengan Market Regime (ADX Filter), Ranging Filter, dan King's Filter (Korelasi BTC).
* **Market Scanner**: Melakukan filter likuiditas, mendeteksi BB Squeeze (volatilitas ditekan), dan Volume Spike.
* **Mode Eksekusi Otonom**: Mendukung *FOMO Mode* (Momentum Breakout) dan *Smart Money Mode* (Liquidity & Retest) dengan Auto-Calculation target untuk SL dan TP berbasis ATR.

## Tech Stack
* **Engine**: Python 3.10+
* **Data Pipeline**: `ccxt` (Fetch OHLCV API)
* **Kalkulasi**: `pandas`, `pandas-ta`
* **Integrasi**: JSON Schema (LangChain/Hermes)

## Struktur Direktori
* `core/`: Modul perhitungan indikator (`indicators.py`), matriks logika MTFA (`logic_matrix.py`), eksekusi filter (`scanner.py`), dan pemuat konfigurasi (`config.py`).
* `data/`: Wrapper API exchange (`exchange_api.py`).
* `integrations/`: Skema definisi JSON (`hermes_schemas.py`), LLM formatter (`llm_formatter.py`), plugin Hermes Agent (`hermes-plugin/`), dan installer `install-hermes-plugin.py`.
* `main_cli.py`: CLI tester manual.
* `config.yaml`: Pusat seluruh parameter engine (indikator, filter, risiko, scanner, exchange).
* `requirements.txt`: Daftar dependensi modul.

## Konfigurasi
Semua parameter yang dapat diubah (periode indikator, ambang filter, pengali ATR, daftar simbol scanner, ambang likuiditas, mode eksekusi, dan lain-lain) berada di `config.yaml`. Setiap parameter memiliki komentar mengenai dampaknya bila nilainya diubah.

```bash
# Setelah mengubah config.yaml, jalankan ulang CLI agar nilai baru terbaca
python main_cli.py analyze --symbol SOL/USDT
```

Untuk memakai file konfigurasi lain tanpa mengubah `config.yaml`:

```bash
ALPHA_STRIKE_CONFIG=/path/ke/config-lain.yaml python main_cli.py scan
```

## Integrasi Hermes Agent

Plugin siap pakai tersedia di `integrations/hermes-plugin/`. Plugin ini
menambahkan tiga tool ke Hermes Agent:

* `alpha_strike_analyze_asset` — analisis MTFA + rencana entry/SL/TP.
* `alpha_strike_scan_market` — scanner BB Squeeze + Volume Spike.
* `alpha_strike_monitor_position` — auto-breakeven dan trailing stop posisi long.

Pasang otomatis (plugin disalin ke `~/.hermes/plugins/alpha-strike/`, lalu
diaktifkan di `plugins.enabled`):

```bash
python integrations/install-hermes-plugin.py
```

Setelah installer selesai, restart Hermes dan coba perintah seperti
`Analisa BTC/USDT dengan Alpha-Strike`. Dokumentasi lengkap, opsi installer,
dan troubleshooting ada di `integrations/hermes-plugin/README.md`.

## Instalasi
```bash
# Clone repository
git clone https://github.com/tonshans/alpha-strike.git
cd alpha-strike

# Install dependencies
pip install -r requirements.txt

# Jalankan tester CLI
python main_cli.py
