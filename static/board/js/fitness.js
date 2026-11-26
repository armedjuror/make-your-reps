/**
 * fitness.js — the Fitness tab: today's targets, today's workout, the
 * Health / Activity checklists, the program calendar, body trackers and diet.
 *
 * No inline handlers: one delegated listener on the pane (data-fit="..."),
 * so the same file runs in the extension (MV3 CSP).
 */
const Fitness = {
    data: null,
    month: null,
    calendar: null,
    exercises: {},
    _bound: false,

    esc(s) { return (typeof Resilient !== 'undefined') ? Resilient.esc(s) : String(s == null ? '' : s); },
    fmt(n) { return n == null ? '–' : (Math.round(n * 10) / 10).toLocaleString(); },
    root() { return document.getElementById('fitness-root'); },
    /** Absolute URL for a server path, so stills load in the extension too. */
    url(u) { return u && u.startsWith('/') && typeof HOST !== 'undefined' ? HOST.replace(/\/$/, '') + u : u; },

    async init() {
        this.bind();
        await this.load();
    },

    async load() {
        const res = await apiClient.get('board/api/fitness/overview/', { silent: true });
        if (res.status !== 'success') {
            this.root().innerHTML = '<div class="tracker-empty">Couldn&rsquo;t load your fitness plan. Try again in a moment.</div>';
            return;
        }
        this.data = res.data;
        if (!this.month) this.month = (res.data.today || res.data.date).slice(0, 7);
        this.render();
        this.loadCalendar();
        this.loadBodyCharts();
    },

    bind() {
        if (this._bound) return;
        this._bound = true;
        document.addEventListener('click', (e) => {
            const el = e.target.closest('[data-fit]');
            if (!el || !el.closest('#pane-fitness, .fit-modal')) return;
            const act = el.dataset.fit;
            if (act === 'add') this.logMetric(+el.dataset.metric, +el.dataset.val);
            else if (act === 'log') this.logDialog(+el.dataset.metric);
            else if (act === 'undo') this.undo(+el.dataset.metric);
            else if (act === 'exercise') this.exerciseDialog(el.dataset.id);
            else if (act === 'month') this.shiftMonth(+el.dataset.dir);
            else if (act === 'day') this.dayDialog(el.dataset.date);
            else if (act === 'start') this.start();
        });
        document.addEventListener('change', (e) => {
            const cb = e.target.closest('input[data-fit="step"]');
            if (cb && cb.closest('#pane-fitness')) this.tick(cb);
        });
    },

    // ── Render ────────────────────────────────────────────────
    render() {
        const d = this.data;
        if (!d.activity && !d.health) {
            this.root().innerHTML = `<div class="section fit-empty">
                <h3 class="section-title">Fitness</h3>
                <p>No fitness plan yet. Your plan, workouts, water and protein will live here.</p>
            </div>`;
            return;
        }
        this.root().innerHTML = [
            this.headHtml(), this.ringsHtml(), this.workoutHtml(), this.checklistsHtml(),
            this.calendarShell(), this.bodyHtml(), this.dietHtml(),
        ].join('');
    },

    headHtml() {
        const p = this.data.program;
        const sub = p ? `${this.esc(p.name)}${p.week ? ` &middot; week ${p.week}` : ''}${p.phase ? ` &middot; ${this.esc(p.phase)}` : ''}` : 'No active program';
        return `<div class="fit-head"><h3 class="section-title mb-0">Fitness</h3><div class="fit-sub">${sub}</div></div>`;
    },

    tracker(key) { return (this.data.trackers || []).find(t => t.key === key); },

    ring(t, label) {
        if (!t) return '';
        const pct = t.target ? Math.min(1, t.today / t.target) : 0;
        const C = 2 * Math.PI * 34;
        const quick = (t.quick_steps || []).map(q =>
            `<button type="button" class="btn btn-paper btn-sm" data-fit="add" data-metric="${t.id}" data-val="${q}">+${this.fmt(q)}</button>`).join('');
        return `<div class="fit-ring-card ${pct >= 1 ? 'met' : ''}">
            <div class="fit-ring" role="img" aria-label="${this.esc(label)}: ${this.fmt(t.today)} of ${this.fmt(t.target)} ${this.esc(t.unit)}">
                <svg viewBox="0 0 80 80"><circle class="score-bg" cx="40" cy="40" r="34"/>
                <circle class="score-fill" cx="40" cy="40" r="34" style="stroke-dasharray:${C};stroke-dashoffset:${C * (1 - pct)}"/></svg>
                <div class="fit-ring-val">${this.fmt(t.today)}<small>${t.target ? '/' + this.fmt(t.target) : ''}</small></div>
            </div>
            <div class="fit-ring-label">${this.esc(label)} <small>${this.esc(t.unit)}</small></div>
            <div class="fit-ring-actions">${quick}
                <button type="button" class="btn btn-paper btn-sm" data-fit="log" data-metric="${t.id}" aria-label="Log ${this.esc(label)}"><i class="fas fa-pen"></i></button>
                <button type="button" class="rs-link" data-fit="undo" data-metric="${t.id}">Undo</button></div>
        </div>`;
    },

    ringsHtml() {
        const rings = [this.ring(this.tracker('water'), 'Water'), this.ring(this.tracker('protein'), 'Protein'),
                       this.ring(this.tracker('steps'), 'Steps'), this.ring(this.tracker('kcal'), 'Calories')].join('');
        return `<div class="section"><h5 class="fit-h">Today&rsquo;s targets</h5><div class="fit-rings">${rings}</div></div>`;
    },

    workoutHtml() {
        const a = this.data.activity;
        if (!a) return '';
        const kind = a.day && a.day.kind;
        let body;
        if (kind === 'session' && a.session) {
            const s = a.session;
            const items = s.blocks.filter(b => !['warmup', 'cooldown'].includes(b.block)).flatMap(b => b.items);
            const warm = s.blocks.filter(b => b.block === 'warmup').flatMap(b => b.items).map(i => this.esc(i.name)).join(', ');
            body = `<div class="fit-workout-title">${this.esc(s.name)} <small>&middot; ${s.exercise_count} exercises</small></div>
                ${warm ? `<div class="fit-muted">Warm-up: ${warm}</div>` : ''}
                <div class="fit-ex-list">${items.map(i => `
                    <button type="button" class="fit-ex" data-fit="exercise" data-id="${this.esc(i.exercise)}">
                        ${i.still ? `<img src="${this.url(i.still)}" alt="" loading="lazy">` : '<span class="fit-ex-noimg"><i class="fas fa-dumbbell"></i></span>'}
                        <span class="fit-ex-name">${this.esc(i.name)}</span><span class="fit-ex-dose">${this.esc(i.dose)}</span>
                    </button>`).join('')}</div>
                <div class="fit-workout-actions">
                    <button type="button" class="btn btn-paper btn-primary" data-fit="start" ${typeof FocusPlayer === 'undefined' ? 'disabled title="The workout player is coming next"' : ''}><i class="fas fa-play"></i> Start workout</button>
                </div>`;
        } else if (kind === 'walk') {
            body = `<div class="fit-workout-title">Walk day</div><div class="fit-muted">Get your steps in. No workout today.</div>`;
        } else if (kind === 'rest') {
            body = `<div class="fit-workout-title">Rest day</div><div class="fit-muted">Recovery is part of the plan. It counts for your Activity streak.</div>`;
        } else {
            const p = this.data.program;
            body = `<div class="fit-muted">${p && p.start_date > this.data.date ? `Your plan starts ${new Date(p.start_date + 'T00:00').toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'short' })}.` : 'Nothing planned today.'}</div>`;
        }
        const preview = (this.data.preview || []).map(p => `<span class="fit-pre fit-k-${p.kind || 'none'}" title="${this.esc(p.name)}">
            ${new Date(p.date + 'T00:00').toLocaleDateString(undefined, { weekday: 'short' })}<i class="fas ${this.kindIcon(p.kind)}"></i></span>`).join('');
        return `<div class="section"><h5 class="fit-h">Today&rsquo;s workout</h5>${body}
            ${preview ? `<div class="fit-preview" aria-label="Next 6 days">${preview}</div>` : ''}</div>`;
    },

    kindIcon(k) { return { session: 'fa-dumbbell', walk: 'fa-walking', rest: 'fa-bed' }[k] || 'fa-minus'; },

    checklist(block, title) {
        if (!block) return '';
        const steps = (block.steps || []).map(s => `
            <div class="form-check fit-step">
                <input class="form-check-input" type="checkbox" id="fit-step-${s.id}" data-fit="step" data-habit="${block.habit_id}" data-step="${s.id}" ${s.done ? 'checked' : ''} ${s.id ? '' : 'disabled'}>
                <label class="form-check-label" for="fit-step-${s.id}">${this.esc(s.name)}${s.target ? ` <small>${this.esc(s.target)}</small>` : ''}
                ${s.linked ? `<i class="fas fa-link fit-linked" title="Ticks itself from your tracker"></i>` : ''}</label>
            </div>`).join('');
        return `<div class="fit-check"><div class="fit-check-head"><h6>${this.esc(title)}</h6>
            <span class="fit-streak" title="Current streak"><i class="fas fa-fire"></i> ${block.streak || 0}</span></div>
            ${steps || '<div class="fit-muted">Nothing to do today.</div>'}</div>`;
    },

    checklistsHtml() {
        return `<div class="section"><h5 class="fit-h">Habits</h5><div class="fit-checks">
            ${this.checklist(this.data.activity, 'Activity')}${this.checklist(this.data.health, 'Health')}</div></div>`;
    },

    // ── Calendar ──────────────────────────────────────────────
    calendarShell() {
        return `<div class="section"><div class="fit-cal-head"><h5 class="fit-h mb-0">Workout schedule</h5>
            <span><button type="button" class="btn btn-paper btn-sm" data-fit="month" data-dir="-1" aria-label="Previous month"><i class="fas fa-chevron-left"></i></button>
            <span class="fit-cal-month" id="fit-cal-month"></span>
            <button type="button" class="btn btn-paper btn-sm" data-fit="month" data-dir="1" aria-label="Next month"><i class="fas fa-chevron-right"></i></button></span></div>
            <div class="fit-cal" id="fit-cal"></div></div>`;
    },

    shiftMonth(dir) {
        const [y, m] = this.month.split('-').map(Number);
        const d = new Date(y, m - 1 + dir, 1);
        this.month = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
        this.loadCalendar();
    },

    async loadCalendar() {
        const el = document.getElementById('fit-cal');
        if (!el) return;
        const res = await apiClient.get(`board/api/fitness/calendar/?month=${this.month}`, { silent: true });
        if (res.status !== 'success') return;
        const days = res.data.days;
        const [y, m] = this.month.split('-').map(Number);
        document.getElementById('fit-cal-month').textContent = new Date(y, m - 1, 1).toLocaleDateString(undefined, { month: 'long', year: 'numeric' });
        const lead = (new Date(y, m - 1, 1).getDay() + 6) % 7;   // Monday first
        const today = this.data.today;
        const heads = ['M', 'T', 'W', 'T', 'F', 'S', 'S'].map(h => `<div class="fit-cal-dow">${h}</div>`).join('');
        const cells = Array(lead).fill('<div></div>').concat(days.map(d => `
            <button type="button" class="fit-cal-day fit-k-${d.kind || 'none'} ${d.done ? 'done' : ''} ${d.date === today ? 'today' : ''}"
                data-fit="day" data-date="${d.date}" title="${this.esc(d.name || 'Nothing planned')}" ${d.kind ? '' : 'disabled'}>
                <span>${+d.date.slice(8)}</span>${d.kind ? `<i class="fas ${this.kindIcon(d.kind)}"></i>` : ''}
            </button>`));
        el.innerHTML = heads + cells.join('');
    },

    async dayDialog(date) {
        const res = await apiClient.get(`board/api/fitness/days/${date}/`, { silent: true });
        if (res.status !== 'success') return;
        const d = res.data;
        const label = new Date(date + 'T00:00').toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long' });
        const list = d.steps.length ? `<ul class="fit-day-list">${d.steps.map(s => `<li>${this.esc(s.name)}${s.target ? ` <small>${this.esc(s.target)}</small>` : ''}</li>`).join('')}</ul>` : '<p class="fit-muted">Nothing planned.</p>';
        const el = Resilient.dialog(`${d.day.name || 'Day'} · ${label}`, list, [{ label: 'Close', primary: true }], 'fa-calendar-day');
        el.classList.add('fit-modal');
    },

    // ── Body trackers + diet ──────────────────────────────────
    bodyHtml() {
        const cards = ['weight', 'waist'].map(k => this.tracker(k)).filter(Boolean).map(t => `
            <div class="tracker-card"><div class="tracker-head"><h5>${this.esc(t.name)}${t.is_private ? ' <i class="fas fa-lock small"></i>' : ''}</h5>
                <button type="button" class="btn btn-paper btn-sm btn-primary" data-fit="log" data-metric="${t.id}"><i class="fas fa-plus"></i> Log</button></div>
                <div class="tracker-value">${t.today ? this.fmt(t.today) : '–'}<small> ${this.esc(t.unit)} today</small></div>
                <div class="tracker-chart"><canvas id="fit-chart-${t.key}"></canvas></div></div>`).join('');
        return cards ? `<div class="section"><h5 class="fit-h">Body</h5><div class="tracker-grid">${cards}</div>
            <div class="fit-muted mt-2">Weigh in once a week, right after waking. Trends matter more than single days.</div></div>` : '';
    },

    async loadBodyCharts() {
        if (typeof Chart === 'undefined') return;
        for (const k of ['weight', 'waist']) {
            const t = this.tracker(k);
            const canvas = document.getElementById(`fit-chart-${k}`);
            if (!t || !canvas) continue;
            const res = await apiClient.get(`board/api/metrics/${t.id}/insights/?days=90`, { silent: true });
            if (res.status !== 'success') continue;
            const pts = res.data.daily.filter(d => d.value > 0);
            const css = getComputedStyle(document.body);
            const brown = css.getPropertyValue('--ink-brown').trim();
            new Chart(canvas, {
                type: 'line',
                data: { labels: pts.map(p => p.date.slice(5)), datasets: [{ data: pts.map(p => p.value), borderColor: brown, backgroundColor: brown, tension: .3 }] },
                options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } },
                    scales: { x: { ticks: { color: css.getPropertyValue('--ink-gray').trim() } }, y: { ticks: { color: css.getPropertyValue('--ink-gray').trim() } } } },
            });
        }
    },

    dietHtml() {
        const p = this.data.profile;
        if (!p || !p.targets) return '';
        const t = p.targets;
        const rows = [
            t.kcal && ['Calories', `${this.fmt(t.kcal)} kcal${p.track_calories ? '' : ' <small>(not tracked)</small>'}`],
            t.protein_g && ['Protein', `${this.fmt(t.protein_g)} g a day &middot; about ${Math.round(t.protein_g / 4)} g a meal`],
            t.water_ml && ['Water', `${this.fmt(t.water_ml / 1000)} L a day`],
            t.steps && ['Steps', `${this.fmt(t.steps)} a day`],
            t.sleep_h && ['Sleep', `${[].concat(t.sleep_h).join('–')} h`],
        ].filter(Boolean);
        return `<div class="section"><h5 class="fit-h">Diet and targets</h5>
            <dl class="fit-diet">${rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('')}</dl></div>`;
    },

    // ── Actions ───────────────────────────────────────────────
    async logMetric(id, value, extra) {
        const res = await Resilient._call('post', `board/api/metrics/${id}/log/`, Object.assign({ value }, extra || {}));
        if (res.status === 'success') this.afterChange();
        return res;
    },

    async undo(id) {
        const res = await Resilient._call('delete', `board/api/metrics/${id}/log/`);
        if (res.status === 'success') this.afterChange();
    },

    logDialog(id) {
        const t = (this.data.trackers || []).find(x => x.id === id);
        if (!t) return;
        const verb = t.kind === 'single' ? 'is' : 'add';
        const body = Resilient.lead(t.kind === 'single' ? `Today&rsquo;s value replaces any earlier one.` : 'This adds to today&rsquo;s total.') +
            Resilient.say(`Today&rsquo;s ${this.esc(t.name.toLowerCase())} ${verb} <input type="number" inputmode="decimal" step="any" min="0" class="form-input" data-f="value" placeholder="${t.target ? this.fmt(t.target) : ''}"> ${this.esc(t.unit)}`);
        const el = Resilient.dialog(`Log ${t.name}`, body, [{ label: 'Cancel' }, {
            label: 'Save', primary: true, run: async (m) => {
                const v = m.querySelector('[data-f="value"]').value;
                if (v === '' || isNaN(+v)) return 'Enter a number';
                const res = await this.logMetric(id, +v);
                return res.status === 'success' ? true : (res.error || 'Could not save');
            },
        }], 'fa-pen');
        el.classList.add('fit-modal');
    },

    async tick(cb) {
        const res = await Resilient._call('put', `board/api/habit_steps/${cb.dataset.step}/log/`, { done: cb.checked });
        if (res.status !== 'success') { cb.checked = !cb.checked; return; }
        this.afterChange();
    },

    afterChange() {
        this.load();
        if (typeof Resilient !== 'undefined') Resilient._refresh();
    },

    async exerciseDialog(id) {
        let ex = this.exercises[id];
        if (!ex) {
            const res = await apiClient.get(`board/api/fitness/exercises/${encodeURIComponent(id)}/`, { silent: true });
            if (res.status !== 'success') return;
            ex = this.exercises[id] = res.data;
        }
        const list = (xs) => `<ul>${(xs || []).map(x => `<li>${this.esc(x)}</li>`).join('')}</ul>`;
        const muscles = [...ex.primary_muscles, ...ex.secondary_muscles.map(m => m + ' (light)')].map(m => m.replace(/_/g, ' ')).join(', ');
        const body = `<div class="fit-ex-view" id="fit-ex-view-${this.esc(ex.id)}">
                ${ex.still ? `<img class="fit-ex-still" src="${this.url(ex.still)}" alt="${this.esc(ex.name)}">` : ''}</div>
            <div class="fit-muted mb-2">${this.esc(muscles)}</div>
            <h6>How to</h6><ol>${ex.steps.map(s => `<li>${this.esc(s)}</li>`).join('')}</ol>
            ${ex.avoid && ex.avoid.length ? `<h6>Avoid</h6>${list(ex.avoid)}` : ''}
            ${ex.breathing ? `<p class="fit-muted"><i class="fas fa-wind"></i> ${this.esc(ex.breathing)}</p>` : ''}
            ${ex.video_url ? `<a class="rs-link" href="${ex.video_url}" target="_blank" rel="noopener">Watch a video <i class="fas fa-external-link-alt"></i></a>` : ''}`;
        const el = Resilient.dialog(ex.name, body, [{ label: 'Close', primary: true }], 'fa-dumbbell');
        el.classList.add('fit-modal');
        // The 3D renderer (phase 2) takes over the view when it is loaded and a clip exists
        if (typeof Exercise3D !== 'undefined') {
            el.addEventListener('shown.bs.modal', () => Exercise3D.mount(el.querySelector('.fit-ex-view'), ex), { once: true });
            el.addEventListener('hide.bs.modal', () => Exercise3D.unmount(el.querySelector('.fit-ex-view')), { once: true });
        }
    },

    start() {
        if (typeof FocusPlayer !== 'undefined') FocusPlayer.startWorkout();
    },
};
