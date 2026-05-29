from typing import Optional
from enum import Enum

from pydantic import BaseModel, Field


class PostgresMode(str, Enum):
    native = "native"
    docker = "docker"


class PostgresConnection(BaseModel):
    mode: PostgresMode = "native"
    pg_host: str = Field(default="localhost", min_length=1, max_length=255)
    pg_port: int = Field(default=5432, ge=1, le=65535)
    pg_user: str = Field(default="postgres", min_length=1, max_length=80)
    pg_password: Optional[str] = None
    docker_container: Optional[str] = None


class PostgresTarget(PostgresConnection):
    database: str


class CronRequest(PostgresTarget):
    pid: Optional[int] = None
