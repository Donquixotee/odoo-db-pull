from typing import Literal, Optional

from pydantic import BaseModel, Field


TargetMode = Literal["native", "docker"]
MaintenanceOperation = Literal["vacuum", "vacuum_analyze", "reindex"]


class PostgresTarget(BaseModel):
    mode: TargetMode = "native"
    pg_user: str = Field(default="postgres", min_length=1, max_length=80)
    pg_password: Optional[str] = None
    pg_host: str = Field(default="localhost", min_length=1, max_length=255)
    pg_port: int = Field(default=5432, gt=0, le=65535)
    docker_container: Optional[str] = None


class MaintenanceRequest(PostgresTarget):
    databases: list[str] = Field(min_length=1, max_length=200)
    operation: MaintenanceOperation
