# Odoo DB Pull

<div align="center">
  <p><strong>A seamless developer utility to clone, sync, and pull live remote Odoo databases directly into your local environment.</strong></p>
</div>

---

## 🚀 Overview

**Odoo DB Pull** is an elegantly designed internal tool built for developers, system administrators, and integration engineers who need to quickly mirror remote Odoo instances locally.

Instead of manually logging into servers, dumping PostgreSQL, downloading gigabytes of files, and running tedious restore commands, Odoo DB Pull automates the entire migration pipeline over SSH with a beautiful, real-time UI.

### Key Features
- **⚡ Remote Auto-Discovery**: Automatically parse remote servers to detect running Odoo instances and active databases.
- **🗺️ Multi-Target Ecosystem**: Pull databases directly to your **Local** machine, between containers on the **Same Server**, or securely between two different **Remote Servers**.
- **🐳 Dual-Target Restoration**: Inject databases directly into native PostgreSQL installations or securely into Docker containers via optimized `docker cp` and `pg_restore` pipelines.
- **📂 Robust Filestore Sync**: Deploys Odoo `filestore` directories via a manual tar-based approach. Create the archive on the source server once — the app handles the rest (SFTP download, extraction, ownership fix via `sudo`).
- **🖥️ Cinematic Console Interface**: Follow the pipeline process live via an interactive, macOS-styled terminal utilizing Server-Sent Events (SSE).
- **🛡️ Secure Proxying**: Fully relies on SSH authentication keys. For remote-to-remote transfers, your local machine acts as a secure encrypted proxy — never requiring direct SSH trust between servers.

---

## 🛠️ Technology Stack
- **Backend:** Python 3, FastAPI, Paramiko (SSH), Docker SDK.
- **Frontend:** AlpineJS (Reactive State), Tailwind CSS (Cinematic Dark Mode Styling).

---

## ⚙️ Quick Start

### 1. Prerequisites
- **Docker** and **Docker Compose**
- Standard **SSH Configuration** with keys in `~/.ssh` (The app will automatically mount these into the container).
- **Postgres Socket** (Optional, only needed if you want to pull into a native local Postgres installation outside of Docker).

### 2. Installation & Quick Start

Clone the repository and spin up the environment:

```bash
git clone https://github.com/yourusername/odoo-db-pull.git
cd odoo-db-pull

# Copy and configure environment variables
cp .env.example .env
# Edit .env: set PGUSER to your local postgres user

# Start the application
docker-compose up -d --build
```

The application will be available at **[http://localhost:8100](http://localhost:8100)**.

### 3. Volume Mapping & Permissions
The `docker-compose.yml` is configured by default to:
- **SSH Keys**: Mount `~/.ssh` into the container to enable remote connectivity.
- **Docker Socket**: Mount `/var/run/docker.sock` so the app can interact with your local containers.
- **Filestore**: Map your local Odoo filestore path to keep data persistent.

### 4. Filestore Deployment
The filestore sync uses a **manual tar-based approach** to avoid SSH permission issues:

1. On the **source server**, create the archive:
   ```bash
   tar czf /tmp/mydb_filestore.tar.gz -C /var/lib/odoo/filestore mydb
   ```
2. In the app's **Configure** step, enable **Filestore Deploy**, enter the tar path and destination.
3. Click **Pull Database + Filestore** — the app downloads the tar via SFTP, extracts it to `/tmp`, and uses `sudo mv` + `sudo chown` to place it in the final destination.

> **Note:** For server targets (`Same Server` or `Another Server`), provide a `sudo` password if the destination path (e.g. `/var/lib/odoo/filestore`) is owned by the `odoo` system user.

---

## 📖 How it Works

The intuitive 4-step wizard guides you effortlessly:
1. **Connect:** Select a configured server alias from your `~/.ssh/config` or enter manual SSH credentials.
2. **Select DB:** The system queries your server and returns a list of active Odoo environments and databases. Choose your target.
3. **Configure:** Define your target environment (Local, Same Server, or Another Remote). The app can automatically discover Odoo instances on a second remote server if needed. Optionally enable Filestore Deploy.
4. **Pull:** Watch the orchestrated pipeline perform the remote `pg_dump`, secure transfer, optimized restoration, and optional filestore deployment — all live in the web terminal!

---

## 🤝 Contributing
Contributions, issues, and feature requests are highly welcome!
If you're adjusting UI logic, note that the frontend is completely decoupled into modular Jinja2 includes (`app/templates/steps/`).

## 📜 License
Distributed under the MIT License. See `LICENSE` for more information.
