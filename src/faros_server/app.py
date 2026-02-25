"""Litestar application factory and CLI entry point."""

from __future__ import annotations

import argparse
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from litestar import Litestar, Request
from litestar.datastructures import State
from litestar.di import Provide
from litestar.exceptions import NotAuthorizedException

from faros_server.auth.jwt import current_user_from_token
from faros_server.auth.oauth import GoogleOAuthClient
from faros_server.config import Settings
from faros_server.controllers.auth import AuthController
from faros_server.controllers.health import HealthController
from faros_server.controllers.ws import websocket_endpoint
from faros_server.dao.user_dao import UserDAO
from faros_server.db import close_db, create_tables, init_db
from faros_server.models.user import User
from faros_server.resources.auth import AuthResource
from faros_server.resources.health import HealthResource
from faros_server.services.user_service import UserService


def _build(settings: Settings) -> State:
    """Factory/build phase: construct the full object graph once.

    pool → dao → svc ─┐
                       ├→ auth_resource
    oauth ─────────────┘
    health_resource (standalone)
    """
    pool = init_db(settings.database_url)
    dao = UserDAO(pool)
    svc = UserService(dao)
    oauth = GoogleOAuthClient(
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        base_url=settings.base_url,
        auth_url=settings.google_auth_url,
        token_url=settings.google_token_url,
        userinfo_url=settings.google_userinfo_url,
    )
    health = HealthResource()
    auth = AuthResource(
        svc=svc,
        oauth=oauth,
        secret_key=settings.secret_key,
        token_expire_minutes=settings.token_expire_minutes,
    )
    return State({
        "settings": settings,
        "dao": dao,
        "health": health,
        "auth": auth,
    })


@asynccontextmanager
async def lifespan(app: Litestar) -> AsyncIterator[None]:
    """Create tables on startup, dispose engine on shutdown."""
    await create_tables()
    yield
    await close_db()


async def provide_current_user(
    request: Request[object, object, State],
) -> User:
    """Litestar dependency — extract authenticated user from Authorization header."""
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise NotAuthorizedException(
            detail="Missing or invalid Authorization header"
        )
    token = header[len("Bearer "):]
    settings = request.app.state.settings
    dao: UserDAO = request.app.state.dao
    try:
        return await current_user_from_token(token, settings.secret_key, dao)
    except ValueError as exc:
        raise NotAuthorizedException(detail=str(exc)) from exc


def _provide_auth(state: State) -> AuthResource:
    """Provide the pre-built AuthResource from app state."""
    auth: AuthResource = state.auth
    return auth


def _provide_health(state: State) -> HealthResource:
    """Provide the pre-built HealthResource from app state."""
    health: HealthResource = state.health
    return health


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
            "auth": Provide(_provide_auth, sync_to_thread=False),
            "health_resource": Provide(_provide_health, sync_to_thread=False),
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
