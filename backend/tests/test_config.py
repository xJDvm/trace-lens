"""Tests for settings loading and the ingestion limit constants."""

from __future__ import annotations

import pytest

from tracelens import config
from tracelens.config import Settings


def test_defaults_bind_loopback_only() -> None:
    settings = Settings.from_env({})

    assert settings == Settings(host="127.0.0.1", port=4318, db_path="trace-lens.db")


def test_environment_overrides_defaults() -> None:
    settings = Settings.from_env({"HOST": "192.0.2.5", "PORT": "8080", "DB_PATH": "/data/t.db"})

    assert settings == Settings(host="192.0.2.5", port=8080, db_path="/data/t.db")


@pytest.mark.parametrize("port", ["1", "65535", "4318"])
def test_valid_port_boundaries_are_accepted(port: str) -> None:
    assert Settings.from_env({"PORT": port}).port == int(port)


@pytest.mark.parametrize("port", ["0", "65536", "99999", "-1", "+80", "80.0", "", " 80", "0x50"])
def test_invalid_port_is_rejected(port: str) -> None:
    with pytest.raises(ValueError, match="PORT"):
        Settings.from_env({"PORT": port})


@pytest.mark.parametrize("host", ["", "   "])
def test_blank_host_is_rejected(host: str) -> None:
    with pytest.raises(ValueError, match="HOST"):
        Settings.from_env({"HOST": host})


def test_empty_db_path_is_rejected() -> None:
    with pytest.raises(ValueError, match="DB_PATH"):
        Settings.from_env({"DB_PATH": ""})


def test_from_env_defaults_to_process_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PORT", "9000")

    assert Settings.from_env().port == 9000


def test_ingestion_limits_match_design() -> None:
    assert config.MAX_BODY_BYTES == 4 * 1024 * 1024
    assert config.MAX_SPANS_PER_REQUEST == 10_000
    assert config.MAX_NAME_CHARS == 256
    assert config.MAX_ATTRIBUTES_PER_SPAN == 64
    assert config.MAX_ATTRIBUTE_KEY_CHARS == 128
    assert config.MAX_ATTRIBUTE_VALUE_CHARS == 4_096
    assert config.MAX_STATUS_MESSAGE_CHARS == 1_024
    assert config.MAX_JSON_DEPTH == 32
