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

from faros_server.clients.google_oauth_client import GoogleOAuthClient
from faros_server.config import Settings, load_settings
from faros_server.controllers.auth import AuthController
from faros_server.controllers.health import HealthController
from faros_server.controllers.ws import websocket_endpoint
from faros_server.dao.user_dao import UserDAO
from faros_server.models.user import User
from faros_server.resources.auth import AuthResource
from faros_server.resources.health import HealthResource
from faros_server.services.user_service import UserService
from faros_server.utils.db import Database
from faros_server.utils.jwt import JWTManager


def _build(settings: Settings) -> State:
    """Factory/build phase: construct the full object graph once.

    pool → dao → service ─┐
                           ├→ AuthResource
    oauth_client ──────────┤
    jwt_manager ───────────┘
    HealthResource (standalone)
    """
    pool = Database.init(settings.database_url)
    user_dao = UserDAO(pool)
    user_service = UserService(user_dao)
    jwt_manager = JWTManager(
        secret_key=settings.secret_key,
        algorithm=settings.jwt_algorithm,
        expire_minutes=settings.token_expire_minutes,
    )
    oauth_client = GoogleOAuthClient(
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        base_url=settings.base_url,
        auth_url=settings.google_auth_url,
        token_url=settings.google_token_url,
        userinfo_url=settings.google_userinfo_url,
    )
    health_resource = HealthResource()
    auth_resource = AuthResource(
        user_service=user_service,
        oauth_client=oauth_client,
        jwt_manager=jwt_manager,
    )
    return State({
        "dao": user_dao,
        "jwt": jwt_manager,
        "health": health_resource,
        "auth": auth_resource,
    })


@asynccontextmanager
async def lifespan(app: Litestar) -> AsyncIterator[None]:
    """Create tables on startup, dispose engine on shutdown."""
    await Database.create_tables()
    yield
    await Database.close()


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
    jwt_manager: JWTManager = request.app.state.jwt
    user_dao: UserDAO = request.app.state.dao
    try:
        return await jwt_manager.resolve_user(token, user_dao)
    except ValueError as error:
        raise NotAuthorizedException(detail=str(error)) from error


def _provide_auth(state: State) -> AuthResource:
    """Provide the pre-built AuthResource from app state."""
    auth_resource: AuthResource = state.auth
    return auth_resource


def _provide_health(state: State) -> HealthResource:
    """Provide the pre-built HealthResource from app state."""
    health_resource: HealthResource = state.health
    return health_resource


def create_app(settings: Settings | None = None) -> Litestar:
    """Create and configure the Litestar application."""
    if settings is None:
        settings = load_settings()
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
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="Start the server")
    run_parser.add_argument("--host", default="0.0.0.0")
    run_parser.add_argument("--port", type=int, default=8000)

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
    except Exception as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    cli_main()
