import os
import paramiko
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SshHostEntry:
    alias: str
    hostname: str
    user: str
    port: int = 22
    identity_file: Optional[str] = None


def load_ssh_hosts() -> list[SshHostEntry]:
    config_path = os.path.expanduser("~/.ssh/config")
    if not os.path.exists(config_path):
        return []

    cfg = paramiko.SSHConfig()
    with open(config_path) as f:
        cfg.parse(f)

    entries = []
    for alias in cfg.get_hostnames():
        if alias in ("*", ""):
            continue
        lookup = cfg.lookup(alias)
        hostname = lookup.get("hostname", alias)
        # skip wildcards / non-routable entries
        if "*" in hostname or "?" in hostname:
            continue
        identity_files = lookup.get("identityfile", [])
        identity_file = identity_files[0] if identity_files else None
        if identity_file:
            identity_file = os.path.expanduser(identity_file)
        entries.append(SshHostEntry(
            alias=alias,
            hostname=hostname,
            user=lookup.get("user", os.getenv("USER", "root")),
            port=int(lookup.get("port", 22)),
            identity_file=identity_file,
        ))
    return entries


def get_host_entry(alias: str) -> Optional[SshHostEntry]:
    for entry in load_ssh_hosts():
        if entry.alias == alias:
            return entry
    return None