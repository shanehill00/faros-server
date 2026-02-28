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
from faros_server.config import ConfigLoader, Settings
from faros_server.controllers.agent import AgentController
from faros_server.controllers.auth import AuthController
from faros_server.controllers.device_page import DevicePageController
from faros_server.controllers.health import HealthController
from faros_server.dao.agent_dao import AgentDAO
from faros_server.dao.user_dao import UserDAO
from faros_server.models.user import User
from faros_server.plugins.db_heartbeat import DbHeartbeatPlugin
from faros_server.resources.agent import AgentResource
from faros_server.resources.auth import AuthResource
from faros_server.resources.health import HealthResource
from faros_server.services.agent_service import AgentService
from faros_server.services.user_service import UserService
from faros_server.utils.db import Database
from faros_server.utils.jwt import JWTManager


class AppFactory:
    """Builds and configures the Litestar application. All methods are static."""

    @staticmethod
    def _build(settings: Settings) -> State:
        """Construct the full object graph once.

        pool → user_dao → user_service ─┐
                                         ├→ AuthResource
        oauth_client ────────────────────┘
        pool → agent_dao → agent_service → AgentResource
        JWTManager.configure() (class-level)
        HealthResource (standalone)
        """
        pool = Database.init(settings.database_url)
        user_dao = UserDAO(pool)
        user_service = UserService(user_dao)
        agent_dao = AgentDAO(pool)
        agent_service = AgentService(
            agent_dao, expire_minutes=settings.device_code_expire_minutes,
        )
        JWTManager.configure(
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
        )
        heartbeat_plugin = DbHeartbeatPlugin(agent_service)
        agent_resource = AgentResource(
            agent_service=agent_service,
            base_url=settings.base_url,
            heartbeat_plugin=heartbeat_plugin,
        )
        return State({
            "health": health_resource,
            "auth": auth_resource,
            "agent": agent_resource,
        })

    @staticmethod
    @asynccontextmanager
    async def _lifespan(app: Litestar) -> AsyncIterator[None]:
        """Create tables on startup, dispose engine on shutdown."""
        await Database.create_tables()
        yield
        await Database.close()

    @staticmethod
    async def provide_user(
        request: Request[object, object, State],
    ) -> User:
        """Litestar dependency — extract authenticated user from Authorization header."""
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            raise NotAuthorizedException(
                detail="Missing or invalid Authorization header",
            )
        token = header[len("Bearer "):]
        auth_resource: AuthResource = request.app.state.auth
        try:
            return await auth_resource.resolve_token(token)
        except ValueError as error:
            raise NotAuthorizedException(detail=str(error)) from error

    @staticmethod
    def provide_auth(state: State) -> AuthResource:
        """Provide the pre-built AuthResource from app state."""
        auth_resource: AuthResource = state.auth
        return auth_resource

    @staticmethod
    def provide_health(state: State) -> HealthResource:
        """Provide the pre-built HealthResource from app state."""
        health_resource: HealthResource = state.health
        return health_resource

    @staticmethod
    def provide_agent(state: State) -> AgentResource:
        """Provide the pre-built AgentResource from app state."""
        agent_resource: AgentResource = state.agent
        return agent_resource

    @staticmethod
    def create_app(settings: Settings | None = None) -> Litestar:
        """Create and configure the Litestar application."""
        if settings is None:
            settings = ConfigLoader.load_settings()
        return Litestar(
            route_handlers=[
                HealthController, AuthController,
                AgentController, DevicePageController,
            ],
            state=AppFactory._build(settings),
            lifespan=[AppFactory._lifespan],
            dependencies={
                "user": Provide(AppFactory.provide_user),
                "auth": Provide(AppFactory.provide_auth, sync_to_thread=False),
                "health_resource": Provide(AppFactory.provide_health, sync_to_thread=False),
                "agent_resource": Provide(AppFactory.provide_agent, sync_to_thread=False),
            },
        )


# Public alias so conftest / uvicorn can call create_app() without knowing AppFactory.
create_app = AppFactory.create_app


class CLI:
    """Command-line interface for faros-server."""

    @staticmethod
    def _build_parser() -> argparse.ArgumentParser:
        """Build the CLI argument parser."""
        parser = argparse.ArgumentParser(
            prog="faros-server", description="Faros Server CLI",
        )
        subparsers = parser.add_subparsers(dest="command")

        run_parser = subparsers.add_parser("run", help="Start the server")
        run_parser.add_argument("--host", default="0.0.0.0")
        run_parser.add_argument("--port", type=int, default=8000)
        run_parser.add_argument("--reload", action="store_true", help="Auto-reload on file changes")

        return parser

    @staticmethod
    def main(argv: list[str] | None = None) -> None:
        """CLI entry point. Catches all exceptions and exits cleanly."""
        parser = CLI._build_parser()
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
                    reload=args.reload,
                )
        except KeyboardInterrupt:
            pass
        except Exception as error:
            print(f"Error: {error}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    CLI.main()
