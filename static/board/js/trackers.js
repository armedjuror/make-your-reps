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

    init() {
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
        if (!this._themeObs && typeof MutationObserver !== 'undefined') {
            this._themeObs = new MutationObserver(() => { if (this.metrics.length) this.render(); });
            this._themeObs.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
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
        const grid = document.getElementById('trackerGrid');
        if (!grid) return;
        Object.values(this.charts).forEach(c => c.destroy());
        this.charts = {};
        const items = this.metrics;
        if (!items.length) {
            grid.innerHTML = '<div class="tracker-empty">No trackers yet. Add one to log things like water, walks or coffee and see how they trend.</div>';
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
                    <h5>${esc(m.name)}${m.is_private ? ' <i class="fas fa-lock small"></i>' : ''}</h5>
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
        const gray = css.getPropertyValue('--ink-gray').trim() || '#888';
        const accent = css.getPropertyValue('--accent-rgb').trim();
        const grid = accent ? `rgba(${accent}, .12)` : 'rgba(127,127,127,.15)';
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
                type: 'line', data: daily.map(d => d.target), borderColor: gray,
                borderDash: [5, 4], borderWidth: 1.5, pointRadius: 0, fill: false,
            });
        }
        if (this.charts[m.id]) this.charts[m.id].destroy();
        this.charts[m.id] = new Chart(canvas, {
            data: { labels: daily.map(d => d.date.slice(5)), datasets },
            options: {
                responsive: true, maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    x: { ticks: { maxTicksLimit: 6, color: gray }, grid: { color: grid } },
                    y: { beginAtZero: true, ticks: { color: gray, maxTicksLimit: 4 }, grid: { color: grid } },
                },
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
        const F = (l, c, h) => Resilient.field(l, c, h);
        const sel = (name, val, opts) => `<select data-f="${name}">${opts.map(([a, b]) =>
            `<option value="${a}" ${String(val) === a ? 'selected' : ''}>${b}</option>`).join('')}</select>`;
        const body =
            F('Name', `<input data-f="name" maxlength="64" value="${v(m && m.name)}" placeholder="Water, Walk, Coffee">`) +
            F('Unit', `<input data-f="unit" maxlength="16" value="${v(m && m.unit)}" placeholder="l, min, cups">`) +
            F('What are you tracking?', sel('kind', m ? m.kind : 'additive', [['counter', 'A count (+1 each time)'], ['additive', 'An amount that adds up through the day'], ['single', 'One value per day (like sleep)']])) +
            F('Goal', sel('direction', m ? m.direction : 'at_least', [['at_least', 'At least'], ['at_most', 'At most']])) +
            F('Daily target', `<input data-f="target" type="number" step="any" value="${v(m && m.target)}" placeholder="Optional">`) +
            F('Target on Light days', `<input data-f="target_light" type="number" step="any" value="${v(m && m.target_light)}" placeholder="Optional">`) +
            F('Quick-add buttons', `<input data-f="quick_steps" value="${v(m && (m.quick_steps || []).join(', '))}" placeholder="1, 5, 10">`, 'Comma separated') +
            F('Daily reminder', `<input data-f="remind_at" type="time" value="${v(m && m.remind_at)}">`, 'Adds a &ldquo;Log&rdquo; card to the timeline at this time') +
            `<label class="form-label">Or attach to habits</label><div class="rs-scroll">${habits.length
                ? habits.map(h => Resilient.check(`data-habit="${h.id}"`, esc(h.habit), attached.has(h.id))).join('')
                : '<div class="form-text">No habits yet</div>'}</div>` +
            F('Extra details to capture', `<textarea data-f="fields" rows="3" placeholder="Where: home, office, outside&#10;Mood: scale 5&#10;Note">${v(this._fieldsToText(m && m.fields))}</textarea>`,
              'One per line. &ldquo;Label: a, b, c&rdquo; gives choices; &ldquo;Label: scale 5&rdquo; gives a 1&ndash;5 rating.') +
            `<div class="mt-3">${Resilient.check('data-f="is_private"', 'Private (hidden until unlocked)', m && m.is_private)}</div>`;
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
        Resilient.dialog(m ? `Edit ${m.name}` : 'New tracker', body, buttons, 'fa-chart-line');
    },

    // ── Habit checklist ──────────────────────────────────────
    async stepsDialog(habitId, name) {
        const res = await apiClient.get(`board/api/habits/${habitId}/steps/`, { silent: true });
        if (res.status !== 'success') return;
        const steps = res.data.steps.filter(s => s.visible);
        const body = steps.length ? `<div class="rs-steps">${steps.map(s => `
            <div class="form-check"><input class="form-check-input" type="checkbox" id="rs-st-${s.id}" data-step="${s.id}" ${s.done ? 'checked' : ''}>
            <label class="form-check-label" for="rs-st-${s.id}">${esc(s.name)}${s.target ? ` <small class="text-brown">(${esc(s.target)})</small>` : ''}</label>
            ${s.how_to ? `<div class="form-text">${esc(s.how_to)}</div>` : ''}</div>`).join('')}</div>`
            : '<p>No steps yet. Add them from the habit settings.</p>';
        const ov = Resilient.dialog(name, body, [{ label: 'Close', run: async () => {
            if (typeof loadHabits === 'function') loadHabits();
            Resilient._refresh();
            return true;
        } }], 'fa-list-check');
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
        const sel = (k, opts) => `<select data-hc="${k}" class="form-control">${opts.map(([v, l]) => `<option value="${v}">${l}</option>`).join('')}</select>`;
        box.innerHTML = `<summary class="text-brown">More options</summary>
            <div class="mt-2">
                ${Resilient.field('On Light days', sel('on_light', [['required', 'Still required'], ['excused', 'Excused']]))}
                ${Resilient.field('On Disrupted days', sel('on_disrupted', [['excused', 'Excused'], ['required', 'Still required']]))}
                <div class="mt-3">${Resilient.check('data-hc="is_private"', 'Private (hidden until you unlock)')}
                ${Resilient.check('data-hc="private_reminder"', 'Show a plain &ldquo;Reminder&rdquo; while locked')}</div>
                ${Resilient.field('Checklist steps', '<textarea data-hc="steps" class="form-control" rows="3" placeholder="Glute bridges&#10;Plank&#10;Bird dog"></textarea>', 'One per line, optional')}
            </div>`;
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
