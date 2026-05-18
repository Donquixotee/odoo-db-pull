function postgresMaintenanceApp() {
  return {
    loading: false,
    running: false,
    error: null,
    message: null,
    databases: [],
    history: [],
    dockerContainers: [],
    selectedDatabases: [],
    selectedOperation: 'vacuum_analyze',
    target: {
      mode: 'native',
      pg_user: window.__defaults__?.defaultPgUser ?? 'postgres',
      pg_password: '',
      pg_host: 'localhost',
      pg_port: 5432,
      docker_container: '',
    },
    operations: [
      { id: 'vacuum', label: 'Vacuum', icon: 'cleaning_services' },
      { id: 'vacuum_analyze', label: 'Vacuum Analyze', icon: 'query_stats' },
      { id: 'reindex', label: 'Reindex', icon: 'view_column' },
    ],

    async init() {
      await Promise.all([this.loadHistory(), this.loadDockerContainers()]);
    },

    payload() {
      return {
        mode: this.target.mode,
        pg_user: this.target.pg_user,
        pg_password: this.target.pg_password || null,
        pg_host: this.target.pg_host || 'localhost',
        pg_port: Number(this.target.pg_port || 5432),
        docker_container: this.target.mode === 'docker' ? (this.target.docker_container || null) : null,
      };
    },

    async loadDatabases() {
      this.loading = true;
      this.error = null;
      this.message = null;
      try {
        const res = await fetch('/api/postgres-maintenance/databases', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(this.payload()),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || data.error || res.statusText);
        this.databases = data;
        const names = new Set(this.databases.map((db) => db.name));
        this.selectedDatabases = this.selectedDatabases.filter((name) => names.has(name));
      } catch (e) {
        this.error = e.message;
        this.databases = [];
        this.selectedDatabases = [];
      } finally {
        this.loading = false;
      }
    },

    async loadDockerContainers() {
      try {
        const res = await fetch('/api/postgres-maintenance/docker-containers');
        const data = await res.json();
        this.dockerContainers = Array.isArray(data) ? data : [];
      } catch {
        this.dockerContainers = [];
      }
    },

    async loadHistory() {
      try {
        const res = await fetch('/api/postgres-maintenance/history');
        this.history = await res.json();
      } catch {
        this.history = [];
      }
    },

    async runMaintenance() {
      if (!this.selectedDatabases.length) {
        this.error = 'Select at least one database first';
        return;
      }
      this.running = true;
      this.error = null;
      this.message = null;
      try {
        const res = await fetch('/api/postgres-maintenance/run', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            ...this.payload(),
            databases: this.selectedDatabases,
            operation: this.selectedOperation,
          }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || data.error || res.statusText);
        const okCount = data.results?.length || 0;
        const errorCount = data.errors?.length || 0;
        this.message = errorCount
          ? `Completed ${okCount}, failed ${errorCount}`
          : `Maintenance completed for ${okCount} database${okCount === 1 ? '' : 's'}`;
        await Promise.all([this.loadDatabases(), this.loadHistory()]);
      } catch (e) {
        this.error = e.message;
        await this.loadHistory();
      } finally {
        this.running = false;
      }
    },

    operationLabel(value) {
      return (this.operations.find((op) => op.id === value) || {}).label || value;
    },

    toggleDatabase(name) {
      if (this.selectedDatabases.includes(name)) {
        this.selectedDatabases = this.selectedDatabases.filter((item) => item !== name);
      } else {
        this.selectedDatabases = [...this.selectedDatabases, name];
      }
    },

    selectAllDatabases() {
      this.selectedDatabases = this.databases.map((db) => db.name);
    },

    clearDatabases() {
      this.selectedDatabases = [];
    },

    isSelected(name) {
      return this.selectedDatabases.includes(name);
    },

    formatBytes(bytes) {
      const value = Number(bytes || 0);
      const abs = Math.abs(value);
      if (abs >= 1024 ** 3) return `${(value / 1024 ** 3).toFixed(2)} GB`;
      if (abs >= 1024 ** 2) return `${(value / 1024 ** 2).toFixed(2)} MB`;
      if (abs >= 1024) return `${(value / 1024).toFixed(2)} kB`;
      return `${value} bytes`;
    },

    deltaClass(bytes) {
      const value = Number(bytes || 0);
      if (value > 0) return 'text-yellow-300';
      if (value < 0) return 'text-green-300';
      return 'text-on-surface-variant';
    },

    deltaText(bytes) {
      const value = Number(bytes || 0);
      const prefix = value > 0 ? '+' : '';
      return `${prefix}${this.formatBytes(value)}`;
    },
  };
}
