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
                if (b.dataset.tr === 'journal') this.journalDialog(id);
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
                    <span class="d-inline-flex gap-1">
                        <button type="button" class="btn btn-paper btn-sm" data-tr="journal" data-metric="${m.id}" title="${esc(m.name)} journal" aria-label="${esc(m.name)} journal"><i class="fas fa-book"></i></button>
                        <button type="button" class="btn btn-paper btn-sm" data-tr="edit" data-metric="${m.id}" aria-label="Edit ${esc(m.name)}"><i class="fa fa-cog"></i></button>
                    </span>
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

    /**
     * "Each time I log, also ask me…" as plain questions instead of a syntax:
     * Ask me [where I was], answered [from a list ▾] like [home, office].
     */
    _questionHtml(f = {}) {
        const R = Resilient;
        const type = f.type || 'choice';
        return `<div class="rs-q"${f.key ? ` data-key="${esc(f.key)}"` : ''}>
            Ask me <input type="text" class="form-input" data-q="label" maxlength="40" value="${esc(f.label || '')}" placeholder="where I was">,
            answered ${R.pick('data-q="type"', type, [['choice', 'by picking from a list'], ['scale', 'with a rating out of 5'], ['text', 'in my own words']])}
            <span data-q-opts ${type === 'choice' ? '' : 'hidden'}>like <input type="text" class="form-input" data-q="options" value="${esc((f.options || []).join(', '))}" placeholder="home, office, outside"></span>
            <button type="button" class="tl-link ms-1" data-q-remove>remove</button>
        </div>`;
    },

    _bindQuestions(root) {
        const list = root.querySelector('[data-questions]');
        if (!list) return;
        root.addEventListener('click', (e) => {
            if (e.target.closest('[data-q-add]')) {
                list.insertAdjacentHTML('beforeend', this._questionHtml());
                const inputs = list.querySelectorAll('[data-q="label"]');
                inputs[inputs.length - 1].focus();
                resizeInputs(list);
            }
            const rm = e.target.closest('[data-q-remove]');
            if (rm) rm.closest('.rs-q').remove();
        });
        root.addEventListener('change', (e) => {
            const t = e.target.closest('[data-q="type"]');
            if (t) t.closest('.rs-q').querySelector('[data-q-opts]').hidden = t.value !== 'choice';
        });
    },

    _readQuestions(root) {
        const rows = [...root.querySelectorAll('.rs-q')];
        // Existing questions keep their key, so answers logged earlier stay linked
        const seen = new Set(rows.map(q => q.dataset.key).filter(Boolean));
        return rows.map(q => {
            const label = q.querySelector('[data-q="label"]').value.trim();
            if (!label) return null;
            if (q.dataset.key) return this._question(q, q.dataset.key, label);
            const base = label.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '').slice(0, 30) || 'note';
            let key = base, n = 2;
            while (seen.has(key)) key = `${base}_${n++}`;
            seen.add(key);
            return this._question(q, key, label);
        }).filter(Boolean);
    },

    _question(q, key, label) {
            const type = q.querySelector('[data-q="type"]').value;
            if (type === 'scale') return { key, label, type, max: 5 };
            if (type === 'choice') {
                const options = q.querySelector('[data-q="options"]').value.split(',').map(x => x.trim()).filter(Boolean);
                return { key, label, type, options, allow_other: true };
            }
            return { key, label, type: 'text' };
    },

    async editor(id) {
        const m = id ? this.metrics.find(x => x.id === id) : null;
        const hres = await apiClient.get('board/api/habits/', { silent: true });
        const habits = hres.status === 'success' ? (hres.data.results || hres.data) : [];
        const attached = new Set(m ? m.habit_ids : []);
        const v = (x, d = '') => esc(x == null ? d : x);
        const R = Resilient;
        const linked = m && m.habit_ids && m.habit_ids.length ? m.habit_ids[0] : '';
        const body = R.lead(m ? 'Change anything below.' : 'What would you like to keep an eye on?') + R.say(
            { need: true, msg: 'Pick one thing, like water, walks, coffee or pages read. The unit is optional.',
              html: `I want to track <input data-f="name" class="form-input" maxlength="64" value="${v(m && m.name)}" placeholder="water">
                     in <input data-f="unit" class="form-input" maxlength="16" value="${v(m && m.unit)}" placeholder="litres">` },
            { msg: 'Water adds up through the day, coffee is counted one cup at a time, sleep is one number for the day. The target is optional; Tab to skip.',
              html: `Each entry is ${R.pick('data-f="kind"', m ? m.kind : 'additive', [['additive', 'an amount that adds up'], ['counter', 'one more (a count)'], ['single', 'the day&rsquo;s one value']])},
                     and I&rsquo;m aiming for ${R.pick('data-f="direction"', m ? m.direction : 'at_least', [['at_least', 'at least'], ['at_most', 'at most']])}
                     <input data-f="target" type="number" step="any" class="form-input" value="${v(m && m.target)}" placeholder="3"> a day` },
            { msg: 'On Light days you can aim lower. Leave it empty to keep the same target.',
              html: `or <input data-f="target_light" type="number" step="any" class="form-input" value="${v(m && m.target_light)}" placeholder="2"> on Light days` },
            { msg: 'These become one-tap buttons on the card, so logging takes a second.',
              html: `Give me quick buttons for <input data-f="quick_steps" class="form-input" value="${v(m && (m.quick_steps || []).join(', '))}" placeholder="0.5, 1">` },
            { msg: 'A reminder puts a &ldquo;Log&rdquo; card on your timeline at that time. Or link it to a habit you already have.',
              html: `Remind me at <input data-f="remind_at" type="time" class="form-input" value="${v(m && m.remind_at)}"> every day,
                     and link it to ${R.pick('data-f="habit"', linked, [['', 'no habit'], ...habits.map(h => [h.id, esc(h.habit)])])}.` },
            { msg: 'Optional. Want to note something each time you log, like where you were or how you felt? Add a question and I&rsquo;ll ask it every time. Your answers help spot patterns.',
              html: `Each time I log, also ask me:
                     <div data-questions>${((m && m.fields) || []).map(f => this._questionHtml(f)).join('')}</div>
                     <button type="button" class="btn btn-paper btn-sm" data-q-add><i class="fas fa-plus me-1"></i>Add a question</button>` },
            { msg: 'Private trackers stay hidden until you unlock them with your PIN.',
              html: `Keep it ${R.pick('data-f="is_private"', m && m.is_private ? 'true' : 'false', [['false', 'visible'], ['true', 'private until I unlock']])}.` },
        );
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
            if (!name) return 'Tell me what you want to track';
            const steps = g('quick_steps').value.split(',').map(x => x.trim()).filter(Boolean).map(Number);
            if (steps.some(Number.isNaN)) return 'Quick-add buttons must be numbers';
            const payload = {
                name, unit: g('unit').value.trim(), kind: g('kind').value, direction: g('direction').value,
                target: g('target').value === '' ? null : Number(g('target').value),
                target_light: g('target_light').value === '' ? null : Number(g('target_light').value),
                quick_steps: steps, remind_at: g('remind_at').value || null,
                fields: this._readQuestions(ov), is_private: g('is_private').value === 'true',
            };
            const res = m ? await apiClient.put(`board/api/metrics/${m.id}/`, payload)
                          : await apiClient.post('board/api/metrics/', payload);
            if (res.status !== 'success') return res.error || 'Could not save the tracker';
            const metricId = res.data.id;
            const chosen = Number(g('habit').value) || null;
            if (chosen !== (Number(linked) || null)) {
                if (linked) await apiClient.patch(`board/api/habits/${linked}/`, { metric: null });
                if (chosen) await apiClient.patch(`board/api/habits/${chosen}/`, { metric: metricId });
            }
            await Resilient.loadMetrics();
            if (typeof Resilient._refresh === 'function') Resilient._refresh();
            return true;
        } });
        const dlg = Resilient.dialog(m ? `Edit ${m.name}` : 'New tracker', body, buttons, 'fa-chart-line', { revealAll: !!m });
        this._bindQuestions(dlg);
    },

    // ── Habit checklist ──────────────────────────────────────
    async stepsDialog(habitId, name) {
        const res = await apiClient.get(`board/api/habits/${habitId}/steps/`, { silent: true });
        if (res.status !== 'success') return;
        const steps = res.data.steps.filter(s => s.visible);
        const body = steps.length ? Resilient.lead('Tick each step as you do it.') + `<div class="conversational-form rs-steps">${steps.map(s => `
            <div class="convo-line form-check"><input class="form-check-input" type="checkbox" id="rs-st-${s.id}" data-step="${s.id}" ${s.done ? 'checked' : ''}>
            <label class="form-check-label" for="rs-st-${s.id}">${esc(s.name)}${s.target ? ` <small class="text-brown">${esc(s.target)}</small>` : ''}</label>
            ${s.how_to ? `<div class="rs-howto">${esc(s.how_to)}</div>` : ''}</div>`).join('')}</div>`
            : Resilient.lead('No steps yet. Add them from the habit&rsquo;s settings.');
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
        const form = document.getElementById('habitConvoForm');
        if (!form || document.getElementById('rs-habit-create')) return;
        const R = Resilient;
        const box = document.createElement('div');
        box.id = 'rs-habit-create';
        box.className = 'convo-line convo-step-2';
        box.style.display = 'none';
        box.innerHTML =
            `<div data-msg="Light days are for busy or low-energy days, Disrupted for travel or sickness. Should this habit still count then?">On Light days it&rsquo;s ${R.pick('data-hc="on_light"', 'required', [['required', 'still required'], ['excused', 'excused']])}
             and on Disrupted days ${R.pick('data-hc="on_disrupted"', 'excused', [['excused', 'excused'], ['required', 'still required']])}.</div>
             <div data-msg="Private habits stay hidden until you unlock them with your PIN.">Keep it ${R.pick('data-hc="is_private"', 'false', [['false', 'visible'], ['true', 'private until I unlock']])}.</div>
             <div data-msg="Break it into small steps, separated by commas. You can tick each one off. Optional.">The steps are <input type="text" data-hc="steps" class="form-input" placeholder="glute bridges, plank, bird dog"></div>`;
        box.addEventListener('focusin', (e) => {
            const line = e.target.closest('[data-msg]');
            const msg = document.getElementById('habit_message');
            if (line && msg) msg.innerHTML = line.dataset.msg;
        });
        form.appendChild(box);
        // Shown together with the reminder and days lines, after the identity is filled in
        const step = document.getElementById('habitFrequencyStep');
        if (step && typeof MutationObserver !== 'undefined') {
            new MutationObserver(() => { box.style.display = step.style.display; })
                .observe(step, { attributes: true, attributeFilter: ['style'] });
        }
    },

    /** Extra fields for the create-habit request. */
    habitExtras() {
        const g = (n) => document.querySelector(`#rs-habit-create [data-hc="${n}"]`);
        if (!g('on_light')) return {};
        return {
            on_light: g('on_light').value, on_disrupted: g('on_disrupted').value,
            is_private: g('is_private').value === 'true',
        };
    },

    async afterHabitCreated(habitId) {
        const ta = document.querySelector('#rs-habit-create [data-hc="steps"]');
        if (!ta) return;
        const names = ta.value.split(/[,\n]/).map(x => x.trim()).filter(Boolean);
        for (const name of names) await apiClient.post(`board/api/habits/${habitId}/steps/`, { name });
        document.querySelectorAll('#rs-habit-create [data-hc]').forEach(el => { el.value = el.tagName === 'SELECT' ? el.options[0].value : ''; });
    },

    /** One tracker's journal: every note logged with it, newest first. */
    async journalDialog(metricId) {
        const m = this.metrics.find(x => x.id === metricId);
        const jres = await apiClient.get('board/api/journal_books/', { silent: true });
        const book = jres.status === 'success' ? jres.data.find(j => j.metric === metricId) : null;
        let entries = [];
        if (book) {
            const r = await apiClient.get(`board/api/journal_books/${book.id}/entries/?limit=200`, { silent: true });
            entries = r.status === 'success' ? r.data : [];
        }
        const unit = m && m.unit ? ' ' + esc(m.unit) : '';
        const body = entries.length
            ? Resilient.lead(`${entries.length} note${entries.length > 1 ? 's' : ''} logged with ${esc(m ? m.name : 'this tracker')}.`) +
              entries.map(e => {
                  const { value, previous, ...rest } = e.metric || {};
                  const bits = Object.entries(rest).map(([k, v]) => `${esc(k)}: ${esc(v)}`);
                  const when = new Date(e.at).toLocaleString('en-US', { weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
                  return `<div class="tracker-note mb-2"><span class="tracker-note-time">${when}</span> ${esc(e.text)}
                      ${e.metric ? `<span class="tracker-note-meta">${esc(this._fmt(value))}${unit}${bits.length ? ' &middot; ' + bits.join(' &middot; ') : ''}</span>` : ''}</div>`;
              }).join('')
            : Resilient.lead(`No notes yet. When you log ${esc(m ? m.name.toLowerCase() : 'this tracker')}, add a note in the last line (&ldquo;and a note: &hellip;&rdquo;) and it lands here and in the Journal pane.`);
        Resilient.dialog(`${m ? m.name : 'Tracker'} journal`, body, [{ label: 'Close' }], 'fa-book');
    },

    // ── Journal pane: notes logged with trackers ─────────────
    /** Shown under the day's journal, grouped by tracker (each tracker has its own journal). */
    async journalNotes(dateStr) {
        const editor = document.getElementById('journal-editor');
        if (!editor) return;
        let box = document.getElementById('tracker-notes');
        if (!box) {
            box = document.createElement('div');
            box.id = 'tracker-notes';
            box.className = 'tracker-notes';
            editor.insertAdjacentElement('afterend', box);
        }
        const res = await apiClient.get(`board/api/journal_entries/?date=${dateStr}`, { silent: true });
        const items = res.status === 'success' ? res.data : [];
        if (!items.length) {
            box.innerHTML = `<h3 class="section-title mt-4 mb-2">From your trackers</h3>
                <p class="tracker-empty">No tracker notes on this day. When you log a tracker, add a note in the last line
                (&ldquo;and a note: &hellip;&rdquo;) and it shows up here. Each tracker&rsquo;s full journal is under the
                <i class="fas fa-book"></i> button on its card in Habits.</p>`;
            return;
        }
        const groups = {};
        items.forEach(e => (groups[e.journal_name] = groups[e.journal_name] || []).push(e));
        const clock = document.body.getAttribute('data-clock') || '12h';
        const t = (iso) => new Date(iso).toLocaleTimeString(clock === '24h' ? 'en-GB' : 'en-US',
            { hour: clock === '24h' ? '2-digit' : 'numeric', minute: '2-digit', hour12: clock !== '24h' });
        const detail = (e) => {
            if (!e.metric) return '';
            const { value, previous, ...rest } = e.metric;
            const bits = Object.entries(rest).map(([k, v]) => `${esc(k)}: ${esc(v)}`);
            return `<span class="tracker-note-meta">${esc(this._fmt(value))}${e.unit ? ' ' + esc(e.unit) : ''}${bits.length ? ' &middot; ' + bits.join(' &middot; ') : ''}</span>`;
        };
        box.innerHTML = `<h3 class="section-title mt-4 mb-2">From your trackers</h3>` +
            Object.entries(groups).map(([name, list]) => `
                <div class="tracker-note-group">
                    <h6>${esc(name)}</h6>
                    ${list.map(e => `<div class="tracker-note"><span class="tracker-note-time">${t(e.at)}</span> ${esc(e.text)} ${detail(e)}</div>`).join('')}
                </div>`).join('');
    },
};
