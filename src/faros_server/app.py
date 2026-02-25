"""Litestar application factory and CLI entry point."""

from __future__ import annotations

import argparse
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from litestar import Litestar
from litestar.datastructures import State
from litestar.di import Provide

from faros_server.auth.deps import provide_current_user
from faros_server.config import Settings
from faros_server.controllers.auth import AuthController
from faros_server.controllers.health import HealthController
from faros_server.controllers.ws import websocket_endpoint
from faros_server.dao.user_dao import UserDAO
from faros_server.db import close_db, create_tables, init_db
from faros_server.services.user_service import UserService


def _build(settings: Settings) -> State:
    """Factory/build phase: construct the full object graph once."""
    pool = init_db(settings.database_url)
    dao = UserDAO(pool)
    svc = UserService(dao)
    return State({"settings": settings, "dao": dao, "svc": svc})


@asynccontextmanager
async def lifespan(app: Litestar) -> AsyncIterator[None]:
    """Create tables on startup, dispose engine on shutdown."""
    await create_tables()
    yield
    await close_db()


def _provide_svc(state: State) -> UserService:
    """Provide the pre-built UserService from app state."""
    svc: UserService = state.svc
    return svc


def _provide_settings(state: State) -> Settings:
    """Provide the app settings from app state."""
    settings: Settings = state.settings
    return settings


def create_app(settings: Settings | None = None) -> Litestar:
    """Create and configure the Litestar application."""
    if settings is None:
        settings = Settings()
    return Litestar(
        route_handlers=[HealthController, AuthController, websocket_endpoint],
        state=_build(settings),
        lifespan=[lifespan],
        dependencies={
            "user": Provide(provide_current_user),
            "svc": Provide(_provide_svc, sync_to_thread=False),
            "settings": Provide(_provide_settings, sync_to_thread=False),
        },
    )


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
