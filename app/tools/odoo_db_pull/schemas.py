from typing import Optional

from pydantic import BaseModel


class ConnectRequest(BaseModel):
    alias: Optional[str] = None
    host: Optional[str] = None
    user: Optional[str] = None
    port: int = 22
    password: Optional[str] = None


class DiscoverRequest(ConnectRequest):
    pass


class ListDbsRequest(ConnectRequest):
    db_container: str
    remote_db_user: str = "odoo"


class PullRequest(ConnectRequest):
    db_container: str
    source_db: str
    target_db_name: str

    # "local", "same_server", "remote"
    target_mode: str = "local"

    rename_existing_to: Optional[str] = None

    target_pg_container: Optional[str] = None
    target_pg_user: Optional[str] = None
    target_pg_password: Optional[str] = None
    target_pg_host: str = "localhost"
    target_pg_port: int = 5432

    remote_db_user: str = "odoo"

    # For remote-to-remote (where target_mode == 'remote')
    target_ssh_alias: Optional[str] = None
    target_ssh_host: Optional[str] = None
    target_ssh_user: Optional[str] = None
    target_ssh_port: int = 22
    target_ssh_password: Optional[str] = None


class FilestoreDeployRequest(BaseModel):
    """
    Deploy filestore — mirrors the DB pull target mode.

    Source server credentials are the SAME as the DB pull (form.alias/host/user/password).
    Target credentials are derived from the chosen target_mode:
      - 'local'       : deploy to local path or local docker container
      - 'same_server' : deploy on the source server itself (same SSH creds)
      - 'remote'      : deploy on the separate target server (target_ssh_* creds)

    The user runs on source server:
        tar czf /tmp/mydb_filestore.tar.gz -C /var/lib/odoo/filestore mydb
    """
    # Source SSH (same as DB pull — where the tar lives)
    source_alias: Optional[str] = None
    source_host: Optional[str] = None
    source_user: Optional[str] = None
    source_port: int = 22
    source_password: Optional[str] = None

    # Path on the SOURCE server where the tar.gz was created
    tar_remote_path: str

    # Folder name inside the filestore (= target DB name)
    db_name: str

    # Target mode: mirrors DB pull
    # 'local' | 'same_server' | 'remote'
    target_mode: str = "local"

    # local mode
    target_local_path: Optional[str] = None
    target_docker_container: Optional[str] = None
    target_docker_internal_path: str = "/var/lib/odoo/filestore"

    # same_server & remote mode
    target_server_path: Optional[str] = None
    target_sudo_password: Optional[str] = None
    odoo_user: str = "odoo"

    # remote mode only: target server SSH
    target_ssh_alias: Optional[str] = None
    target_ssh_host: Optional[str] = None
    target_ssh_user: Optional[str] = None
    target_ssh_port: int = 22
    target_ssh_password: Optional[str] = None
