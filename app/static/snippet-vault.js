function snippetVaultApp() {
  return {
    loading: true,
    saving: false,
    error: null,
    copiedId: null,
    search: '',
    selectedType: 'all',
    notes: [],
    formOpen: false,
    form: {
      id: null,
      title: '',
      content: '',
      type: 'other',
      tagsText: '',
    },
    types: [
      { id: 'all', label: 'All', icon: 'select_all' },
      { id: 'ssh', label: 'SSH', icon: 'dns' },
      { id: 'database', label: 'Database', icon: 'database' },
      { id: 'command', label: 'Commands', icon: 'terminal' },
      { id: 'credential', label: 'Credentials', icon: 'key' },
      { id: 'query', label: 'Queries', icon: 'article' },
      { id: 'other', label: 'Other', icon: 'description' },
    ],

    async init() {
      await this.load();
    },

    async load() {
      this.loading = true;
      this.error = null;
      try {
        const res = await fetch('/api/snippet-vault');
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || data.error || res.statusText);
        this.notes = data.notes || [];
      } catch (e) {
        this.error = e.message;
      } finally {
        this.loading = false;
      }
    },

    get filteredNotes() {
      const term = this.search.trim().toLowerCase();
      return this.notes.filter((note) => {
        const matchesType = this.selectedType === 'all' || note.type === this.selectedType;
        const haystack = [
          note.title,
          note.content,
          ...(note.tags || []),
        ].join(' ').toLowerCase();
        return matchesType && (!term || haystack.includes(term));
      });
    },

    get typeCounts() {
      const counts = { all: this.notes.length };
      for (const note of this.notes) {
        counts[note.type] = (counts[note.type] || 0) + 1;
      }
      return counts;
    },

    newNote() {
      this.form = { id: null, title: '', content: '', type: 'other', tagsText: '' };
      this.formOpen = true;
    },

    edit(note) {
      this.form = {
        id: note.id,
        title: note.title,
        content: note.content,
        type: note.type,
        tagsText: (note.tags || []).join(', '),
      };
      this.formOpen = true;
      window.scrollTo({ top: 0, behavior: 'smooth' });
    },

    async save() {
      this.saving = true;
      this.error = null;
      const payload = {
        title: this.form.title.trim(),
        content: this.form.content,
        type: this.form.type,
        tags: this.form.tagsText.split(',').map((tag) => tag.trim()).filter(Boolean),
      };
      try {
        const url = this.form.id
          ? `/api/snippet-vault/notes/${encodeURIComponent(this.form.id)}`
          : '/api/snippet-vault/notes';
        const res = await fetch(url, {
          method: this.form.id ? 'PATCH' : 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || data.error || res.statusText);
        this.formOpen = false;
        await this.load();
      } catch (e) {
        this.error = e.message;
      } finally {
        this.saving = false;
      }
    },

    async remove(note) {
      if (!confirm(`Delete "${note.title}"?`)) return;
      this.error = null;
      try {
        const res = await fetch(`/api/snippet-vault/notes/${encodeURIComponent(note.id)}`, {
          method: 'DELETE',
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || data.error || res.statusText);
        await this.load();
      } catch (e) {
        this.error = e.message;
      }
    },

    async copy(text, id = 'content') {
      try {
        await navigator.clipboard.writeText(text);
        this.copiedId = id;
        setTimeout(() => {
          if (this.copiedId === id) this.copiedId = null;
        }, 1200);
      } catch (e) {
        this.error = 'Copy failed';
      }
    },

    commands(note) {
      return (note.content || '').split('\n').map((line) => line.trim()).filter((line) => {
        const upper = line.toUpperCase();
        return line.startsWith('ssh ')
          || line.startsWith('sudo ')
          || line.startsWith('docker ')
          || line.startsWith('scp ')
          || upper.includes('SELECT ')
          || upper.includes('UPDATE ')
          || upper.includes('CREATE ')
          || upper.includes('PG_DUMP');
      });
    },

    icon(type) {
      return (this.types.find((item) => item.id === type) || this.types[this.types.length - 1]).icon;
    },

    typeClass(type) {
      return {
        ssh: 'bg-blue-500/15 text-blue-300',
        database: 'bg-green-500/15 text-green-300',
        command: 'bg-purple-500/15 text-purple-300',
        credential: 'bg-red-500/15 text-red-300',
        query: 'bg-yellow-500/15 text-yellow-300',
        other: 'bg-surface-container-highest text-on-surface-variant',
      }[type] || 'bg-surface-container-highest text-on-surface-variant';
    },
  };
}
