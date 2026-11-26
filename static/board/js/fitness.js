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
            if (!el || !el.closest('#pane-fitness, .fit-modal')) {
                const tl = e.target.closest('[data-fit-tl]');
                if (tl) this.timelineAction(tl);
                return;
            }
            const act = el.dataset.fit;
            if (act === 'add') this.logMetric(+el.dataset.metric, +el.dataset.val);
            else if (act === 'log') this.logDialog(+el.dataset.metric);
            else if (act === 'undo') this.undo(+el.dataset.metric);
            else if (act === 'exercise') this.exerciseDialog(el.dataset.id);
            else if (act === 'month') this.shiftMonth(+el.dataset.dir);
            else if (act === 'day') this.dayDialog(el.dataset.date);
            else if (act === 'start') this.start();
            else if (act === 'onboard') this.onboard();
            else if (act === 'log-workout') this.logWorkoutDialog(el.dataset.date);
            else if (act === 'focus') { if (typeof FocusPlayer !== 'undefined') FocusPlayer.startFocus({}); }
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
                <p>No fitness plan yet. Answer a few questions and you&rsquo;ll get a plan, today&rsquo;s workout on your timeline,
                and water and protein targets. It takes about 3 minutes.</p>
                <button type="button" class="btn btn-paper btn-primary" data-fit="onboard"><i class="fas fa-play me-1"></i>Set up my plan</button>
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
                <div class="fit-workout-actions">${this.workoutButtons(a)}</div>`;
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

    workoutButtons(a) {
        const w = a.workout;
        if (w && w.status === 'completed') return `<span class="badge-done"><i class="fas fa-check"></i> Done${w.xp ? ` &middot; +${w.xp} XP` : ''}</span>`;
        if (w && w.status === 'skipped') return '<span class="badge-skipped">Skipped</span> <button type="button" class="rs-link" data-fit="log-workout">Log it anyway</button>';
        const resume = w && w.status === 'in_progress';
        return `<button type="button" class="btn btn-paper btn-primary" data-fit="start"><i class="fas fa-play"></i> ${resume ? 'Resume workout' : 'Start workout'}</button>
            <button type="button" class="btn btn-paper" data-fit="log-workout"><i class="fas fa-clipboard-check"></i> Log workout</button>
            ${w && w.status === 'partial' ? '<span class="fit-muted">Saved as partial</span>' : ''}`;
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
        const ex = p.explanation || {};
        const how = Object.keys(ex).length ? `<details class="fit-how"><summary>How this was calculated</summary>
            <ul>${['kcal', 'protein_g', 'water_ml', 'steps', 'sleep_h'].filter(k => ex[k]).map(k => `<li>${this.esc(ex[k])}</li>`).join('')}</ul></details>` : '';
        return `<div class="section"><h5 class="fit-h">Diet and targets</h5>
            <dl class="fit-diet">${rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('')}</dl>${how}
            <button type="button" class="btn btn-paper btn-sm mt-2" data-fit="onboard"><i class="fas fa-pen me-1"></i>${p.answered ? 'Edit my answers' : 'Answer the questions'}</button>
            <div class="fit-muted mt-1">General fitness guidance, not medical advice.</div></div>`;
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
        if (this.data) this.load();
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
        if (typeof FocusPlayer !== 'undefined') return FocusPlayer.startWorkout();
        // The extension has no player: open the web player
        window.open(`${HOST}board/?start=workout#fitness`, '_blank', 'noopener');
    },

    async ensureData() {
        if (!this.data) await this.load();
        return this.data;
    },

    // ── Log a workout without the player ──────────────────────
    async logWorkoutDialog(date) {
        const q = date ? `?date=${date}` : '';
        const res = await apiClient.get(`board/api/fitness/workouts/plan/${q}`, { silent: true });
        if (res.status !== 'success') return showError(res.error || 'No workout planned that day', 'Nothing to log');
        const p = res.data;
        if (p.logged) return showInfo('That workout is already logged.', 'Already done');
        const groups = [];
        p.rows.forEach(r => {
            let g = groups.find(x => x.exercise === r.exercise);
            if (!g) groups.push(g = { exercise: r.exercise, name: r.name, rows: [] });
            g.rows.push(r);
        });
        const last = p.last || {};
        const today = (this.data && this.data.today) || getDate(new Date());
        const min = new Date(new Date(today + 'T00:00').getTime() - 7 * 864e5).toISOString().slice(0, 10);
        const rows = groups.map(g => `<div class="fit-log-ex"><div class="fit-log-name">${this.esc(g.name)}
                ${last[g.exercise] ? `<small>last: ${last[g.exercise].reps} reps${last[g.exercise].load ? `, ${this.esc(last[g.exercise].load)}` : ''}</small>` : ''}</div>
            ${g.rows.map(r => `<div class="fit-log-row" data-ex="${this.esc(r.exercise)}" data-set="${r.set_index}" data-side="${r.side}">
                <span class="fit-log-k">Set ${r.set_index}${r.side ? ` ${r.side}` : ''}</span>
                ${r.target.reps ? `<input type="number" min="0" max="200" class="form-input" data-k="reps_done" value="${r.target.reps[1]}" aria-label="Reps"> reps`
                                : `<input type="number" min="0" max="3600" class="form-input" data-k="seconds_done" value="${r.target.seconds}" aria-label="Seconds"> s`}
                <input type="text" class="form-input fit-log-load" data-k="load" placeholder="load" value="${this.esc((last[r.exercise] || {}).load || '')}" aria-label="Load">
                <label class="fit-log-skip"><input type="checkbox" data-k="skipped"> skipped</label></div>`).join('')}</div>`).join('');
        const body = Resilient.lead('Trained away from the screen? Log it here. It counts the same as the player.') +
            Resilient.say(`I did ${this.esc(p.name || 'the workout')} on <input type="date" class="form-input" data-f="date" value="${p.date}" min="${min}" max="${today}">
                at <input type="time" class="form-input" data-f="start" value="18:00"> for <input type="number" class="form-input" data-f="minutes" value="${p.minutes}" min="1" max="240"> minutes.`) +
            `<details class="fit-log-details"><summary>Change sets</summary>${rows}</details>`;
        const collect = (m, planned) => {
            const g = (k) => m.querySelector(`[data-f="${k}"]`).value;
            const out = { date: g('date'), start_time: g('start'), duration_min: +g('minutes'), as_planned: planned };
            if (!planned) out.sets = [...m.querySelectorAll('.fit-log-row')].map(r => {
                const v = (k) => r.querySelector(`[data-k="${k}"]`);
                const row = { exercise: r.dataset.ex, set_index: +r.dataset.set, side: r.dataset.side, load: v('load').value.trim().toLowerCase(), skipped: v('skipped').checked };
                if (v('reps_done')) row.reps_done = +v('reps_done').value;
                if (v('seconds_done')) row.seconds_done = +v('seconds_done').value;
                return row;
            });
            return out;
        };
        const save = async (m, planned) => {
            const r = await Resilient._call('post', 'board/api/fitness/workouts/log/', collect(m, planned));
            if (r.status !== 'success') return r.error || 'Could not save';
            this.afterChange();
            const s = r.data;
            showSuccess(s.status === 'completed' ? `Logged. ${s.summary.sets_done}/${s.summary.sets_planned} sets${s.xp ? `, +${s.xp} XP` : ''}.` : 'Saved as partial: less than half the sets.', 'Workout logged');
            return true;
        };
        const el = Resilient.dialog('Log workout', body, [
            { label: 'Cancel' },
            { label: 'Save these sets', run: (m) => save(m, false) },
            { label: 'Did it as planned', primary: true, run: (m) => save(m, true) },
        ], 'fa-clipboard-check', { revealAll: true });
        el.classList.add('fit-modal');
        el.querySelector('details').addEventListener('toggle', () => typeof resizeInputs === 'function' && resizeInputs(el));
    },

    // ── Onboarding ────────────────────────────────────────────
    async onboard() {
        const prev = await apiClient.get('board/api/fitness/onboarding/', { silent: true });
        const a = (prev.status === 'success' && prev.data.answers) || {};
        const h = a.health || {};
        const t = a.times || {};
        const m = t.meals || {};
        const S = (k, v, opts) => Resilient.pick(`data-q="${k}"`, v, opts);
        const num = (k, v, attrs = '') => `<input type="number" class="form-input" data-q="${k}" value="${v == null ? '' : v}" ${attrs}>`;
        const time = (k, v) => `<input type="time" class="form-input" data-q="${k}" value="${v || ''}">`;
        const check = (k, label, on) => `<label class="fit-q-check"><input type="checkbox" data-q="${k}" ${on ? 'checked' : ''}> ${label}</label>`;
        const eq = new Set(a.equipment || ['band_tube', 'door_anchor', 'mat']);
        const pages = [
            { msg: 'What do you want from this?', html: `I want to ${S('goal', a.goal || 'lean_muscle', [['lean_muscle', 'build lean muscle'], ['lose_fat', 'lose fat'], ['general', 'get fit and active'], ['strength', 'build strength']])}
                because <input type="text" class="form-input" data-q="why" maxlength="200" value="${this.esc(a.why || '')}" placeholder="I want to keep up with my kids">.
                <div class="fit-muted mt-1">Your reason shows at the start of every workout.</div>` },
            { msg: 'The numbers for your targets. They stay private.', html: `I weigh ${num('weight_kg', a.weight_kg, 'step="0.1" min="30" max="300"')} kg, I&rsquo;m ${num('height_cm', a.height_cm, 'min="120" max="230"')} cm tall,
                ${num('age', a.age, 'min="16" max="90"')} years old, and ${S('sex', a.sex || 'male', [['male', 'male'], ['female', 'female']])}.` },
            { msg: 'A quick health check. Any yes gives you a gentler start.', html: `<div class="fit-q-list">
                ${check('heart', 'A heart condition, or a doctor told me to limit activity', h.heart)}
                ${check('chest_pain', 'Chest pain during activity or at rest', h.chest_pain)}
                ${check('dizziness', 'Dizziness or fainting', h.dizziness)}
                ${check('meds', 'I take blood-pressure or heart medication', h.meds)}
                ${check('joint', 'A bone, joint or back problem exercise could make worse', h.joint)}
                <div class="fit-q-joints">${['knee', 'lower_back', 'shoulder', 'wrist', 'hip', 'ankle'].map(j => check('joint_' + j, j.replace('_', ' '), (h.joints || []).includes(j))).join('')}</div>
                ${check('pregnant', 'Pregnant, or gave birth in the last 6 months', h.pregnant)}
                ${check('surgery', 'Surgery in the last 6 months', h.surgery)}</div>` },
            { msg: 'How much have you trained lately?', html: `In the last 6 months I&rsquo;ve trained ${S('experience', a.experience || 'none', [['none', 'not at all'], ['some', 'now and then'], ['regular', 'regularly']])}.` },
            { msg: 'Where and with what?', html: `I&rsquo;ll train ${S('setting', a.setting || 'home', [['home', 'at home'], ['gym', 'at a gym']])} and I have:
                <div class="fit-q-list fit-q-cols">${[['band_tube', 'bands with handles'], ['band_loop', 'loop bands'], ['door_anchor', 'a door anchor'], ['dumbbell', 'dumbbells'], ['kettlebell', 'a kettlebell'], ['bench', 'a bench'], ['pullup_bar', 'a pull-up bar'], ['mat', 'a mat']]
                    .map(([k, l]) => check('eq_' + k, l, eq.has(k))).join('')}</div>` },
            { msg: 'When does training fit your day?', html: `I can train ${S('days_per_week', a.days_per_week || 3, [[2, '2'], [3, '3'], [4, '4'], [5, '5'], [6, '6']])} days a week for
                ${S('minutes', a.minutes || 25, [[15, '15'], [25, '20–30'], [45, '45'], [60, '60']])} minutes, around ${time('workout', t.workout || '18:00')}.
                I wake at ${time('wake', t.wake || '06:00')} and eat breakfast at ${time('breakfast', m.breakfast || '08:00')}, lunch at ${time('lunch', m.lunch || '13:00')},
                a snack at ${time('snack', m.snack || '17:00')} and dinner at ${time('dinner', m.dinner || '20:30')}.` },
            { msg: 'Outside workouts, how active is your day?', html: `Most days I&rsquo;m ${S('daily_activity', a.daily_activity || 'sitting', [['sitting', 'mostly sitting'], ['some', 'on my feet some of the time'], ['most', 'on my feet most of the day']])}.` },
            { msg: 'Last one.', html: `I eat ${S('diet', a.diet || 'nonveg', [['veg', 'vegetarian'], ['egg', 'vegetarian with eggs'], ['nonveg', 'non-vegetarian']])} food,
                ${S('track_calories', a.track_calories ? '1' : '0', [['0', 'don&rsquo;t want'], ['1', 'want']])} to track calories, and sleep about ${num('sleep_hours', a.sleep_hours || 7, 'step="0.5" min="3" max="12"')} hours.
                <div class="fit-muted mt-1">Calorie logging is optional: protein and water do most of the work.</div>` },
        ];
        let page = 0;
        const body = `<div class="rs-convo-host"><div class="rs-lead" data-rs-msg></div>
            <div class="fit-q-progress" aria-hidden="true">${pages.map(() => '<i></i>').join('')}</div>
            ${pages.map((p, i) => `<div class="conversational-form fit-q-page" data-page="${i}" ${i ? 'hidden' : ''}><div class="convo-line">${p.html}</div></div>`).join('')}
            <div class="fit-q-page" data-page="preview" hidden></div></div>`;
        const collect = (el) => {
            const q = (k) => el.querySelector(`[data-q="${k}"]`);
            const v = (k) => (q(k) ? q(k).value : '');
            const c = (k) => !!(q(k) && q(k).checked);
            const joints = ['knee', 'lower_back', 'shoulder', 'wrist', 'hip', 'ankle'].filter(j => c('joint_' + j));
            return {
                goal: v('goal'), why: v('why'), weight_kg: +v('weight_kg'), height_cm: +v('height_cm'), age: +v('age'), sex: v('sex'),
                health: { heart: c('heart'), chest_pain: c('chest_pain'), dizziness: c('dizziness'), meds: c('meds'),
                          joint: c('joint') || joints.length > 0, joints, pregnant: c('pregnant'), surgery: c('surgery') },
                experience: v('experience'), setting: v('setting'),
                equipment: ['band_tube', 'band_loop', 'door_anchor', 'dumbbell', 'kettlebell', 'bench', 'pullup_bar', 'mat'].filter(k => c('eq_' + k)),
                days_per_week: +v('days_per_week'), minutes: +v('minutes'), daily_activity: v('daily_activity'),
                diet: v('diet'), track_calories: v('track_calories') === '1', sleep_hours: +v('sleep_hours'),
                timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
                times: { workout: v('workout'), wake: v('wake'), meals: { breakfast: v('breakfast'), lunch: v('lunch'), snack: v('snack'), dinner: v('dinner') } },
            };
        };
        const show = (el, i) => {
            page = i;
            el.querySelectorAll('.fit-q-page').forEach(p => { p.hidden = String(p.dataset.page) !== String(i); });
            el.querySelectorAll('.fit-q-progress i').forEach((d, j) => d.classList.toggle('on', i === 'preview' || j <= i));
            el.querySelector('[data-rs-msg]').innerHTML = i === 'preview' ? 'Here&rsquo;s your plan. Nothing changes until you start it.' : pages[i].msg;
            const btns = el.querySelectorAll('.modal-footer button');
            btns[0].textContent = i === 0 ? 'Cancel' : 'Back';
            btns[1].textContent = i === 'preview' ? 'Start my plan' : (i === pages.length - 1 ? 'See my plan' : 'Next');
            if (typeof resizeInputs === 'function') resizeInputs(el);
        };
        const preview = async (el) => {
            const r = await apiClient.post('board/api/fitness/onboarding/', collect(el), { silent: true });
            if (r.status !== 'success') return r.error || 'Check your answers';
            const d = r.data;
            const ex = d.explanation;
            const names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
            el.querySelector('[data-page="preview"]').innerHTML = `
                ${d.banner ? `<div class="fit-banner"><i class="fas fa-user-md"></i> ${this.esc(d.banner)}</div>` : ''}
                <h6>${this.esc(d.template.name)}</h6>
                <ul class="fit-q-week">${d.week1.map(w => `<li><b>${names[w.weekday]}</b> ${w.kind === 'session' ? this.esc(w.name) + ` <small>${this.esc(w.exercises.join(', '))}</small>` : this.esc(w.name)}</li>`).join('')}</ul>
                <h6>Your daily targets</h6>
                <dl class="fit-diet">
                    <dt>Calories</dt><dd>${d.targets.kcal.toLocaleString()} kcal${d.answers.track_calories ? '' : ' <small>(not tracked)</small>'}<div class="fit-muted">${this.esc(ex.kcal)}</div></dd>
                    <dt>Protein</dt><dd>${d.targets.protein_g} g<div class="fit-muted">${this.esc(ex.protein_g)}</div></dd>
                    <dt>Water</dt><dd>${(d.targets.water_ml / 1000).toFixed(1)} L<div class="fit-muted">${this.esc(ex.water_ml)}</div></dd>
                    <dt>Steps</dt><dd>${d.targets.steps.toLocaleString()}<div class="fit-muted">${this.esc(ex.steps)}</div></dd>
                </dl>
                ${this.data && this.data.program ? '<p class="fit-muted"><i class="fas fa-exclamation-circle"></i> Starting this replaces your current plan.</p>' : ''}
                <p class="fit-muted">${this.esc(d.disclaimer)}</p>`;
            return null;
        };
        const el = Resilient.dialog('Your fitness plan', body, [
            { label: 'Cancel', run: (m) => { if (page === 0) return true; show(m, page === 'preview' ? pages.length - 1 : page - 1); } },
            { label: 'Next', primary: true, run: async (m) => {
                if (page === 'preview') {
                    const r = await Resilient._call('post', 'board/api/fitness/onboarding/', { ...collect(m), confirm: true });
                    if (r.status !== 'success') return r.error || 'Could not start the plan';
                    this.data = null;
                    await this.load();
                    if (typeof Resilient !== 'undefined') Resilient._refresh();
                    showSuccess(`${r.data.template.name} starts today. Your first workout and targets are on your timeline.`, 'Plan ready');
                    return true;
                }
                if (page === pages.length - 1) {
                    const err = await preview(m);
                    if (err) return err;
                    show(m, 'preview');
                    return;
                }
                show(m, page + 1);
            } },
        ], 'fa-dumbbell', { revealAll: true });
        el.classList.add('fit-modal', 'fit-onboard');
        el.addEventListener('shown.bs.modal', () => show(el, 0), { once: true });
    },

    // ── Timeline items ────────────────────────────────────────
    async timelineAction(b) {
        const k = b.dataset.fitTl;
        const metric = +b.dataset.metric;
        if (k === 'start') return this.start();
        if (k === 'log') return this.logWorkoutDialog(b.dataset.date);
        if (k === 'skip') {
            const r = await Resilient._call('post', 'board/api/fitness/workouts/skip/', {});
            if (r.status === 'success') this.afterChange();
            return;
        }
        if (k === 'add') return this.logMetric(metric, +b.dataset.val);
        if (k === 'snack') {
            const r = await Resilient._call('post', 'board/api/fitness/ticks/', { key: 'snack', date: b.dataset.date });
            if (r.status === 'success') Resilient._refresh();
            return;
        }
        if (k === 'walk') {
            const r = await Resilient._call('put', `board/api/habit_steps/${b.dataset.step}/log/`, { done: true, date: b.dataset.date });
            if (r.status === 'success') this.afterChange();
            return;
        }
        if (k === 'weigh') { await this.ensureData(); return this.logDialog(metric); }
    },
};

/** Fitness items on the Today timeline (workout, snack, meals, water, walk, weigh-in, bedtime). */
const FitnessTimeline = {
    owns(e) { return e.event_type === 'fitness'; },

    actions(e) {
        const f = e.fit || {};
        const esc = (x) => Fitness.esc(x);
        const date = String(e.id).slice(-10);
        const prog = f.progress ? `<span class="fit-tl-prog">${esc(f.progress)}</span>` : '';
        if (e.action_response) {
            const label = f.kind === 'workout' && f.status === 'skipped' ? '<span class="badge-skipped">Skipped</span>' : '<span class="badge-done"><i class="fas fa-check"></i> Done</span>';
            return `<div class="timeline-actions">${prog}${label}</div>`;
        }
        if (!e.action) return prog ? `<div class="timeline-actions">${prog}</div>` : '';
        const btn = (k, label, extra = '', primary = false) =>
            `<button type="button" class="btn btn-paper btn-sm ${primary ? 'btn-primary' : ''} ms-1" data-fit-tl="${k}" data-date="${date}" ${extra}>${label}</button>`;
        let html = '';
        if (f.kind === 'workout') {
            html = f.status === 'in_progress' ? btn('start', '<i class="fas fa-play me-1"></i>Resume', '', true)
                : btn('start', '<i class="fas fa-play me-1"></i>Start', '', true) + btn('log', 'Log') + btn('skip', 'Skip');
        } else if (f.kind === 'snack') html = btn('snack', '<i class="fas fa-check"></i>', 'aria-label="Done"', true);
        else if (f.kind === 'meal') html = (e.action.protein || []).map(g => btn('add', `+${g} g`, `data-metric="${f.metric}" data-val="${g}"`)).join('');
        else if (f.kind === 'water') html = (e.action.water || []).map(ml => btn('add', `+${ml} ml`, `data-metric="${f.metric}" data-val="${ml}"`)).join('');
        else if (f.kind === 'walk') html = f.step ? btn('walk', '<i class="fas fa-check"></i>', `data-step="${f.step}" aria-label="Done"`, true) : '';
        else if (f.kind === 'weighin') html = btn('weigh', '<i class="fas fa-plus me-1"></i>Log', `data-metric="${f.metric}"`, true);
        return `<div class="timeline-actions">${prog}${html}</div>`;
    },
};
