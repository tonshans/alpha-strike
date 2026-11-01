"""Subprocess client used by the Hermes Alpha-Strike plugin.

The plugin itself deliberately imports only the Python standard library. All
market-analysis work happens in the Alpha-Strike interpreter (the same one used
for ``main_cli.py``), which keeps Hermes' virtualenv isolated from ccxt/pandas
and makes dependency problems easy to diagnose.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

PLUGIN_DIR = Path(__file__).resolve().parent
PLUGIN_ID = "alpha-strike"
INSTALL_META_NAME = "alpha-strike-install.json"
DEFAULT_TIMEOUT_SECONDS = 90
MIN_TIMEOUT_SECONDS = 5
MAX_TIMEOUT_SECONDS = 600


class AlphaStrikeError(RuntimeError):
    """Raised when Alpha-Strike cannot be located or a command fails."""


def _as_optional_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _setting(ctx: Any, key: str, default: Any = None) -> Any:
    """Read a plugin setting without letting a host-side error break a tool."""
    try:
        value = ctx.get_config(key, default=None)
    except Exception:
        value = None
    if value is None:
        return default
    if isinstance(value, str) and not value.strip():
        return default
    return value


def _read_install_meta() -> Dict[str, Any]:
    """Read installer metadata from the plugin dir and the active Hermes home."""
    candidates: List[Path] = [PLUGIN_DIR / INSTALL_META_NAME, PLUGIN_DIR / "install.json"]

    hermes_home = os.environ.get("HERMES_HOME", "").strip()
    if hermes_home:
        candidates.append(Path(hermes_home).expanduser() / INSTALL_META_NAME)
    else:
        candidates.append(Path.home() / ".hermes" / INSTALL_META_NAME)

    for path in candidates:
        try:
            if not path.is_file():
                continue
            with path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                return data
        except (OSError, ValueError, TypeError):
            continue
    return {}


def _is_alpha_root(path: Path) -> bool:
    try:
        return (path / "main_cli.py").is_file() and (path / "config.yaml").is_file()
    except OSError:
        return False


def _candidate_roots(ctx: Any, meta: Dict[str, Any]) -> List[Path]:
    raw: List[Any] = [
        _setting(ctx, "alpha_strike_root"),
        os.environ.get("ALPHA_STRIKE_HOME"),
        os.environ.get("ALPHA_STRIKE_ROOT"),
        meta.get("alpha_strike_root"),
    ]

    # A symlink install resolves back into the repository, so its parents are
    # useful candidates. A copy install simply won't match these.
    try:
        raw.extend(PLUGIN_DIR.parents)
    except Exception:
        pass

    # Also allow launching Hermes from inside the alpha-strike checkout.
    try:
        raw.extend([Path.cwd(), *Path.cwd().parents])
    except Exception:
        pass

    roots: List[Path] = []
    for item in raw:
        text = _as_optional_str(item)
        if not text:
            continue
        try:
            path = Path(text).expanduser().resolve()
        except (OSError, ValueError):
            continue
        if path not in roots:
            roots.append(path)
    return roots


def resolve_root(ctx: Any) -> Path:
    meta = _read_install_meta()
    for path in _candidate_roots(ctx, meta):
        if _is_alpha_root(path):
            return path

    raise AlphaStrikeError(
        "Folder alpha-strike tidak ditemukan. Jalankan installer "
        "`python integrations/install-hermes-plugin.py` atau set lokasi repo lewat "
        "`hermes config set plugins.entries.alpha-strike.settings.alpha_strike_root "
        "/path/ke/alpha-strike` (atau environment variable ALPHA_STRIKE_HOME)."
    )


def _python_candidates(ctx: Any, root: Path, meta: Dict[str, Any]) -> List[Path]:
    raw: List[Any] = [
        _setting(ctx, "alpha_strike_python"),
        os.environ.get("ALPHA_STRIKE_PYTHON"),
        meta.get("python"),
    ]
    raw.extend(
        [
            root / ".venv" / "bin" / "python",
            root / "venv" / "bin" / "python",
            root / ".venv" / "Scripts" / "python.exe",
            root / "venv" / "Scripts" / "python.exe",
            Path(sys.executable),
        ]
    )

    candidates: List[Path] = []
    for item in raw:
        text = _as_optional_str(item)
        if not text:
            continue
        try:
            # Do NOT resolve symlinks here: a venv's bin/python is commonly a
            # symlink, and resolving it would drop the venv's site-packages.
            path = Path(text).expanduser()
            if not path.is_absolute():
                path = path.absolute()
        except (OSError, ValueError):
            continue
        if path not in candidates:
            candidates.append(path)
    return candidates


def resolve_python(ctx: Any, root: Path) -> Path:
    meta = _read_install_meta()
    for path in _python_candidates(ctx, root, meta):
        try:
            if path.is_file() and os.access(str(path), os.X_OK):
                return path
        except OSError:
            continue

    raise AlphaStrikeError(
        "Interpreter Python untuk alpha-strike tidak ditemukan. Set lewat "
        "`hermes config set plugins.entries.alpha-strike.settings.alpha_strike_python "
        "/path/ke/python` atau environment variable ALPHA_STRIKE_PYTHON."
    )


def resolve_timeout(ctx: Any) -> int:
    meta = _read_install_meta()
    raw = _setting(ctx, "timeout_seconds", meta.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS))
    try:
        value = int(float(raw))
    except (TypeError, ValueError):
        value = DEFAULT_TIMEOUT_SECONDS
    return max(MIN_TIMEOUT_SECONDS, min(value, MAX_TIMEOUT_SECONDS))


def _tail(text: str, limit: int = 4000) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return "…" + text[-limit:]


def _parse_json(stdout: str, tool: str) -> Dict[str, Any]:
    text = (stdout or "").strip()
    if not text:
        raise AlphaStrikeError(f"{tool} tidak mengembalikan output apa pun.")

    try:
        parsed = json.loads(text)
    except ValueError:
        # Be tolerant of a leading warning/log line: take the outermost JSON object.
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end <= start:
            raise AlphaStrikeError(
                f"Output {tool} bukan JSON yang valid: {_tail(text, 1200)}"
            )
        try:
            parsed = json.loads(text[start : end + 1])
        except ValueError as exc:
            raise AlphaStrikeError(
                f"Gagal mem-parsing JSON dari {tool}: {exc}. Output: {_tail(text, 1200)}"
            ) from exc

    if not isinstance(parsed, dict):
        raise AlphaStrikeError(f"{tool} mengembalikan JSON non-object.")
    return parsed


def _run(
    cmd: Sequence[str],
    *,
    cwd: Path,
    timeout: int,
    tool: str,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    started = time.monotonic()
    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")

    try:
        completed = subprocess.run(
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
    except subprocess.TimeoutExpired as exc:
        raise AlphaStrikeError(
            f"{tool} melewati batas waktu {timeout} detik. "
            "Coba lagi, naikkan timeout_seconds, atau pakai timeframe/symbol yang lebih ringan."
        ) from exc
    except OSError as exc:
        raise AlphaStrikeError(f"Gagal menjalankan {tool}: {exc}") from exc

    duration_ms = int((time.monotonic() - started) * 1000)
    if completed.returncode != 0:
        stderr = _tail(completed.stderr)
        stdout = _tail(completed.stdout)
        detail = stderr or stdout or "tanpa detail"
        raise AlphaStrikeError(f"{tool} gagal (exit {completed.returncode}): {detail}")

    payload = _parse_json(completed.stdout, tool)
    meta = {
        "source": "alpha-strike",
        "duration_ms": duration_ms,
        "timeout_seconds": timeout,
    }
    stderr_warning = _tail(completed.stderr, 1000)
    if stderr_warning:
        meta["stderr"] = stderr_warning
    return payload, meta


def run_cli(ctx: Any, args: Sequence[str], *, tool: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Run ``main_cli.py`` with the Alpha-Strike interpreter and parse JSON."""
    root = resolve_root(ctx)
    python = resolve_python(ctx, root)
    cli = root / "main_cli.py"
    if not cli.is_file():
        raise AlphaStrikeError(f"main_cli.py tidak ditemukan di {root}.")

    cmd = [str(python), str(cli), *[str(arg) for arg in args]]
    return _run(cmd, cwd=root, timeout=resolve_timeout(ctx), tool=tool)


def run_bridge(
    ctx: Any, args: Sequence[str], *, tool: str
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Run the bundled bridge script (used for monitoring and diagnostics)."""
    root = resolve_root(ctx)
    python = resolve_python(ctx, root)
    bridge = PLUGIN_DIR / "_bridge.py"
    if not bridge.is_file():
        raise AlphaStrikeError(f"File bridge plugin tidak ditemukan: {bridge}")

    cmd = [str(python), str(bridge), *[str(arg) for arg in args]]
    return _run(cmd, cwd=root, timeout=resolve_timeout(ctx), tool=tool)


def success(tool: str, data: Any, meta: Optional[Dict[str, Any]] = None) -> str:
    envelope = {
        "ok": True,
        "tool": tool,
        "data": data,
        "meta": meta or {"source": "alpha-strike"},
    }
    return json.dumps(envelope, ensure_ascii=False, default=str)


def failure(tool: str, message: str, *, hint: Optional[str] = None) -> str:
    envelope: Dict[str, Any] = {"ok": False, "tool": tool, "error": str(message)}
    if hint:
        envelope["hint"] = hint
    return json.dumps(envelope, ensure_ascii=False, default=str)
