# Alpha-Strike Plugin for Hermes Agent

Plugin ini membuat [Hermes Agent](https://github.com/NousResearch/hermes-agent)
bisa memanggil engine **Alpha-Strike** untuk menganalisis market kripto.

Plugin hanya memakai standard library Python. Semua pekerjaan berat
(`ccxt`, `pandas`, `pandas-ta`) dijalankan oleh interpreter Alpha-Strike
terpisah, sehingga virtualenv Hermes tidak perlu diisi dependency trading.

## Instalasi otomatis

Dari root repository `alpha-strike`:

```bash
python integrations/install-hermes-plugin.py
```

Installer akan:

1. Memvalidasi `plugin.yaml`, schema, dan handler tanpa melakukan request jaringan.
2. Mencari Python yang memiliki dependency Alpha-Strike.
3. Menyalin plugin ke `<HERMES_HOME>/plugins/alpha-strike/`
   (default `~/.hermes/plugins/alpha-strike/`).
4. Menyimpan lokasi repo + interpreter ke
   `<HERMES_HOME>/alpha-strike-install.json`.
5. Mengaktifkan plugin lewat `hermes plugins enable alpha-strike`
   (fallback: memperbarui `plugins.enabled` di `config.yaml`).

Setelah itu restart Hermes.

### Opsi installer

```bash
# Lokasi Hermes lain
python integrations/install-hermes-plugin.py --hermes-home /opt/hermes

# Pilih interpreter engine secara eksplisit
python integrations/install-hermes-plugin.py --python .venv/bin/python

# Development: symlink ke repo, bukan copy
python integrations/install-hermes-plugin.py --symlink --force

# Hanya pasang, jangan aktifkan
python integrations/install-hermes-plugin.py --no-enable

# Pasang dependency otomatis bila belum ada
python integrations/install-hermes-plugin.py --install-deps
```

Lihat semua opsi:

```bash
python integrations/install-hermes-plugin.py --help
```

## Tool yang tersedia

Setelah plugin aktif, tool muncul di toolset `alpha_strike`:

| Tool | Fungsi |
| --- | --- |
| `alpha_strike_analyze_asset` | MTFA + filter ADX/Ranging/King's Filter + rencana entry/SL/TP1/TP2/RRR untuk satu simbol. |
| `alpha_strike_scan_market` | Scanner BB Squeeze + Volume Spike dengan filter likuiditas 24 jam. Default watchlist; `all: true` untuk universe dynamic. |
| `alpha_strike_monitor_position` | Pantau posisi long: auto-breakeven setelah TP1, trailing stop ATR, dan target TP2. |

Contoh perintah di chat Hermes:

```text
Analisa BTC/USDT dengan Alpha-Strike, mode SMART_MONEY.
Pindai watchlist Indodax timeframe 1h untuk koin dengan BB Squeeze + volume spike.
Pindai seluruh market Binance (dynamic) timeframe 1h dengan Alpha-Strike.
Pantau posisi long SOL/USDT: entry 180, SL 172, TP1 190, TP2 205, high 196.
```

Semua tool mengembalikan JSON:

```json
{
  "ok": true,
  "tool": "alpha_strike_analyze_asset",
  "data": { "...": "..." },
  "meta": { "source": "alpha-strike", "duration_ms": 1234 }
}
```

Jika gagal, hasilnya tetap JSON dan tidak melempar exception:

```json
{
  "ok": false,
  "tool": "alpha_strike_analyze_asset",
  "error": "pesan yang bisa dibaca model"
}
```

## Konfigurasi

Nilai default diambil dari `config.yaml` Alpha-Strike. Pengaturan plugin bisa
diubah lewat Hermes:

```bash
hermes config set plugins.entries.alpha-strike.settings.alpha_strike_root /path/ke/alpha-strike
hermes config set plugins.entries.alpha-strike.settings.alpha_strike_python /path/ke/alpha-strike/.venv/bin/python
hermes config set plugins.entries.alpha-strike.settings.timeout_seconds 120
```

Urutan pencarian lokasi engine:

1. Setting plugin `alpha_strike_root`
2. `ALPHA_STRIKE_HOME` atau `ALPHA_STRIKE_ROOT`
3. Metadata installer (`<HERMES_HOME>/alpha-strike-install.json`)
4. Parent directory plugin (berguna untuk instalasi symlink)
5. Current working directory dan parent-nya

Urutan pencarian interpreter:

1. Setting plugin `alpha_strike_python`
2. `ALPHA_STRIKE_PYTHON`
3. Metadata installer
4. `<root>/.venv/bin/python` atau `<root>/venv/bin/python`
5. Interpreter Hermes saat ini

## Troubleshooting

### Plugin tidak muncul di `hermes plugins list`

Pastikan direktori tujuan berisi `plugin.yaml` dan `__init__.py`:

```bash
ls ~/.hermes/plugins/alpha-strike
hermes plugins enable alpha-strike
```

Lalu restart Hermes.

### Tool mengembalikan error "Folder alpha-strike tidak ditemukan"

Set lokasi repo secara eksplisit:

```bash
python integrations/install-hermes-plugin.py --force
# atau
hermes config set plugins.entries.alpha-strike.settings.alpha_strike_root /path/ke/alpha-strike
```

### Tool mengembalikan error dependency (`ccxt`, `pandas`, `pandas_ta`)

Interpreter yang dipilih belum punya dependency. Install di interpreter itu:

```bash
/path/ke/python -m pip install -r requirements.txt
python integrations/install-hermes-plugin.py --python /path/ke/python --force
```

### Cek manual engine + bridge

```bash
python main_cli.py schemas
python integrations/hermes-plugin/_bridge.py health --root "$PWD"
```

### Debug bridge monitor

```bash
ALPHA_STRIKE_BRIDGE_DEBUG=1 \
  python integrations/hermes-plugin/_bridge.py monitor \
  --root "$PWD" --symbol SOL/USDT \
  --entry-price 180 --stop-loss 172 --tp1 190 --tp2 205
```

## Uninstall

```bash
hermes plugins remove alpha-strike
rm -f ~/.hermes/alpha-strike-install.json
```

Atau hapus manual:

```bash
rm -rf ~/.hermes/plugins/alpha-strike
# lalu hapus "alpha-strike" dari plugins.enabled di ~/.hermes/config.yaml
```
