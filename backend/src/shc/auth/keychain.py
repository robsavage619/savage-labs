from __future__ import annotations

import contextlib
import json
import logging
import os
import threading
from pathlib import Path

import keyring

log = logging.getLogger(__name__)

_SERVICE_PREFIX = "shc"

# A boot-time daemon can't unlock the login Keychain, so a headless host points
# SHC_TOKEN_FILE at an owner-only JSON file instead. Unset, the Keychain is used.
_TOKEN_FILE_ENV = "SHC_TOKEN_FILE"
_file_lock = threading.Lock()


def _service(source: str, kind: str, version: int = 1) -> str:
    return f"{_SERVICE_PREFIX}.{source}.{kind}.v{version}"


def _token_file() -> Path | None:
    raw = os.environ.get(_TOKEN_FILE_ENV)
    return Path(raw) if raw else None


def _read(path: Path) -> dict[str, str]:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return {}


def _write(path: Path, data: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)
    os.replace(tmp, path)  # atomic: a crash mid-write never loses a rotated refresh token


def store_token(source: str, kind: str, value: str, version: int = 1) -> None:
    key = _service(source, kind, version)
    if (path := _token_file()) is not None:
        with _file_lock:
            data = _read(path)
            data[key] = value
            _write(path, data)
    else:
        keyring.set_password(key, source, value)
    log.debug("stored %s/%s", source, kind)


def load_token(source: str, kind: str, version: int = 1) -> str | None:
    key = _service(source, kind, version)
    if (path := _token_file()) is not None:
        with _file_lock:
            return _read(path).get(key)
    return keyring.get_password(key, source)


def delete_token(source: str, kind: str, version: int = 1) -> None:
    key = _service(source, kind, version)
    if (path := _token_file()) is not None:
        with _file_lock:
            data = _read(path)
            if data.pop(key, None) is not None:
                _write(path, data)
        return
    with contextlib.suppress(keyring.errors.PasswordDeleteError):
        keyring.delete_password(key, source)


def purge_all(source: str) -> None:
    """Remove all versioned tokens for a source (use shc auth purge CLI)."""
    for kind in ("access_token", "refresh_token"):
        for v in range(1, 5):
            delete_token(source, kind, version=v)
    log.info("purged all tokens for %s", source)
