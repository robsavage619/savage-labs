from __future__ import annotations

import stat
from pathlib import Path

import pytest

from shc.auth import keychain


def test_file_store_round_trips_and_is_owner_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "secrets.json"
    monkeypatch.setenv("SHC_TOKEN_FILE", str(path))

    def boom(*_a: object) -> None:
        raise AssertionError("the Keychain must not be touched in file mode")

    monkeypatch.setattr(keychain.keyring, "set_password", boom)
    monkeypatch.setattr(keychain.keyring, "get_password", boom)

    assert keychain.load_token("whoop", "refresh_token") is None
    keychain.store_token("whoop", "refresh_token", "r1")
    keychain.store_token("whoop", "refresh_token", "r2")  # rotation overwrites
    keychain.store_token("hevy", "api_key", "k")
    assert keychain.load_token("whoop", "refresh_token") == "r2"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600

    keychain.purge_all("whoop")
    assert keychain.load_token("whoop", "refresh_token") is None
    assert keychain.load_token("hevy", "api_key") == "k"
