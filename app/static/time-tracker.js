function timeTrackerApp() {
  return {
    loading: true,
    saving: false,
    error: null,
    entries: [],
    summary: {
      total_hours: 0,
      total_amount: 0,
      unpaid_amount: 0,
      total_amount_dzd: 0,
      unpaid_amount_dzd: 0,
      entry_count: 0,
    },
    settings: {
      eur_to_dzd_rate: window.__defaults__?.defaultEurToDzdRate ?? 250,
    },
    form: {
      id: null,
      work_date: new Date().toISOString().slice(0, 10),
      task: '',
      notes: '',
      hoursPart: '',
      minutesPart: '',
      hourly_rate: window.__defaults__?.defaultHourlyRate ?? 7.5,
      status: 'sent',
      paid: false,
    },

    async init() {
      await this.load();
    },

    async load() {
      this.loading = true;
      this.error = null;
      try {
        const res = await fetch('/api/time-tracker');
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || data.error || res.statusText);
        this.entries = data.entries || [];
        this.summary = data.summary || this.summary;
        this.settings.eur_to_dzd_rate = data.eur_to_dzd_rate || this.settings.eur_to_dzd_rate;
      } catch (e) {
        this.error = e.message;
      } finally {
        this.loading = false;
      }
    },

    async saveRate() {
      this.error = null;
      try {
        const res = await fetch('/api/time-tracker/settings', {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            eur_to_dzd_rate: Number(this.settings.eur_to_dzd_rate),
          }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || data.error || res.statusText);
        this.settings.eur_to_dzd_rate = data.eur_to_dzd_rate;
        await this.load();
      } catch (e) {
        this.error = e.message;
      }
    },

    async save() {
      this.saving = true;
      this.error = null;
      if (this.durationToDecimal() <= 0) {
        this.error = 'Duration must be greater than zero';
        this.saving = false;
        return;
      }
      const payload = {
        work_date: this.form.work_date,
        task: this.form.task.trim(),
        notes: this.form.notes.trim(),
        hours: this.durationToDecimal(),
        hourly_rate: Number(this.form.hourly_rate || 7.5),
        status: this.form.status,
        paid: Boolean(this.form.paid),
      };

      try {
        const url = this.form.id
          ? `/api/time-tracker/entries/${encodeURIComponent(this.form.id)}`
          : '/api/time-tracker/entries';
        const res = await fetch(url, {
          method: this.form.id ? 'PATCH' : 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || data.error || res.statusText);
        this.resetForm();
        await this.load();
      } catch (e) {
        this.error = e.message;
      } finally {
        this.saving = false;
      }
    },

    edit(entry) {
      this.form = {
        id: entry.id,
        work_date: entry.work_date,
        task: entry.task,
        notes: entry.notes || '',
        ...this.decimalToDuration(entry.hours),
        hourly_rate: entry.hourly_rate || 7.5,
        status: entry.status || 'sent',
        paid: Boolean(entry.paid),
      };
      window.scrollTo({ top: 0, behavior: 'smooth' });
    },

    async togglePaid(entry) {
      await this.patch(entry.id, { paid: !entry.paid });
    },

    async patch(id, payload) {
      this.error = null;
      try {
        const res = await fetch(`/api/time-tracker/entries/${encodeURIComponent(id)}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || data.error || res.statusText);
        await this.load();
      } catch (e) {
        this.error = e.message;
      }
    },

    async remove(entry) {
      if (!confirm(`Delete "${entry.task}"?`)) return;
      this.error = null;
      try {
        const res = await fetch(`/api/time-tracker/entries/${encodeURIComponent(entry.id)}`, {
          method: 'DELETE',
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || data.error || res.statusText);
        await this.load();
      } catch (e) {
        this.error = e.message;
      }
    },

    resetForm() {
      this.form = {
        id: null,
        work_date: new Date().toISOString().slice(0, 10),
        task: '',
        notes: '',
        hoursPart: '',
        minutesPart: '',
        hourly_rate: window.__defaults__?.defaultHourlyRate ?? 7.5,
        status: 'sent',
        paid: false,
      };
    },

    money(value) {
      return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'EUR',
      }).format(Number(value || 0));
    },

    dzd(value) {
      return `${new Intl.NumberFormat('en-US', {
        maximumFractionDigits: 0,
      }).format(Number(value || 0))} DZD`;
    },

    entryAmount(entry) {
      return Number(entry.hours || 0) * Number(entry.hourly_rate || 0);
    },

    entryAmountDzd(entry) {
      return this.entryAmount(entry) * Number(this.settings.eur_to_dzd_rate || 0);
    },

    durationToDecimal() {
      const hours = Number(this.form.hoursPart || 0);
      const minutes = Number(this.form.minutesPart || 0);
      return Number((hours + minutes / 60).toFixed(4));
    },

    decimalToDuration(value) {
      const totalMinutes = Math.round(Number(value || 0) * 60);
      return {
        hoursPart: Math.floor(totalMinutes / 60),
        minutesPart: totalMinutes % 60,
      };
    },

    durationLabel(value) {
      const duration = this.decimalToDuration(value);
      if (!duration.hoursPart && !duration.minutesPart) return '0m';
      if (!duration.hoursPart) return `${duration.minutesPart}m`;
      if (!duration.minutesPart) return `${duration.hoursPart}h`;
      return `${duration.hoursPart}h ${duration.minutesPart}m`;
    },
  };
}
