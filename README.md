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
* `core/`: Modul perhitungan indikator (`indicators.py`), matriks logika MTFA (`logic_matrix.py`), dan eksekusi filter (`scanner.py`).
* `data/`: Wrapper API exchange (`exchange_api.py`).
* `integrations/`: Skema definisi JSON (`hermes_schemas.py`) dan LLM formatter (`llm_formatter.py`).
* `main_cli.py`: CLI tester manual.
* `requirements.txt`: Daftar dependensi modul.

## Instalasi
```bash
# Clone repository
git clone https://github.com/tonshans/alpha-strike.git
cd alpha-strike

# Install dependencies
pip install -r requirements.txt

# Jalankan tester CLI
python main_cli.py
