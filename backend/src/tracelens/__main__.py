"""Serve the trace-lens API with uvicorn: ``python -m tracelens``.

The bind address and port come from ``HOST`` and ``PORT`` (default ``127.0.0.1:4318``) and the
database file from ``DB_PATH``. Keep-alive and concurrency are capped to bound the cost of a
client that holds connections open.
"""

from __future__ import annotations

import uvicorn

from tracelens.api import create_app
from tracelens.config import Settings
from tracelens.store import Store

KEEP_ALIVE_TIMEOUT_SECONDS = 5
CONCURRENCY_LIMIT = 64


def main() -> None:
    """Open the store named by the environment and serve the API until interrupted."""
    settings = Settings.from_env()
    store = Store(settings.db_path)
    try:
        uvicorn.run(
            create_app(store),
            host=settings.host,
            port=settings.port,
            timeout_keep_alive=KEEP_ALIVE_TIMEOUT_SECONDS,
            limit_concurrency=CONCURRENCY_LIMIT,
        )
    finally:
        store.close()


if __name__ == "__main__":
    main()
