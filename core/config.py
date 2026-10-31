"""Pemuat konfigurasi terpusat untuk Alpha-Strike Engine.

Seluruh parameter yang dapat diubah pengguna berada di ``config.yaml`` pada
root project. Modul ini membaca file tersebut sekali lalu menyimpannya di cache
agar tidak terjadi I/O berulang pada setiap perhitungan indikator.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional, Union

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.yaml"
CONFIG_PATH_ENV = "ALPHA_STRIKE_CONFIG"

_config_cache: Optional[Dict[str, Any]] = None
_config_path_cache: Optional[Path] = None

PathLike = Union[str, "os.PathLike[str]"]


def _resolve_config_path(path: Optional[PathLike] = None) -> Path:
    """Menentukan path config: argumen > environment variable > config.yaml."""
    if path is None:
        path = os.environ.get(CONFIG_PATH_ENV) or DEFAULT_CONFIG_PATH
    return Path(path).expanduser().resolve()


def load_config(path: Optional[PathLike] = None) -> Dict[str, Any]:
    """Membaca config.yaml dari disk tanpa menggunakan cache."""
    config_path = _resolve_config_path(path)

    if not config_path.exists():
        raise FileNotFoundError(
            f"File konfigurasi tidak ditemukan: {config_path}. "
            "Pastikan config.yaml ada di root project atau set environment "
            f"variable {CONFIG_PATH_ENV}."
        )

    with config_path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)

    if config is None:
        config = {}
    if not isinstance(config, dict):
        raise ValueError(
            f"Format config tidak valid di {config_path}: root harus berupa mapping/dict."
        )
    return config


def get_config(path: Optional[PathLike] = None) -> Dict[str, Any]:
    """Mengembalikan config (di-cache) agar pembacaan file cukup sekali."""
    global _config_cache, _config_path_cache

    config_path = _resolve_config_path(path)
    if _config_cache is None or _config_path_cache != config_path:
        _config_cache = load_config(config_path)
        _config_path_cache = config_path
    return _config_cache


def reload_config(path: Optional[PathLike] = None) -> Dict[str, Any]:
    """Memaksa pembacaan ulang config.yaml (berguna untuk testing)."""
    global _config_cache, _config_path_cache

    _config_cache = None
    _config_path_cache = None
    return get_config(path)


def get(path: str, default: Any = None) -> Any:
    """Mengambil nilai config dengan dot-path, misal ``logic.filters.adx_min``."""
    node: Any = get_config()
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node
