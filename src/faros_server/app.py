"""FastAPI application factory and CLI entry point."""

from __future__ import annotations

import argparse
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from faros_server.config import Settings
from faros_server.db import close_db, create_tables, init_db
from faros_server.routers import auth, health, ws


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize and tear down database on startup/shutdown."""
    settings: Settings = app.state.settings
    init_db(settings.database_url)
    await create_tables()
    yield
    await close_db()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    if settings is None:
        settings = Settings()
    app = FastAPI(title="Faros Server", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(ws.router)
    return app


def _build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(prog="faros-server", description="Faros Server CLI")
    sub = parser.add_subparsers(dest="command")

    run_p = sub.add_parser("run", help="Start the server")
    run_p.add_argument("--host", default="0.0.0.0")
    run_p.add_argument("--port", type=int, default=8000)

    return parser


def cli_main(argv: list[str] | None = None) -> None:
    """CLI entry point. Catches all exceptions and exits cleanly."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    try:
        if args.command == "run":
            import uvicorn

            uvicorn.run(
                "faros_server.app:create_app",
                factory=True,
                host=args.host,
                port=args.port,
            )
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    cli_main()
