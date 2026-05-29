function odooCronDebuggerApp() {
  return {
    loading: null,
    killingPid: null,
    error: null,
    message: null,
    databases: [],
    dockerContainers: [],
    stuckCrons: [],
    recentCrons: [],
    activeSessions: [],
    target: {
      mode: 'native',
      pg_user: window.__defaults__?.defaultPgUser ?? 'postgres',
      pg_password: '',
      pg_host: 'localhost',
      pg_port: 5432,
      docker_container: '',
      database: '',
    },

    async init() {
      await this.loadDockerContainers();
    },

    connectionPayload(includeDatabase = true) {
      const payload = {
        mode: this.target.mode,
        pg_user: this.target.pg_user,
        pg_password: this.target.pg_password || null,
        pg_host: this.target.pg_host || 'localhost',
        pg_port: Number(this.target.pg_port || 5432),
        docker_container: this.target.mode === 'docker' ? (this.target.docker_container || null) : null,
      };
      if (includeDatabase) {
        payload.database = this.target.database;
      }
      return payload;
    },

    async request(path, body) {
      const res = await fetch(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || data.error || res.statusText);
      return data;
    },

    async loadDockerContainers() {
      try {
        const res = await fetch('/api/odoo-cron-debugger/docker-containers');
        const data = await res.json();
        this.dockerContainers = Array.isArray(data) ? data : [];
      } catch {
        this.dockerContainers = [];
      }
    },

    async loadDatabases() {
      this.loading = 'databases';
      this.error = null;
      this.message = null;
      try {
        this.databases = await this.request(
          '/api/odoo-cron-debugger/databases',
          this.connectionPayload(false),
        );
        if (!this.target.database && this.databases.length) {
          this.target.database = this.databases[0].name;
        }
        this.message = `Loaded ${this.databases.length} database${this.databases.length === 1 ? '' : 's'}`;
      } catch (e) {
        this.error = e.message;
        this.databases = [];
      } finally {
        this.loading = null;
      }
    },

    async loadStuckCrons() {
      await this.loadPanel('stuck', '/api/odoo-cron-debugger/stuck-crons', (data) => {
        this.stuckCrons = data;
      });
    },

    async loadRecentCrons() {
      await this.loadPanel('recent', '/api/odoo-cron-debugger/recent-crons', (data) => {
        this.recentCrons = data;
      });
    },

    async loadActiveSessions() {
      await this.loadPanel('sessions', '/api/odoo-cron-debugger/active-sessions', (data) => {
        this.activeSessions = data;
      });
    },

    async loadAll() {
      await Promise.all([
        this.loadStuckCrons(),
        this.loadRecentCrons(),
        this.loadActiveSessions(),
      ]);
    },

    async loadPanel(name, path, assign) {
      if (!this.target.database) {
        this.error = 'Choose a database first';
        return;
      }
      this.loading = name;
      this.error = null;
      this.message = null;
      try {
        assign(await this.request(path, this.connectionPayload(true)));
      } catch (e) {
        this.error = e.message;
      } finally {
        this.loading = null;
      }
    },

    async killBackend(pid) {
      if (!window.confirm(`Terminate PostgreSQL backend ${pid}?`)) return;
      this.killingPid = pid;
      this.error = null;
      this.message = null;
      try {
        const result = await this.request('/api/odoo-cron-debugger/kill-backend', {
          ...this.connectionPayload(true),
          pid,
        });
        if (!result.success) throw new Error(result.message || 'Backend was not terminated');
        this.message = result.message;
        await Promise.all([this.loadStuckCrons(), this.loadActiveSessions()]);
      } catch (e) {
        this.error = e.message;
      } finally {
        this.killingPid = null;
      }
    },

    duration(seconds) {
      const value = Number(seconds || 0);
      if (value >= 3600) return `${Math.floor(value / 3600)}h ${Math.floor((value % 3600) / 60)}m`;
      if (value >= 60) return `${Math.floor(value / 60)}m ${value % 60}s`;
      return `${value}s`;
    },

    stateClass(state) {
      if (state === 'active') return 'bg-green-500/15 text-green-300';
      if (state === 'idle in transaction') return 'bg-red-500/15 text-red-300';
      return 'bg-surface-container-highest text-on-surface-variant';
    },
  };
}
