"""SQLAlchemy ORM models."""

# Import all models so Base.metadata registers them for create_all().
from faros_server.models.agent import Agent as Agent
from faros_server.models.agent import ApiKey as ApiKey
from faros_server.models.agent import DeviceRegistration as DeviceRegistration
from faros_server.models.command import AgentCommand as AgentCommand
from faros_server.models.event import AgentEvent as AgentEvent
from faros_server.models.user import User as User
from faros_server.models.user import UserAuthMethod as UserAuthMethod
