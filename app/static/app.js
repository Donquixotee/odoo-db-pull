function pullApp() {
  return {
    currentStep: 0,
    steps: ['Serveur', 'Base de données', 'Configuration', 'Pull'],

    sshHosts: [],
    pairs: [],
    remoteDbs: [],
    localDbs: [],
    localDockerContainers: [],
    targetPairs: [],

    loading: false,
    loadingDbs: false,
    pulling: false,
    done: false,
    error: null,
    logs: [],
    progress: 0,

    // ── DB Pull progress ────────────────────────────────────────────────────
    _STEP_PROGRESS: [
      { match: 'Connecting to SSH',        pct: 5  },
      { match: 'Running pg_dump',          pct: 20 },
      { match: 'Copying dump',             pct: 35 },
      { match: 'Downloading dump',         pct: 50 },
      { match: 'Creating local database',  pct: 65 },
      { match: 'Creating target database', pct: 65 },
      { match: 'Restoring dump',           pct: 80 },
      { match: 'Done',                     pct: 100 },
    ],

    // ── Filestore progress ──────────────────────────────────────────────────
    _FS_STEP_PROGRESS: [
      { match: 'Connecting to source',     pct: 5  },
      { match: 'Checking file',            pct: 10 },
      { match: 'Found:',                   pct: 15 },
      { match: 'Downloading filestore',    pct: 20 },
      { match: 'Extracting',               pct: 50 },
      { match: 'Extraction complete',      pct: 55 },
      { match: 'Moving to final',          pct: 70 },
      { match: 'Placing at',               pct: 70 },
      { match: 'Files moved',              pct: 80 },
      { match: 'Files placed',             pct: 80 },
      { match: 'Setting ownership',        pct: 90 },
      { match: 'Ownership set',            pct: 95 },
      { match: '✓ Filestore deployed',     pct: 100 },
    ],

    localPgMode: 'native',  // 'native' | 'docker'
    targetMode: 'local',    // 'local' | 'same_server' | 'remote'
    targetSshLoading: false,

    // ── Filestore deploy state ──────────────────────────────────────────────
    filestoreProgress: 0,
    filestoreDone: false,
    filestore: {
      enabled: false,
      tarPath: '',
      dbName: '',
      // ── local mode ───────────────────────────────────────────────────────
      targetLocalPath: window.__defaults__?.localFilestoreBase ?? '',
      // ── local docker mode ─────────────────────────────────────────────────
      // (reuses form.targetPgContainer for the container name)
      targetDockerInternalPath: '/var/lib/odoo/filestore',
      // ── same_server / remote mode ─────────────────────────────────────────
      targetServerPath: '/var/lib/odoo/filestore',
      sudoPassword: '',
      // logs
      logs: [],
    },

    form: {
      alias: '',
      host: '',
      user: '',
      port: 22,
      password: '',
      selectedPair: '',
      sourceDb: '',
      remoteDbUser: 'odoo',
      targetDbName: '',
      targetPgContainer: '',
      targetPgHost: 'localhost',
      targetPgUser: window.__defaults__?.defaultPgUser ?? 'postgres',
      targetPgPassword: '',
      targetPgPort: 5432,
      // For remote target
      targetSshAlias: '',
      targetSshHost: '',
      targetSshUser: '',
      targetSshPassword: '',
      targetSshPort: 22,
      targetSelectedPair: '',
    },

    get selectedPairInfo() {
      return this.pairs.find(p => p.odoo === this.form.selectedPair) || null;
    },

    async init() {
      const [hosts, localDbs, dockerContainers] = await Promise.all([
        fetch('/api/ssh-hosts').then(r => r.json()).catch(() => []),
        fetch('/api/local-dbs').then(r => r.json()).catch(() => []),
        fetch('/api/local-docker-containers').then(r => r.json()).catch(() => []),
      ]);
      this.sshHosts = hosts;
      this.localDbs = localDbs;
      this.localDockerContainers = Array.isArray(dockerContainers) ? dockerContainers : [];
      this._watchSourceDb();
      this._watchLocalPgMode();
    },

    onAliasChange() {
      this.pairs = [];
      this.remoteDbs = [];
      this.form.selectedPair = '';
      this.form.sourceDb = '';
      this.error = null;
    },

    async discover() {
      this.loading = true;
      this.error = null;
      try {
        const res = await fetch('/api/discover', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(this._connPayload()),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || res.statusText);
        if (!data.length) throw new Error('No Odoo instances detected on this server.');
        this.pairs = data;
        this.currentStep = 1;
      } catch (e) {
        this.error = e.message;
      } finally {
        this.loading = false;
      }
    },

    async onPairChange() {
      const pair = this.selectedPairInfo;
      if (!pair) return;
      this.loadingDbs = true;
      this.remoteDbs = [];
      this.form.sourceDb = '';
      try {
        const res = await fetch('/api/list-dbs', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ...this._connPayload(), db_container: pair.db, remote_db_user: this.form.remoteDbUser || 'odoo' }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || res.statusText);
        this.remoteDbs = data;
      } catch (e) {
        this.error = e.message;
      } finally {
        this.loadingDbs = false;
      }
    },

    async discoverTarget() {
      this.targetSshLoading = true;
      this.error = null;
      try {
        const res = await fetch('/api/discover', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
              alias: this.form.targetSshAlias || null,
              host: this.form.targetSshHost || null,
              user: this.form.targetSshUser || null,
              port: this.form.targetSshPort || 22,
              password: this.form.targetSshPassword || null,
          }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || res.statusText);
        if (!data.length) throw new Error('No Odoo instances detected on target server.');
        this.targetPairs = data;
      } catch (e) {
        this.error = e.message;
      } finally {
        this.targetSshLoading = false;
      }
    },

    async _refreshLocalDbs() {
      const url = this.localPgMode === 'docker' && this.form.localPgContainer
        ? `/api/local-dbs?container=${encodeURIComponent(this.form.localPgContainer)}`
        : '/api/local-dbs';
      this.localDbs = await fetch(url).then(r => r.json()).catch(() => []);
      if (this.form.sourceDb) {
        this.form.renameExistingTo = this.localDbs.includes(this.form.sourceDb)
          ? `${this.form.sourceDb}_old` : '';
      }
    },

    _watchSourceDb() {
      this.$watch('form.sourceDb', (val) => {
        if (!val) return;
        this.form.targetDbName = val;
        this.form.renameExistingTo = this.localDbs.includes(val) ? `${val}_old` : '';
        // Auto-fill filestore db name
        if (!this.filestore.dbName) {
          this.filestore.dbName = val;
        }
      });
      // Keep filestore.dbName in sync with targetDbName
      this.$watch('form.targetDbName', (val) => {
        this.filestore.dbName = val;
      });
    },

    _watchLocalPgMode() {
      this.$watch('localPgMode', (mode) => {
        if (mode === 'docker') {
          this.form.targetPgUser = 'postgres';
        } else {
          this.form.targetPgUser = window.__defaults__?.defaultPgUser ?? 'postgres';
        }
        this._refreshLocalDbs();
      });
      this.$watch('form.targetPgContainer', () => this._refreshLocalDbs());
    },

    async startPull() {
      this.currentStep = 3;
      this.logs = [];
      this.pulling = true;
      this.done = false;
      this.progress = 0;
      this.filestoreProgress = 0;
      this.filestoreDone = false;
      this.filestore.logs = [];

      const pair = this.selectedPairInfo;

      const payload = {
        ...this._connPayload(),
        db_container: pair.db,
        source_db: this.form.sourceDb,

        target_mode: this.targetMode,
        target_db_name: this.form.targetDbName,
        rename_existing_to: this.form.renameExistingTo || null,

        target_pg_container: this.localPgMode === 'docker' ? (this.form.targetPgContainer || null) : null,
        target_pg_user: this.form.targetPgUser || null,
        target_pg_password: this.form.targetPgPassword || null,
        target_pg_host: this.localPgMode === 'native' ? (this.form.targetPgHost || 'localhost') : 'localhost',
        target_pg_port: this.form.targetPgPort || 5432,

        remote_db_user: this.form.remoteDbUser || 'odoo',

        target_ssh_alias: this.form.targetSshAlias || null,
        target_ssh_host: this.form.targetSshHost || null,
        target_ssh_user: this.form.targetSshUser || null,
        target_ssh_port: this.form.targetSshPort || 22,
        target_ssh_password: this.form.targetSshPassword || null,
      };

      let dbPullOk = false;
      try {
        const res = await fetch('/api/pull', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const events = buffer.split('\n\n');
          buffer = events.pop();
          for (const event of events) {
            const line = event.replace(/^data: /, '');
            if (!line) continue;
            const [status, ...rest] = line.split('|');
            const message = rest.join('|');
            this.logs.push({ status, message });
            if (status === 'success') { this.done = true; this.progress = 100; dbPullOk = true; }
            if (status === 'error') { this.progress = this.progress || 0; }
            const step = this._STEP_PROGRESS.find(s => message.startsWith(s.match));
            if (step && step.pct > this.progress) this.progress = step.pct;
            this._scrollLog();
          }
        }
      } catch (e) {
        this.logs.push({ status: 'error', message: `Network error: ${e.message}` });
      } finally {
        this.pulling = false;
      }

      // ── Phase 2: Filestore (only if DB pull succeeded and filestore is enabled)
      if (dbPullOk && this.filestore.enabled) {
        await this._runFilestoreDeploy();
      }
    },

    async _runFilestoreDeploy() {
      this.filestoreProgress = 0;
      this.filestoreDone = false;
      this.filestore.logs = [];

      const fs = this.filestore;
      const targetMode = this.targetMode;

      const payload = {
        source_alias: this.form.alias || null,
        source_host:  this.form.host  || null,
        source_user:  this.form.user  || null,
        source_port:  this.form.port  || 22,
        source_password: this.form.password || null,

        tar_remote_path: fs.tarPath,
        db_name: fs.dbName || this.form.targetDbName || this.form.sourceDb,
        target_mode: targetMode,

        target_local_path: (targetMode === 'local' && this.localPgMode === 'native')
          ? (fs.targetLocalPath || null) : null,
        target_docker_container: (targetMode === 'local' && this.localPgMode === 'docker')
          ? (this.form.targetPgContainer || null) : null,
        target_docker_internal_path: fs.targetDockerInternalPath || '/var/lib/odoo/filestore',

        target_server_path: (targetMode === 'same_server' || targetMode === 'remote')
          ? (fs.targetServerPath || null) : null,
        target_sudo_password: (targetMode === 'same_server' || targetMode === 'remote')
          ? (fs.sudoPassword || null) : null,

        target_ssh_alias:    targetMode === 'remote' ? (this.form.targetSshAlias    || null) : null,
        target_ssh_host:     targetMode === 'remote' ? (this.form.targetSshHost     || null) : null,
        target_ssh_user:     targetMode === 'remote' ? (this.form.targetSshUser     || null) : null,
        target_ssh_port:     targetMode === 'remote' ? (this.form.targetSshPort     || 22)   : 22,
        target_ssh_password: targetMode === 'remote' ? (this.form.targetSshPassword || null) : null,
      };

      try {
        const res = await fetch('/api/filestore/deploy', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const events = buffer.split('\n\n');
          buffer = events.pop();
          for (const event of events) {
            const line = event.replace(/^data: /, '');
            if (!line) continue;
            const [status, ...rest] = line.split('|');
            const message = rest.join('|');
            this.filestore.logs.push({ status, message });
            if (status === 'success') { this.filestoreDone = true; this.filestoreProgress = 100; }
            const step = this._FS_STEP_PROGRESS.find(s => message.startsWith(s.match));
            if (step && step.pct > this.filestoreProgress) this.filestoreProgress = step.pct;
            this._scrollFilestoreLog();
          }
        }
      } catch (e) {
        this.filestore.logs.push({ status: 'error', message: `Network error: ${e.message}` });
      }
    },

    logClass(status) {
      return {
        'text-green-400': status === 'success',
        'text-red-400': status === 'error',
        'text-yellow-400': status === 'warning',
        'text-gray-300': status === 'info',
      };
    },

    _scrollLog() {
      this.$nextTick(() => {
        const box = document.getElementById('log-box');
        if (box) box.scrollTop = box.scrollHeight;
      });
    },

    _scrollFilestoreLog() {
      this.$nextTick(() => {
        const box = document.getElementById('fs-log-box');
        if (box) box.scrollTop = box.scrollHeight;
      });
    },

    _connPayload() {
      return {
        alias: this.form.alias || null,
        host: this.form.host || null,
        user: this.form.user || null,
        port: this.form.port,
        password: this.form.password || null,
      };
    },

    reset() {
      this.currentStep = 0;
      this.pairs = [];
      this.remoteDbs = [];
      this.logs = [];
      this.done = false;
      this.progress = 0;
      this.error = null;
      this.form.selectedPair = '';
      this.form.sourceDb = '';
      this.filestore.logs = [];
      this.filestoreProgress = 0;
      this.filestoreDone = false;
    },
  };
}