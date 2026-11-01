#!/usr/bin/env python3
"""Install the Alpha-Strike plugin into Hermes Agent.

What this script does:

1. Validates the plugin source and its tool schemas.
2. Finds a Python interpreter that can run Alpha-Strike (ccxt/pandas/pandas-ta/PyYAML).
3. Copies (default) or symlinks ``integrations/hermes-plugin`` into
   ``<HERMES_HOME>/plugins/alpha-strike``.
4. Records the Alpha-Strike root/interpreter so the plugin works without manual
   configuration.
5. Enables the plugin through ``hermes plugins enable`` when available, with a
   safe YAML fallback that updates ``plugins.enabled`` in ``config.yaml``.

Examples::

    python integrations/install-hermes-plugin.py
    python integrations/install-hermes-plugin.py --hermes-home ~/.hermes
    python integrations/install-hermes-plugin.py --python .venv/bin/python
    python integrations/install-hermes-plugin.py --symlink --force
    python integrations/install-hermes-plugin.py --no-enable
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_SOURCE = Path(__file__).resolve().parent / "hermes-plugin"
PLUGIN_NAME = "alpha-strike"
PLUGIN_TOOLSET = "alpha_strike"
INSTALL_META_NAME = "alpha-strike-install.json"
DEFAULT_TIMEOUT_SECONDS = 90
REQUIRED_IMPORTS = ("ccxt", "pandas", "pandas_ta", "yaml")


def log(message: str = "") -> None:
    print(message, flush=True)


def fail(message: str, code: int = 1) -> int:
    print(f"[ERROR] {message}", file=sys.stderr, flush=True)
    return code


def _read_manifest(plugin_dir: Path) -> Dict[str, Any]:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("PyYAML tidak tersedia; jalankan `pip install -r requirements.txt`.") from exc

    manifest_path = plugin_dir / "plugin.yaml"
    if not manifest_path.is_file():
        raise RuntimeError(f"plugin.yaml tidak ditemukan di {plugin_dir}.")
    with manifest_path.open("r", encoding="utf-8") as handle:
        manifest = yaml.safe_load(handle)
    if not isinstance(manifest, dict):
        raise RuntimeError("plugin.yaml tidak berisi mapping YAML yang valid.")
    return manifest


def _validate_plugin_source(plugin_dir: Path) -> Dict[str, Any]:
    """Import the plugin with a stub ctx and verify every declared tool."""
    manifest = _read_manifest(plugin_dir)
    provides = [str(item) for item in manifest.get("provides_tools", [])]
    if not provides:
        raise RuntimeError("plugin.yaml tidak mendeklarasikan provides_tools.")

    init_file = plugin_dir / "__init__.py"
    if not init_file.is_file():
        raise RuntimeError(f"__init__.py tidak ditemukan di {plugin_dir}.")

    module_name = "alpha_strike_hermes_plugin_validation"
    spec = importlib.util.spec_from_file_location(
        module_name,
        str(init_file),
        submodule_search_locations=[str(plugin_dir)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Gagal membuat import spec untuk plugin.")
    module = importlib.util.module_from_spec(spec)

    registered: Dict[str, Any] = {}

    class StubContext:
        def register_tool(self, name, toolset, schema, handler, **_kwargs):
            registered[name] = {"toolset": toolset, "schema": schema, "handler": handler}

    previous_module = sys.modules.get(module_name)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
        module.register(StubContext())
    except Exception as exc:  # noqa: BLE001 - installer should report the real failure
        raise RuntimeError(f"Plugin gagal di-import/diregistrasi: {exc}") from exc
    finally:
        if previous_module is None:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = previous_module

    missing = sorted(set(provides) - set(registered))
    extra = sorted(set(registered) - set(provides))
    if missing:
        raise RuntimeError(f"Tool yang dideklarasikan tetapi tidak terdaftar: {', '.join(missing)}")
    if extra:
        raise RuntimeError(f"Tool terdaftar tetapi tidak ada di provides_tools: {', '.join(extra)}")

    for name, entry in registered.items():
        if entry["toolset"] != PLUGIN_TOOLSET:
            raise RuntimeError(f"Tool {name} memakai toolset tak terduga: {entry['toolset']}")
        schema_name = entry["schema"].get("name") if isinstance(entry["schema"], dict) else None
        if schema_name != name:
            raise RuntimeError(f"Schema name '{schema_name}' tidak cocok dengan tool '{name}'.")
        if not callable(entry["handler"]):
            raise RuntimeError(f"Handler untuk {name} tidak callable.")

        # Handlers must always return JSON. Use deliberately invalid parameters
        # so validation never performs a live network request.
        try:
            raw = entry["handler"]({"symbols": [123], "entry_price": -1})
            parsed = json.loads(raw)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Handler {name} gagal saat diuji dengan parameter tidak valid: {exc}") from exc
        if not isinstance(parsed, dict) or parsed.get("ok") is not False:
            raise RuntimeError(
                f"Handler {name} tidak mengembalikan error JSON untuk parameter tidak valid."
            )

    return manifest


def _resolve_hermes_home(raw: Optional[str]) -> Path:
    if raw:
        return Path(raw).expanduser().resolve()
    env_home = os.environ.get("HERMES_HOME", "").strip()
    if env_home:
        return Path(env_home).expanduser().resolve()
    return (Path.home() / ".hermes").resolve()


def _candidate_pythons(root: Path, explicit: Optional[str]) -> List[Path]:
    candidates: List[Optional[str]] = []
    if explicit:
        candidates.append(explicit)
    else:
        candidates.extend(
            [
                os.environ.get("ALPHA_STRIKE_PYTHON"),
                sys.executable,
                str(root / ".venv" / "bin" / "python"),
                str(root / "venv" / "bin" / "python"),
                str(root / ".venv" / "Scripts" / "python.exe"),
                str(root / "venv" / "Scripts" / "python.exe"),
                shutil.which("python3"),
                shutil.which("python"),
            ]
        )

    result: List[Path] = []
    for item in candidates:
        if not item:
            continue
        try:
            # Preserve symlinks so a virtualenv's bin/python keeps its venv
            # site-packages instead of resolving to the system interpreter.
            path = Path(item).expanduser()
            if not path.is_absolute():
                path = path.absolute()
        except (OSError, ValueError):
            continue
        if path not in result:
            result.append(path)
    return result


def _run(
    cmd: Sequence[str],
    *,
    cwd: Path,
    timeout: int = 120,
    env: Optional[Dict[str, str]] = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(cmd),
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env=env,
        shell=False,
    )


def _dependency_error(python: Path, root: Path) -> Optional[str]:
    code = "import " + ", ".join(REQUIRED_IMPORTS) + "; print('ok')"
    try:
        proc = _run([str(python), "-c", code], cwd=root, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"{python}: {exc}"
    if proc.returncode == 0:
        return None
    detail = (proc.stderr or proc.stdout or "import gagal").strip()
    return f"{python}: {detail.splitlines()[-1] if detail else 'import gagal'}"


def _find_python(
    root: Path,
    explicit: Optional[str],
    *,
    install_deps: bool,
    skip_check: bool,
) -> Tuple[Path, bool]:
    candidates = _candidate_pythons(root, explicit)
    existing = [path for path in candidates if path.is_file()]
    if not existing:
        raise RuntimeError("Tidak ada interpreter Python yang dapat dieksekusi.")

    if skip_check:
        return existing[0], False

    errors: List[str] = []
    for path in existing:
        error = _dependency_error(path, root)
        if error is None:
            return path, True
        errors.append(error)

    if explicit:
        raise RuntimeError(
            "Interpreter yang diminta tidak memiliki dependency alpha-strike:\n  "
            + "\n  ".join(errors)
            + "\nJalankan `pip install -r requirements.txt` pada interpreter tersebut."
        )

    if install_deps:
        target = existing[0]
        log(f"[deps] Memasang dependency alpha-strike ke {target} …")
        requirements = root / "requirements.txt"
        proc = _run([str(target), "-m", "pip", "install", "-r", str(requirements)], cwd=root, timeout=900)
        if proc.returncode != 0:
            raise RuntimeError(f"pip install gagal:\n{(proc.stderr or proc.stdout).strip()}")
        error = _dependency_error(target, root)
        if error is not None:
            raise RuntimeError(f"Dependency masih belum lengkap setelah instalasi: {error}")
        return target, True

    raise RuntimeError(
        "Tidak ada Python yang memiliki dependency alpha-strike "
        f"({', '.join(REQUIRED_IMPORTS)}).\n  "
        + "\n  ".join(errors)
        + "\nInstall dulu: `pip install -r requirements.txt`, lalu jalankan ulang installer. "
        "Atau pilih interpreter dengan `--python /path/ke/python`."
    )


def _validate_engine(root: Path, python: Path) -> Dict[str, Any]:
    cli = root / "main_cli.py"
    if not cli.is_file() or not (root / "config.yaml").is_file():
        raise RuntimeError(
            f"{root} bukan root alpha-strike (main_cli.py/config.yaml tidak ditemukan)."
        )

    # Exercise the public CLI without touching the network.
    try:
        proc = _run([str(python), str(cli), "schemas"], cwd=root, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"Gagal menjalankan main_cli.py schemas: {exc}") from exc
    if proc.returncode != 0:
        raise RuntimeError(
            "main_cli.py gagal dijalankan:\n" + (proc.stderr or proc.stdout or "").strip()
        )
    try:
        schemas = json.loads(proc.stdout)
    except ValueError as exc:
        raise RuntimeError(f"Output `main_cli.py schemas` bukan JSON: {proc.stdout[:500]!r}") from exc
    if not isinstance(schemas, list) or not schemas:
        raise RuntimeError("`main_cli.py schemas` tidak mengembalikan daftar tool.")

    bridge = PLUGIN_SOURCE / "_bridge.py"
    try:
        health_proc = _run(
            [str(python), str(bridge), "health", "--root", str(root)],
            cwd=root,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"Gagal menjalankan bridge health: {exc}") from exc
    try:
        health = json.loads(health_proc.stdout)
    except ValueError:
        health = None
    if health_proc.returncode != 0 or not isinstance(health, dict) or not health.get("ok"):
        detail = health_proc.stderr or health_proc.stdout or "bridge health gagal"
        raise RuntimeError(f"Bridge Alpha-Strike gagal: {detail.strip()}")

    return health.get("data", {})


def _remove_destination(destination: Path) -> None:
    if destination.is_symlink() or destination.is_file():
        destination.unlink()
    elif destination.is_dir():
        shutil.rmtree(destination)


def _install_files(source: Path, destination: Path, *, mode: str, force: bool) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)

    if destination.exists() or destination.is_symlink():
        if not force:
            raise RuntimeError(
                f"Plugin sudah ada di {destination}. Gunakan --force untuk menimpanya."
            )
        _remove_destination(destination)

    if mode == "symlink":
        destination.symlink_to(source, target_is_directory=True)
        return

    ignore = shutil.ignore_patterns(
        "__pycache__", "*.pyc", "*.pyo", ".pytest_cache", ".git", ".DS_Store"
    )
    shutil.copytree(source, destination, ignore=ignore)


def _write_install_metadata(
    home: Path,
    destination: Path,
    *,
    root: Path,
    python: Path,
    mode: str,
    timeout_seconds: int,
) -> Path:
    metadata = {
        "plugin": PLUGIN_NAME,
        "version": "1.0.0",
        "alpha_strike_root": str(root),
        "python": str(python),
        "timeout_seconds": timeout_seconds,
        "mode": mode,
        "source": str(PLUGIN_SOURCE),
        "destination": str(destination),
        "installed_at": datetime.now(timezone.utc).isoformat(),
    }
    home.mkdir(parents=True, exist_ok=True)
    meta_path = home / INSTALL_META_NAME
    meta_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # A copy install can also carry metadata locally. A symlink install must not
    # dirty the repository, so only the HERMES_HOME copy is written there.
    if mode == "copy":
        local_meta = destination / INSTALL_META_NAME
        try:
            local_meta.write_text(
                json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
        except OSError:
            pass
    return meta_path


def _enable_with_hermes_cli(home: Path) -> Optional[Tuple[int, str, str]]:
    hermes = shutil.which("hermes")
    if not hermes:
        return None
    env = os.environ.copy()
    env["HERMES_HOME"] = str(home)
    try:
        proc = subprocess.run(
            [hermes, "plugins", "enable", PLUGIN_NAME],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=240,
            env=env,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return (1, "", str(exc))
    return (proc.returncode, proc.stdout or "", proc.stderr or "")


def _enable_in_config(home: Path) -> Path:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError(
            "PyYAML tidak tersedia untuk memperbarui config.yaml. "
            "Jalankan `hermes plugins enable alpha-strike` secara manual."
        ) from exc

    config_path = home / "config.yaml"
    existing: Dict[str, Any] = {}
    if config_path.is_file():
        text = config_path.read_text(encoding="utf-8")
        if text.strip():
            try:
                loaded = yaml.safe_load(text)
            except yaml.YAMLError as exc:
                raise RuntimeError(
                    f"config.yaml tidak dapat di-parse: {exc}. "
                    "Perbaiki file tersebut atau jalankan `hermes plugins enable alpha-strike`."
                ) from exc
            if loaded is None:
                loaded = {}
            if not isinstance(loaded, dict):
                raise RuntimeError("Root config.yaml harus berupa mapping/dict.")
            existing = loaded

    plugins = existing.get("plugins")
    if plugins is None:
        plugins = {}
        existing["plugins"] = plugins
    if not isinstance(plugins, dict):
        raise RuntimeError("Bagian `plugins` di config.yaml harus berupa mapping/dict.")

    enabled = plugins.get("enabled")
    if not isinstance(enabled, list):
        enabled = []
    enabled = [str(item) for item in enabled]
    if PLUGIN_NAME not in enabled:
        enabled.append(PLUGIN_NAME)
    plugins["enabled"] = enabled

    disabled = plugins.get("disabled")
    if isinstance(disabled, list):
        filtered = [item for item in disabled if str(item) != PLUGIN_NAME]
        if filtered:
            plugins["disabled"] = filtered
        else:
            plugins.pop("disabled", None)

    # Mirror what `hermes plugins enable` does for users who saved explicit
    # platform toolset selections: add our toolset only to lists that already
    # exist, never seed a new list (that would strip built-in tools).
    import ast

    platform_toolsets = existing.get("platform_toolsets")
    if isinstance(platform_toolsets, dict):
        for platform, raw in list(platform_toolsets.items()):
            values = None
            if isinstance(raw, list):
                values = [str(item) for item in raw]
            elif isinstance(raw, str) and raw.strip().startswith("["):
                try:
                    parsed = ast.literal_eval(raw.strip())
                except (ValueError, SyntaxError):
                    parsed = None
                if isinstance(parsed, list):
                    values = [str(item) for item in parsed]
            if values is not None and PLUGIN_TOOLSET not in values:
                values.append(PLUGIN_TOOLSET)
                platform_toolsets[platform] = values

    config_path.parent.mkdir(parents=True, exist_ok=True)
    if config_path.is_file():
        backup = config_path.with_name(f"config.yaml.bak-{int(time.time())}")
        shutil.copy2(config_path, backup)
        log(f"[config] Backup config lama: {backup}")

    rendered = yaml.safe_dump(existing, sort_keys=False, allow_unicode=True)
    tmp_path = config_path.with_name(config_path.name + ".tmp")
    tmp_path.write_text(rendered, encoding="utf-8")
    os.replace(tmp_path, config_path)
    return config_path


def _config_has_plugin(home: Path) -> bool:
    try:
        import yaml
    except ImportError:
        return False
    config_path = home / "config.yaml"
    if not config_path.is_file():
        return False
    try:
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        enabled = (loaded.get("plugins") or {}).get("enabled") or []
        return PLUGIN_NAME in [str(item) for item in enabled]
    except Exception:
        return False


def _enable_plugin(home: Path, *, use_cli: bool, allow_config_fallback: bool) -> str:
    if use_cli:
        result = _enable_with_hermes_cli(home)
        if result is not None:
            code, stdout, stderr = result
            if code == 0:
                if _config_has_plugin(home):
                    return "hermes-cli"
                log(
                    "[warn] `hermes plugins enable` selesai tetapi plugins.enabled "
                    "belum memuat alpha-strike; memakai fallback config.yaml."
                )
            else:
                log(
                    "[warn] `hermes plugins enable` gagal; mencoba update config.yaml langsung.\n"
                    f"       {(stderr or stdout).strip()[:1000]}"
                )
        else:
            log("[info] CLI `hermes` tidak ditemukan; mengaktifkan lewat config.yaml.")

    if not allow_config_fallback:
        raise RuntimeError("Plugin terpasang tetapi belum diaktifkan (--no-config-fallback).")

    _enable_in_config(home)
    return "config-yaml"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="install-hermes-plugin.py",
        description="Pasang plugin Alpha-Strike ke Hermes Agent secara otomatis.",
    )
    parser.add_argument(
        "--hermes-home",
        default=None,
        help="Lokasi HERMES_HOME (default: $HERMES_HOME atau ~/.hermes).",
    )
    parser.add_argument(
        "--alpha-root",
        default=str(PROJECT_ROOT),
        help="Root repository alpha-strike (default: folder induk integrations/).",
    )
    parser.add_argument(
        "--python",
        default=None,
        help="Interpreter Python yang punya dependency alpha-strike. Default: auto-detect.",
    )
    parser.add_argument(
        "--symlink",
        action="store_true",
        help="Pasang sebagai symlink ke integrations/hermes-plugin (untuk development).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Timpakan instalasi plugin yang sudah ada.",
    )
    parser.add_argument(
        "--no-enable",
        action="store_true",
        help="Salin plugin tetapi jangan tambahkan ke plugins.enabled.",
    )
    parser.add_argument(
        "--no-hermes-cli",
        action="store_true",
        help="Jangan panggil `hermes plugins enable`; update config.yaml langsung.",
    )
    parser.add_argument(
        "--no-config-fallback",
        action="store_true",
        help="Gagal jika `hermes plugins enable` tidak tersedia/gagal.",
    )
    parser.add_argument(
        "--install-deps",
        action="store_true",
        help="Jalankan `pip install -r requirements.txt` bila dependency belum lengkap.",
    )
    parser.add_argument(
        "--skip-dependency-check",
        action="store_true",
        help="Lewati validasi dependency/engine (hanya untuk instalasi darurat).",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"Timeout tool dalam detik (default: {DEFAULT_TIMEOUT_SECONDS}).",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    root = Path(args.alpha_root).expanduser().resolve()
    home = _resolve_hermes_home(args.hermes_home)
    destination = home / "plugins" / PLUGIN_NAME
    timeout_seconds = max(5, min(int(args.timeout), 600))

    log("=" * 68)
    log(" Alpha-Strike → Hermes Agent plugin installer")
    log("=" * 68)
    log(f"Repo alpha-strike : {root}")
    log(f"HERMES_HOME       : {home}")
    log(f"Tujuan plugin     : {destination}")
    log(f"Mode              : {'symlink' if args.symlink else 'copy'}")
    log("")

    try:
        manifest = _validate_plugin_source(PLUGIN_SOURCE)
        log(f"[ok] Plugin source valid: {manifest.get('name')} v{manifest.get('version')}")

        python, checked = _find_python(
            root,
            args.python,
            install_deps=bool(args.install_deps),
            skip_check=bool(args.skip_dependency_check),
        )
        log(f"[ok] Python engine: {python}")

        if checked:
            health = _validate_engine(root, python)
            deps = health.get("dependencies", {})
            dep_text = ", ".join(f"{name} {version}" for name, version in deps.items())
            log(f"[ok] Engine sehat: {dep_text}")
        else:
            log("[warn] Validasi dependency/engine dilewati (--skip-dependency-check).")

        _install_files(
            PLUGIN_SOURCE,
            destination,
            mode="symlink" if args.symlink else "copy",
            force=bool(args.force),
        )
        log(f"[ok] Plugin dipasang di {destination}")

        meta_path = _write_install_metadata(
            home,
            destination,
            root=root,
            python=python,
            mode="symlink" if args.symlink else "copy",
            timeout_seconds=timeout_seconds,
        )
        log(f"[ok] Metadata instalasi: {meta_path}")

        if args.no_enable:
            log("[info] --no-enable dipakai; plugin belum diaktifkan.")
            enabled_by = None
        else:
            enabled_by = _enable_plugin(
                home,
                use_cli=not args.no_hermes_cli,
                allow_config_fallback=not args.no_config_fallback,
            )
            log(f"[ok] Plugin diaktifkan lewat: {enabled_by}")
            if enabled_by == "config-yaml" and not _config_has_plugin(home):
                raise RuntimeError(
                    "Plugin terpasang, tetapi plugins.enabled belum terverifikasi. "
                    "Jalankan `hermes plugins enable alpha-strike`."
                )

    except Exception as exc:  # noqa: BLE001 - CLI reports a concise failure
        return fail(str(exc))

    log("")
    log("=" * 68)
    log(" Selesai.")
    log("=" * 68)
    log("Langkah berikutnya:")
    log("  1. Restart Hermes (tutup lalu jalankan `hermes` kembali).")
    log("  2. Cek plugin : hermes plugins list")
    log("  3. Coba di chat: \"Analisa BTC/USDT dengan Alpha-Strike\"")
    log("")
    log("Tool yang tersedia:")
    for tool in manifest.get("provides_tools", []):
        log(f"  - {tool}")
    log("")
    log("Jika Hermes tidak menemukan repo alpha-strike, set manual:")
    log(
        "  hermes config set plugins.entries.alpha-strike.settings.alpha_strike_root "
        f"{root}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
