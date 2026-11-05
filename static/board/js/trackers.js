/**
 * trackers.js — Trackers (metrics) on the Trackers pane: a multi-row grid of
 * cards, each with today's value, quick logging, a reminder time or attached
 * habits, and a chart. Also the habit checklist dialog and the extra options
 * on the New Habit modal.
 *
 * No inline handlers (works under the extension's MV3 CSP).
 */
const Trackers = {
    metrics: [],
    charts: {},
    DAYS: 30,

    _css() {
        if (document.getElementById('trackers-css')) return;
        const s = document.createElement('style');
        s.id = 'trackers-css';
        s.textContent = `
        .tracker-grid{display:flex;flex-wrap:wrap;gap:14px}
        .tracker-card{flex:1 1 300px;max-width:480px;border:1px solid rgba(var(--accent-rgb),.3);border-radius:12px;padding:12px 14px;display:flex;flex-direction:column;gap:6px}
        .tracker-card.tr-over{border-color:#c0392b}
        .tracker-card.tr-met{border-color:#2e8b57}
        .tracker-head{display:flex;justify-content:space-between;align-items:center;gap:8px}
        .tracker-head h5{margin:0;font-size:1rem}
        .tracker-value{font-size:1.4rem;font-weight:600}
        .tracker-value small{font-size:.8rem;font-weight:400;opacity:.7}
        .tracker-actions{display:flex;flex-wrap:wrap;gap:6px;align-items:center}
        .tracker-meta{font-size:.75rem;opacity:.7}
        .tracker-chart{position:relative;height:130px}
        .tracker-empty{opacity:.7;font-size:.9rem;padding:8px 0}
        `;
        document.head.appendChild(s);
    },

    init() {
        this._css();
        const grid = document.getElementById('trackerGrid');
        if (grid && !grid.dataset.bound) {
            grid.dataset.bound = '1';
            grid.addEventListener('click', (e) => {
                const b = e.target.closest('[data-tr]');
                if (!b) return;
                const id = Number(b.dataset.metric);
                if (b.dataset.tr === 'edit') this.editor(id);
            });
        }
        const add = document.getElementById('new-tracker-btn');
        if (add && !add.dataset.bound) {
            add.dataset.bound = '1';
            add.addEventListener('click', () => this.editor(null));
        }
        // Habit modal extras and checklist buttons
        this._bindHabitCreate();
        if (!this._docBound) {
            this._docBound = true;
            document.addEventListener('click', (e) => {
                const b = e.target.closest('[data-tr="habit-steps"]');
                if (b) this.stepsDialog(Number(b.dataset.habit), b.dataset.name || 'Checklist');
            });
        }
        Resilient.loadMetrics();
    },

    /** Called by Resilient whenever the metric list has been (re)loaded. */
    onMetrics(metrics) {
        this.metrics = metrics;
        if (document.getElementById('trackerGrid')) this.render();
    },

    _fmt(n) { return Number.isInteger(n) ? String(n) : String(Math.round(n * 100) / 100); },

    render() {
        this._css();
        const grid = document.getElementById('trackerGrid');
        if (!grid) return;
        Object.values(this.charts).forEach(c => c.destroy());
        this.charts = {};
        const items = this.metrics;
        if (!items.length) {
            grid.innerHTML = '<div class="tracker-empty">No trackers yet. Add one to log things like water, walks or cigarettes and see how they trend.</div>';
            return;
        }
        grid.innerHTML = items.map(m => {
            const t = m.today_target;
            const over = m.direction === 'at_most' && t != null && m.today > t;
            const met = m.direction === 'at_least' && t != null && m.today >= t;
            const goal = t != null ? `<small> / ${this._fmt(t)} ${esc(m.unit || '')} ${m.direction === 'at_most' ? 'max' : ''}</small>` : `<small> ${esc(m.unit || '')}</small>`;
            const steps = (m.kind === 'counter' || m.kind === 'additive')
                ? (m.quick_steps && m.quick_steps.length ? m.quick_steps : [1]).map(s =>
                    `<button type="button" class="btn btn-paper btn-sm" data-rs="metric-add" data-metric="${m.id}" data-val="${s}">+${this._fmt(s)}</button>`).join('')
                : '';
            const meta = [];
            if (m.remind_at) meta.push(`<i class="fas fa-bell"></i> ${esc(m.remind_at)}`);
            if (m.habit_ids && m.habit_ids.length) meta.push(`<i class="fas fa-link"></i> attached to ${m.habit_ids.length} habit${m.habit_ids.length > 1 ? 's' : ''}`);
            if (!meta.length) meta.push('No reminder or habit attached');
            return `<div class="tracker-card ${over ? 'tr-over' : ''} ${met ? 'tr-met' : ''}" data-metric="${m.id}">
                <div class="tracker-head">
                    <h5>${esc(m.name)}${m.is_private ? ' <i class="fas fa-lock" style="font-size:.7em"></i>' : ''}</h5>
                    <button type="button" class="btn btn-paper btn-sm" data-tr="edit" data-metric="${m.id}" aria-label="Edit ${esc(m.name)}"><i class="fa fa-cog"></i></button>
                </div>
                <div class="tracker-value">${this._fmt(m.today)}${goal}</div>
                <div class="tracker-actions">
                    ${steps}
                    <button type="button" class="btn btn-paper btn-sm btn-primary" data-rs="metric-open" data-metric="${m.id}"><i class="fas fa-plus"></i> Add entry</button>
                    <button type="button" class="rs-link" data-rs="metric-undo" data-metric="${m.id}">Undo</button>
                </div>
                <div class="tracker-meta">${meta.join(' &middot; ')}</div>
                <div class="tracker-chart"><canvas id="tracker-chart-${m.id}"></canvas></div>
            </div>`;
        }).join('');
        items.forEach(m => this._chart(m));
    },

    async _chart(m) {
        const res = await apiClient.get(`board/api/metrics/${m.id}/insights/?days=${this.DAYS}`, { silent: true });
        const canvas = document.getElementById(`tracker-chart-${m.id}`);
        if (res.status !== 'success' || !canvas || typeof Chart === 'undefined') return;
        const daily = res.data.daily;
        const css = getComputedStyle(document.body);
        const brown = css.getPropertyValue('--ink-brown').trim() || 'rgb(142,110,58)';
        const light = css.getPropertyValue('--ink-brown-light').trim() || 'rgba(184,156,125,0.25)';
        const hasTarget = daily.some(d => d.target != null);
        const datasets = [{
            type: m.kind === 'single' ? 'line' : 'bar',
            data: daily.map(d => d.value),
            borderColor: brown, backgroundColor: m.kind === 'single' ? light : brown,
            borderWidth: 2, pointRadius: m.kind === 'single' ? 3 : 0, tension: 0.25,
            fill: m.kind === 'single',
        }];
        if (hasTarget) {
            datasets.push({
                type: 'line', data: daily.map(d => d.target), borderColor: '#2e8b57',
                borderDash: [5, 4], borderWidth: 1.5, pointRadius: 0, fill: false,
            });
        }
        if (this.charts[m.id]) this.charts[m.id].destroy();
        this.charts[m.id] = new Chart(canvas, {
            data: { labels: daily.map(d => d.date.slice(5)), datasets },
            options: {
                responsive: true, maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: { x: { ticks: { maxTicksLimit: 6 } }, y: { beginAtZero: true } },
            },
        });
    },

    // ── Create / edit ────────────────────────────────────────
    _slug(label) {
        return label.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '').slice(0, 30) || 'field';
    },

    _fieldsToText(fields) {
        return (fields || []).map(f => f.type === 'choice' ? `${f.label}: ${(f.options || []).join(', ')}`
            : f.type === 'scale' ? `${f.label}: scale ${f.max || 10}` : f.label).join('\n');
    },

    _textToFields(text) {
        const seen = new Set();
        return text.split('\n').map(l => l.trim()).filter(Boolean).map(line => {
            const [label, rest] = line.split(/:(.*)/s).map(x => x && x.trim());
            let key = this._slug(label), n = 2;
            while (seen.has(key)) key = `${this._slug(label)}_${n++}`;
            seen.add(key);
            if (!rest) return { key, label, type: 'text' };
            const sc = rest.match(/^scale\s*(\d+)?$/i);
            if (sc) return { key, label, type: 'scale', max: Number(sc[1] || 10) };
            return { key, label, type: 'choice', options: rest.split(',').map(x => x.trim()).filter(Boolean), allow_other: true };
        });
    },

    async editor(id) {
        const m = id ? this.metrics.find(x => x.id === id) : null;
        const hres = await apiClient.get('board/api/habits/', { silent: true });
        const habits = hres.status === 'success' ? (hres.data.results || hres.data) : [];
        const attached = new Set(m ? m.habit_ids : []);
        const v = (x, d = '') => esc(x == null ? d : x);
        const sel = (name, val, opts) => `<select data-f="${name}">${opts.map(([a, b]) =>
            `<option value="${a}" ${String(val) === a ? 'selected' : ''}>${b}</option>`).join('')}</select>`;
        const body = `
            <label>Name</label><input data-f="name" maxlength="64" value="${v(m && m.name)}" placeholder="Water, Walk, Cigarettes">
            <label>Unit</label><input data-f="unit" maxlength="16" value="${v(m && m.unit)}" placeholder="l, min, count">
            <label>What are you tracking?</label>
            ${sel('kind', m ? m.kind : 'additive', [['counter', 'A count (+1 each time)'], ['additive', 'An amount that adds up through the day'], ['single', 'One value per day (like sleep)']])}
            <label>Goal</label>
            ${sel('direction', m ? m.direction : 'at_least', [['at_least', 'At least'], ['at_most', 'At most']])}
            <input data-f="target" type="number" step="any" value="${v(m && m.target)}" placeholder="Daily target (optional)">
            <input data-f="target_light" type="number" step="any" value="${v(m && m.target_light)}" placeholder="Target on Light days (optional)">
            <label>Quick-add buttons (comma separated)</label><input data-f="quick_steps" value="${v(m && (m.quick_steps || []).join(', '))}" placeholder="1, 5, 10">
            <label>Daily reminder time</label><input data-f="remind_at" type="time" value="${v(m && m.remind_at)}">
            <label>Or attach to habits</label>
            <div style="max-height:110px;overflow:auto;margin-bottom:6px">${habits.length ? habits.map(h =>
                `<label style="display:block;font-size:.85rem"><input type="checkbox" data-habit="${h.id}" ${attached.has(h.id) ? 'checked' : ''}> ${esc(h.habit)}</label>`).join('') : '<small>No habits yet</small>'}</div>
            <label>Extra details to capture (one per line)</label>
            <textarea data-f="fields" rows="3" placeholder="Trigger: after meal, stress, boredom&#10;Urge: scale 5&#10;Note">${v(this._fieldsToText(m && m.fields))}</textarea>
            <label style="font-size:.85rem"><input type="checkbox" data-f="is_private" ${m && m.is_private ? 'checked' : ''}> Private (hidden until unlocked)</label>`;
        const buttons = [{ label: 'Cancel' }];
        if (m && !m.is_system) buttons.unshift({ label: 'Delete', run: async () => {
            const r = await apiClient.delete(`board/api/metrics/${m.id}/`);
            if (r.status !== 'success') return r.error || 'Could not delete';
            await Resilient.loadMetrics();
            return true;
        } });
        buttons.push({ label: m ? 'Save' : 'Add tracker', primary: true, run: async (ov) => {
            const g = (n) => ov.querySelector(`[data-f="${n}"]`);
            const name = g('name').value.trim();
            if (!name) return 'Give the tracker a name';
            const steps = g('quick_steps').value.split(',').map(x => x.trim()).filter(Boolean).map(Number);
            if (steps.some(Number.isNaN)) return 'Quick-add buttons must be numbers';
            const payload = {
                name, unit: g('unit').value.trim(), kind: g('kind').value, direction: g('direction').value,
                target: g('target').value === '' ? null : Number(g('target').value),
                target_light: g('target_light').value === '' ? null : Number(g('target_light').value),
                quick_steps: steps, remind_at: g('remind_at').value || null,
                fields: this._textToFields(g('fields').value), is_private: g('is_private').checked,
            };
            const res = m ? await apiClient.put(`board/api/metrics/${m.id}/`, payload)
                          : await apiClient.post('board/api/metrics/', payload);
            if (res.status !== 'success') return res.error || 'Could not save the tracker';
            const metricId = res.data.id;
            const chosen = new Set([...ov.querySelectorAll('[data-habit]:checked')].map(x => Number(x.dataset.habit)));
            for (const h of habits) {
                const was = attached.has(h.id), now = chosen.has(h.id);
                if (now && !was) await apiClient.patch(`board/api/habits/${h.id}/`, { metric: metricId });
                if (!now && was) await apiClient.patch(`board/api/habits/${h.id}/`, { metric: null });
            }
            await Resilient.loadMetrics();
            if (typeof Resilient._refresh === 'function') Resilient._refresh();
            return true;
        } });
        const ov = Resilient.dialog(m ? `Edit ${m.name}` : 'New tracker', body, buttons);
        ov.querySelector('.rs-dialog').style.cssText += ';max-height:90vh;overflow:auto;width:min(94vw,420px)';
    },

    // ── Habit checklist ──────────────────────────────────────
    async stepsDialog(habitId, name) {
        const res = await apiClient.get(`board/api/habits/${habitId}/steps/`, { silent: true });
        if (res.status !== 'success') return;
        const steps = res.data.steps.filter(s => s.visible);
        const body = steps.length ? `<div class="rs-steps">${steps.map(s => `
            <label><input type="checkbox" data-step="${s.id}" ${s.done ? 'checked' : ''}> ${esc(s.name)}${s.target ? ` <small>(${esc(s.target)})</small>` : ''}</label>
            ${s.how_to ? `<small style="opacity:.65;margin-left:22px">${esc(s.how_to)}</small>` : ''}`).join('')}</div>`
            : '<p>No steps yet. Add them from the habit settings.</p>';
        const ov = Resilient.dialog(name, body, [{ label: 'Close', run: async () => {
            if (typeof loadHabits === 'function') loadHabits();
            Resilient._refresh();
            return true;
        } }]);
        ov.addEventListener('change', async (e) => {
            const cb = e.target.closest('[data-step]');
            if (!cb) return;
            const r = await apiClient.put(`board/api/habit_steps/${cb.dataset.step}/log/`, {
                done: cb.checked, date: Resilient.logicalToday(),
            });
            if (r.status !== 'success') cb.checked = !cb.checked;
        });
    },

    // ── New Habit modal extras ───────────────────────────────
    _bindHabitCreate() {
        const modal = document.getElementById('habitModal');
        if (!modal || document.getElementById('rs-habit-create')) return;
        const body = modal.querySelector('.modal-body');
        const box = document.createElement('details');
        box.id = 'rs-habit-create';
        box.className = 'mt-3';
        box.innerHTML = `<summary style="cursor:pointer">More options</summary>
            <div class="small mt-2">On Light days
                <select data-hc="on_light" class="form-control form-control-sm d-inline-block" style="width:auto"><option value="required">still required</option><option value="excused">excused</option></select></div>
            <div class="small mt-1">On Disrupted days
                <select data-hc="on_disrupted" class="form-control form-control-sm d-inline-block" style="width:auto"><option value="excused">excused</option><option value="required">still required</option></select></div>
            <label class="small d-block mt-1"><input type="checkbox" data-hc="is_private"> Private (hidden until you unlock)</label>
            <label class="small d-block"><input type="checkbox" data-hc="private_reminder"> Show a plain &ldquo;Reminder&rdquo; while locked</label>
            <label class="small d-block mt-2">Checklist steps, one per line (optional)</label>
            <textarea data-hc="steps" class="form-control form-control-sm" rows="3" placeholder="Glute bridges&#10;Plank&#10;Bird dog"></textarea>`;
        body.appendChild(box);
    },

    /** Extra fields for the create-habit request. */
    habitExtras() {
        const g = (n) => document.querySelector(`#rs-habit-create [data-hc="${n}"]`);
        if (!g('on_light')) return {};
        return {
            on_light: g('on_light').value, on_disrupted: g('on_disrupted').value,
            is_private: g('is_private').checked, private_reminder: g('private_reminder').checked,
        };
    },

    async afterHabitCreated(habitId) {
        const ta = document.querySelector('#rs-habit-create [data-hc="steps"]');
        if (!ta) return;
        const names = ta.value.split('\n').map(x => x.trim()).filter(Boolean);
        for (const name of names) await apiClient.post(`board/api/habits/${habitId}/steps/`, { name });
        document.querySelectorAll('#rs-habit-create [data-hc]').forEach(el => {
            if (el.type === 'checkbox') el.checked = false; else if (el.tagName === 'TEXTAREA') el.value = '';
        });
    },
};
