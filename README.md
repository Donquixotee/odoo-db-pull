# Personal Admin Tools

A local FastAPI web app for small developer/admin utilities. The project started as **Odoo DB Pull**, then was refactored into a modular tool platform so new personal tools can be added under the same dark UI, shared navbar, shared branding, and Docker runtime.

The app is available at:

```text
http://localhost:8100
```

## Current Tools

### Odoo DB Pull

Pull Odoo databases and optional filestores from remote servers into local, same-server, or remote targets.

Features:
- Discover Odoo/Postgres Docker container pairs over SSH.
- List remote databases.
- Run remote `pg_dump`.
- Restore into local native PostgreSQL, local Docker PostgreSQL, same-server target, or another remote server.
- Optional filestore deployment from a tar archive.
- Server-Sent Events progress logs.

### Time Tracker

Track part-time work sessions and earnings.

Features:
- Store task date, title, notes, hours, hourly rate, status, and paid/unpaid state.
- Default rate: `7.5 EUR/hour`.
- Custom EUR to DZD conversion rate.
- Show total hours, total EUR, unpaid EUR, total DZD, and unpaid DZD.
- JSON persistence in `app/data/time_tracker.json`.

### Snippet Vault

Replacement for a previous local Next.js notes app, rebuilt in FastAPI/Jinja/Alpine and integrated into this platform.

Features:
- Stores frequently used SSH commands, credentials, SQL queries, paths, notes, and technical snippets.
- Search by title, content, or tag.
- Filter by type: SSH, Database, Command, Credential, Query, Other.
- Copy full content.
- Quick-copy extracted commands/queries.
- Add, edit, and delete notes.
- Seeded from a previous local Next.js notes app.
- JSON persistence in `app/data/snippet_vault.json`.

### Postgres Maintenance

Inspect local PostgreSQL databases and run maintenance operations.

Features:
- Native local PostgreSQL target.
- Local Docker PostgreSQL target.
- Database list ordered by size.
- Multi-select databases.
- Run:
  - `VACUUM`
  - `VACUUM ANALYZE`
  - `REINDEX DATABASE`
- Records size before, size after, and delta for each database.
- Stores history in `app/data/postgres_maintenance.json`.

Note: `VACUUM ANALYZE` does not necessarily shrink disk usage. It marks space reusable and updates planner statistics; database size may stay the same or increase slightly.

## Tech Stack

- Backend: Python 3.11, FastAPI, Pydantic
- Frontend: Jinja2 templates, AlpineJS, Tailwind CDN
- SSH: Paramiko
- Containers: Docker SDK and Docker socket
- Database CLI tools: `psql`, `pg_dump`, `pg_restore`, `vacuumdb`, `reindexdb`
- Persistence: JSON files under `app/data/`

## Project Structure

```text
app/
  core/
    config.py
    templates.py
    tool_registry.py
  data/
    postgres_maintenance.json
    snippet_vault.json
    time_tracker.json
  static/
    app.js
    postgres-maintenance.js
    snippet-vault.js
    time-tracker.js
    logo-dark.png
    favicon.png
  templates/
    partials/
    postgres_maintenance/
    snippet_vault/
    steps/
    time_tracker/
    index.html
  tools/
    odoo_db_pull/
    postgres_maintenance/
    snippet_vault/
    time_tracker/
  main.py
```

`app/main.py` is intentionally thin. It creates the FastAPI app, mounts static files, and includes each tool router.

New tools should generally follow this shape:

```text
app/tools/my_tool/
  __init__.py
  routes.py
  schemas.py
  storage.py      # if the tool persists JSON data
  service.py      # if it has command/business logic

app/templates/my_tool/index.html
app/static/my-tool.js
app/data/my_tool.json
```

Then register the tool in `app/core/tool_registry.py` and include its router in `app/main.py`.

## Persistence

The app stores tool data in JSON files under `app/data/`.

Current files:
- `app/data/time_tracker.json`
- `app/data/snippet_vault.json`
- `app/data/postgres_maintenance.json`

Because `docker-compose.yml` bind-mounts `./app` into the container, these JSON files persist across container restarts.

Depending on which process created or updated a JSON file, it may be owned by the container user. The app can still read/write it from inside the container.

## Quick Start

### Prerequisites

- Docker
- Docker Compose
- SSH config/keys in `~/.ssh` for Odoo DB Pull remote access
- Local PostgreSQL tools are installed inside the container image
- Docker socket access if using Docker-based database targets

### Run

```bash
docker compose up -d --build
```

Open:

```text
http://localhost:8100
```

The compose service uses host networking and runs:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8100 --reload --reload-dir /app/app
```

## Docker Volumes

`docker-compose.yml` mounts:

- `~/.ssh` into the container for SSH access.
- `/var/run/postgresql` for native local PostgreSQL socket access.
- `/var/run/docker.sock` for local Docker PostgreSQL discovery and operations.
- `~/.local/share/Odoo/filestore` for local Odoo filestore targets.
- `/tmp` for dump and temporary transfer files.
- `./app` for live-reloaded source code and persistent JSON data.

## Odoo Filestore Deployment

The Odoo filestore deploy flow expects you to create a tar archive on the source server first:

```bash
tar czf /tmp/mydb_filestore.tar.gz -C /var/lib/odoo/filestore mydb
```

Then enable filestore deployment in the Odoo DB Pull configuration step and provide:
- source tar path
- target path/container
- sudo password when required for server-side destinations

## Notes

- This is a local personal/admin tool, not a public multi-user application.
- Some tools handle sensitive credentials and commands. Keep the repo and `app/data/` files private.
- Postgres maintenance operations can be disruptive depending on database size and workload. Use `REINDEX` and large multi-database runs carefully.

## License

MIT. See `LICENSE`.
