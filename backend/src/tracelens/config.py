"""Runtime settings and the ingestion limits from the design document.

Only the network settings come from the environment. The ingestion limits are fixed constants
so that a deployment cannot silently raise the cost of untrusted input.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 4318
DEFAULT_DB_PATH = "trace-lens.db"

MAX_BODY_BYTES = 4 * 1024 * 1024
"""Largest accepted request body, enforced while the body is streamed."""
MAX_SPANS_PER_REQUEST = 10_000
MAX_NAME_CHARS = 256
"""Limit for span names and for the ``service.name`` value."""
MAX_ATTRIBUTES_PER_SPAN = 64
"""Limit on attributes per span, counting the resource attributes it inherits."""
MAX_ATTRIBUTE_KEY_CHARS = 128
MAX_ATTRIBUTE_VALUE_CHARS = 4_096
MAX_STATUS_MESSAGE_CHARS = 1_024
MAX_JSON_DEPTH = 32
"""JSON nesting depth beyond which a body is refused before decoding."""

_PORT_PATTERN = re.compile(r"[0-9]{1,5}")


@dataclass(frozen=True, slots=True)
class Settings:
    """Network and storage settings for one server process.

    The default host is the loopback address, so the server is not reachable from the network
    unless ``HOST`` is set explicitly.
    """

    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    db_path: str = DEFAULT_DB_PATH

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        """Build settings from ``HOST``, ``PORT`` and ``DB_PATH``, falling back to defaults.

        Args:
            environ: Mapping to read from; defaults to the process environment.

        Raises:
            ValueError: If a value is empty or ``PORT`` is not a decimal number in 1..65535.
        """
        env = os.environ if environ is None else environ
        host = env.get("HOST", DEFAULT_HOST)
        port_text = env.get("PORT", str(DEFAULT_PORT))
        db_path = env.get("DB_PATH", DEFAULT_DB_PATH)
        if not host.strip():
            raise ValueError("HOST must not be empty")
        if not db_path:
            raise ValueError("DB_PATH must not be empty")
        if _PORT_PATTERN.fullmatch(port_text) is None or not 1 <= int(port_text) <= 65_535:
            raise ValueError("PORT must be a decimal number between 1 and 65535")
        return cls(host=host, port=int(port_text), db_path=db_path)
