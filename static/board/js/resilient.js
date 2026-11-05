/**
 * resilient.js — Resilient days: day chip (template + mode), running late,
 * slips, travel, check-in / reset cards, routine block actions, metric quick
 * logging, privacy lock and the matching settings card.
 *
 * No inline handlers: everything is wired with data-rs attributes and one
 * delegated listener, so the same file works in the extension (MV3 CSP).
 */
const Resilient = {
    day: null,
    metrics: [],
    privateState: { has_pin: false, unlocked: false },
    _boundDoc: false,

    // ── Helpers ──────────────────────────────────────────────
    esc(str) {
        const d = document.createElement('div');
        d.textContent = str == null ? '' : String(str);
        return d.innerHTML;
    },

    /** Today's date for the user: before day_start the logical day is still yesterday. */
    logicalToday() {
        const start = (typeof AppConfig !== 'undefined' && AppConfig.userDetail && AppConfig.userDetail.day_start) || '04:00';
        const [h, m] = String(start).split(':').map(Number);
        const now = new Date();
        const shifted = new Date(now.getTime() - ((h || 0) * 60 + (m || 0)) * 60000);
        return getDate(shifted);
    },

    isToday(date) { return date === this.logicalToday(); },

    async _call(method, url, body) {
        const res = await apiClient[method](url, body);
        if (res.status !== 'success') {
            const msg = res.error || res.message || 'Something went wrong';
            if (typeof showError === 'function') showError(typeof msg === 'string' ? msg : JSON.stringify(msg));
        }
        return res;
    },

    /** Debounced timeline refresh, for saves that happen while typing (the journal). */
    refreshSoon() {
        clearTimeout(this._soon);
        this._soon = setTimeout(() => this._refresh(), 1500);
    },

    async _refresh() {
        if (typeof Timeline === 'undefined') return;
        // A load already in flight would make loadEvents() return early and leave the old day on screen
        for (let i = 0; i < 40 && Timeline.loading; i++) await new Promise(r => setTimeout(r, 50));
        Timeline.events = [];
        Timeline.hasMore = true;
        await Timeline.loadEvents();
        if (typeof General !== 'undefined' && General.loadProductivityScore) General.loadProductivityScore();
        if (typeof Gamification !== 'undefined' && Gamification.load) Gamification.load();
    },

    // ── Boot ─────────────────────────────────────────────────
    init() {
        if (!this._boundDoc) {
            this._boundDoc = true;
            document.addEventListener('click', (e) => this._onClick(e));
            document.addEventListener('keydown', (e) => {
                if (e.ctrlKey && e.shiftKey && (e.key === 'L' || e.key === 'l')) {
                    e.preventDefault();
                    this.toggleLock();
                }
            });
        }
        this._mountBar();
        this._cacheDayStart();
        this.loadPrivateStatus();
        this.loadMetrics();
        this.mountSettings();
        this._bindHabitModal();
    },

    /** The extension's background worker needs the day start to pick the right day to poll. */
    _cacheDayStart() {
        try {
            const d = typeof AppConfig !== 'undefined' ? AppConfig.userDetail : null;
            if (d && d.day_start && typeof chrome !== 'undefined' && chrome.storage) {
                chrome.storage.local.set({ day_start: String(d.day_start).slice(0, 5) });
            }
        } catch (e) { /* not in the extension */ }
    },

    _mountBar() {
        if (document.getElementById('day-bar')) return;
        const host = document.getElementById('timeline-filters');
        const row = document.querySelector('.timeline-bar');
        if (!host || !row) return;
        // The day chips take the place of the old All/Habits/Todos/Routine filters
        host.id = 'day-bar';
        const note = document.createElement('div');
        note.id = 'day-note';
        row.insertAdjacentElement('afterend', note);
    },

    // ── Day bar ──────────────────────────────────────────────
    setDay(day, date) {
        this.day = day || null;
        this._mountBar();
        this.renderBar(date);
    },

    renderBar(date) {
        const bar = document.getElementById('day-bar');
        const note = document.getElementById('day-note');
        if (!bar) return;
        const d = this.day;
        if (!d) { bar.innerHTML = ''; if (note) note.innerHTML = ''; return; }
        const today = this.isToday(d.date);
        const editable = d.date >= this.logicalToday();
        const tpl = d.template === 'holiday' ? 'Holiday' : 'Workday';
        const mode = d.mode.charAt(0).toUpperCase() + d.mode.slice(1);
        let html = `<button type="button" class="timeline-chip rs-chip ${d.mode !== 'normal' ? 'active' : ''}" data-rs="menu-day" ${editable ? '' : 'disabled'}>${tpl} &middot; ${mode}<i class="fas fa-chevron-down"></i></button>`;
        if (today) {
            html += '<button type="button" class="timeline-chip rs-chip" data-rs="menu-late"><i class="fas fa-person-running"></i> Running late</button>';
            html += '<button type="button" class="timeline-chip rs-chip" data-rs="slip"><i class="fas fa-heart-crack"></i> I slipped</button>';
        }
        if (editable) html += '<button type="button" class="timeline-chip rs-chip" data-rs="travel"><i class="fas fa-mug-hot"></i> Off day&hellip;</button>';
        bar.innerHTML = html;
        let n = '';
        if (d.banner) n += `<div class="rs-banner">${this.esc(d.banner)}</div>`;
        if (d.warning === 'no_essential') n += '<div class="rs-warn">No essential blocks are set for this day, so the first anchor stands in. Mark an essential in your routine.</div>';
        if (today && d.shifts && d.shifts.length) {
            const total = d.shifts.reduce((a, s) => a + (s.minutes || 0), 0);
            n += `<div class="rs-banner">Running ${total} min late. <button type="button" class="rs-link" data-rs="late-undo">Undo</button></div>`;
        }
        if (note) note.innerHTML = n;
    },

    _closeMenus() { document.querySelectorAll('.rs-menu').forEach(m => m.remove()); },

    _menu(anchor, html) {
        this._closeMenus();
        const m = document.createElement('div');
        m.className = 'rs-menu search-engine-dropdown show';
        m.setAttribute('role', 'menu');
        m.innerHTML = html;
        document.body.appendChild(m);
        const r = anchor.getBoundingClientRect();
        const left = Math.min(window.scrollX + r.left, window.scrollX + document.documentElement.clientWidth - m.offsetWidth - 8);
        m.style.top = `${window.scrollY + r.bottom + 6}px`;
        m.style.left = `${Math.max(8, left)}px`;
    },

    _opt(rs, val, label, cur, hint) {
        return `<button type="button" role="menuitem" class="search-engine-option ${cur === val ? 'active' : ''}" data-rs="${rs}" data-val="${val}">${label}${hint ? `<small>${hint}</small>` : ''}</button>`;
    },

    _dayMenu(anchor) {
        const d = this.day;
        this._menu(anchor,
            '<div class="rs-menu-head">Day type</div>' +
            this._opt('set-template', 'workday', 'Workday', d.template) +
            this._opt('set-template', 'holiday', 'Holiday', d.template) +
            '<div class="rs-menu-head">Mode</div>' +
            this._opt('set-mode', 'normal', 'Normal', d.mode, 'everything') +
            this._opt('set-mode', 'light', 'Light', d.mode, 'essentials + anchors') +
            this._opt('set-mode', 'disrupted', 'Disrupted', d.mode, 'essentials only'));
    },

    _lateMenu(anchor) {
        this._menu(anchor, '<div class="rs-menu-head">Running late by</div>' +
            [15, 30, 60].map(m => this._opt('late', String(m), `${m} minutes`)).join(''));
    },

    async setDayPlan(patch) {
        if (!this.day) return;
        const res = await this._call('put', `board/api/day_plans/${this.day.date}/`, patch);
        if (res.status === 'success') {
            this.setDay(res.data, this.day.date);   // chip updates at once
            await this._refresh();
        }
    },

    // ── Timeline items ───────────────────────────────────────
    /** Items whose buttons this module draws; everything else keeps the timeline's own buttons. */
    owns(event) {
        const id = String(event.id);
        return event.event_type === 'routine' || id.startsWith('day-checkin-') || id.startsWith('reset-') || /^metric-\d+-/.test(id);
    },

    /** Buttons for string-id items (blocks and cards). */
    actions(event) {
        const id = String(event.id);
        if (event.event_type === 'routine') return this._blockActions(event);
        if (id.startsWith('day-checkin-')) return this._checkinActions(event);
        if (id.startsWith('reset-')) return this._resetActions(event);
        if (id.startsWith('metric-') && event.reference) {
            if (event.action_response) return '<div class="timeline-actions"><span class="badge-done"><i class="fas fa-check"></i> Logged</span></div>';
            return `<div class="timeline-actions"><button type="button" class="btn btn-paper btn-sm btn-primary" data-rs="metric-open" data-metric="${this.esc(event.reference.id)}"><i class="fas fa-plus me-1"></i>Log</button></div>`;
        }
        return '';
    },

    _blockActions(event) {
        const st = event.status;
        const entry = event.reference && event.reference.id;
        if (st === 'dropped') return '<div class="timeline-actions"><span class="badge-skipped">Dropped</span></div>';
        if (st === 'done' || st === 'skipped') {
            const badge = st === 'done'
                ? '<span class="badge-done"><i class="fas fa-check"></i> Done</span>'
                : '<span class="badge-skipped">Skipped</span>';
            const undo = entry ? `<button type="button" class="rs-link" data-rs="block-undo" data-entry="${this.esc(entry)}">Undo</button>` : '';
            return `<div class="timeline-actions">${badge}${undo}</div>`;
        }
        if (!entry) return '';
        return `<div class="timeline-actions">
            <button type="button" class="btn btn-paper btn-sm btn-primary" data-rs="block" data-st="done" data-entry="${this.esc(entry)}"><i class="fas fa-check me-1"></i>Done</button>
            <button type="button" class="btn btn-paper btn-sm ms-1" data-rs="block" data-st="skipped" data-entry="${this.esc(entry)}">Skip</button>
        </div>`;
    },

    _checkinActions(event) {
        if (event.action_response) return '';
        return `<div class="timeline-actions">
            <button type="button" class="btn btn-paper btn-sm btn-primary" data-rs="checkin" data-val="normal">Normal</button>
            <button type="button" class="btn btn-paper btn-sm ms-1" data-rs="checkin" data-val="light">Light</button>
            <button type="button" class="btn btn-paper btn-sm ms-1" data-rs="checkin" data-val="disrupted">Disrupted</button>
        </div>`;
    },

    _resetActions(event) {
        if (event.action_response) return '<div class="timeline-actions"><span class="badge-done"><i class="fas fa-check"></i> Reset</span></div>';
        const steps = (event.reset && event.reset.steps) || [];
        const list = steps.length
            ? `<div class="rs-steps">${steps.map(s => `<div class="form-check"><input class="form-check-input" type="checkbox" id="rs-rst-${this.esc(s.id)}" data-rs="reset-step" data-step="${this.esc(s.id)}" ${s.done ? 'checked' : ''}><label class="form-check-label" for="rs-rst-${this.esc(s.id)}">${this.esc(s.name)}</label></div>`).join('')}</div>`
            : '';
        return `${list}<div class="timeline-actions">
            <button type="button" class="btn btn-paper btn-sm btn-primary" data-rs="reset-done">I&rsquo;ve reset</button>
            <button type="button" class="btn btn-paper btn-sm ms-1" data-rs="checkin" data-val="light">Make today light</button>
        </div>`;
    },

    /** Small inline decoration for a block title. */
    note(event) {
        if (event.event_type !== 'routine') return '';
        let out = '';
        if (event.shifted_from) out += `<span class="rs-note">moved from ${this.esc(event.shifted_from)}</span>`;
        if (event.status === 'missed') out += '<span class="rs-note">missed</span>';
        return out;
    },

    // ── Click handling ───────────────────────────────────────
    async _onClick(e) {
        const el = e.target.closest('[data-rs]');
        if (!el) {
            if (!e.target.closest('.rs-menu')) this._closeMenus();
            return;
        }
        const act = el.dataset.rs;
        const today = this.logicalToday();
        const date = (this.day && this.day.date) || today;
        if (act === 'reset-step') return this._stepToggle(el);
        if (!['menu-day', 'menu-late'].includes(act)) this._closeMenus();

        switch (act) {
            case 'menu-day': return this._dayMenu(el);
            case 'menu-late': return this._lateMenu(el);
            case 'set-template': return this.setDayPlan({ template: el.dataset.val });
            case 'set-mode': return this.setDayPlan({ mode: el.dataset.val });
            case 'checkin': return this.setDayPlan({ mode: el.dataset.val, source: 'checkin' });
            case 'late': {
                const res = await this._call('post', `board/api/day_plans/${date}/late/`, { minutes: Number(el.dataset.val) });
                if (res.status === 'success') await this._refresh();
                return;
            }
            case 'late-undo': {
                const res = await this._call('delete', `board/api/day_plans/${date}/late/`);
                if (res.status === 'success') await this._refresh();
                return;
            }
            case 'block': {
                const res = await this._call('put', `board/api/day_plans/${date}/blocks/${el.dataset.entry}/`, { status: el.dataset.st });
                if (res.status === 'success') {
                    if (el.dataset.st === 'done' && typeof Theme !== 'undefined' && Theme.celebrate) Theme.celebrate();
                    await this._refresh();
                }
                return;
            }
            case 'block-undo': {
                const res = await this._call('delete', `board/api/day_plans/${date}/blocks/${el.dataset.entry}/`);
                if (res.status === 'success') await this._refresh();
                return;
            }
            case 'reset-done': {
                const res = await this._call('put', `board/api/day_plans/${date}/reset/`, {});
                if (res.status === 'success') await this._refresh();
                return;
            }
            case 'slip': return this.slipDialog();
            case 'travel': return this.travelDialog();
            case 'metric-add': return this.logMetric(Number(el.dataset.metric), Number(el.dataset.val));
            case 'metric-open': return this.metricDialog(Number(el.dataset.metric));
            case 'metric-undo': return this.undoMetric(Number(el.dataset.metric));
            case 'lock': return this.toggleLock();
        }
    },

    async _stepToggle(el) {
        await this._call('put', `board/api/habit_steps/${el.dataset.step}/log/`, {
            done: el.checked, date: this.logicalToday(),
        });
    },

    // ── Dialogs ──────────────────────────────────────────────
    /**
     * Conversational form helpers. Every form reads as a sentence the app says
     * with you ("Remind me at ___"), built from the app's own .conversational-form,
     * .convo-line and .form-input, like the New Habit and New Task modals.
     */
    /**
     * Lines are strings, or {html, msg, need}. msg is what the assistant says
     * when you're on that line; need means the line must be answered before the
     * next one appears (other lines can be skipped with Tab or Enter).
     */
    say(...lines) {
        const out = lines.filter(Boolean).map(l => {
            const o = typeof l === 'string' ? { html: l } : l;
            return `<div class="convo-line"${o.msg ? ` data-msg="${this.esc(o.msg)}"` : ''}${o.need ? ' data-need' : ''}>${o.html}</div>`;
        });
        return `<div class="conversational-form" data-rs-convo>${out.join('')}</div>`;
    },

    _textInputs(line) {
        return [...line.querySelectorAll('input.form-input')].filter(i => !['checkbox', 'radio', 'hidden'].includes(i.type));
    },
    _filled(line) { return this._textInputs(line).every(i => i.value.trim() !== ''); },

    /**
     * Wire a conversational form: fields grow with their text, later lines appear
     * once the current one is answered, and the message above follows the line
     * you're on. revealAll shows every line (editing something that exists).
     */
    convo(form, { revealAll = false } = {}) {
        if (!form) return;
        const lines = [...form.querySelectorAll(':scope > .convo-line')];
        const msgEl = form.closest('.modal-body, .rs-convo-host')?.querySelector('[data-rs-msg]');
        const lead = msgEl ? msgEl.innerHTML : '';
        const update = (focusNew) => {
            let open = true, firstNew = null;
            lines.forEach(line => {
                const wasHidden = line.hidden;
                line.hidden = !open && !revealAll;
                if (wasHidden && !line.hidden) { line.classList.add('rs-new'); firstNew = firstNew || line; }
                const passed = this._filled(line) || (!('need' in line.dataset) && line.dataset.touched === '1');
                if (!passed) open = false;
            });
            if (focusNew && firstNew) {
                const f = firstNew.querySelector('input:not([type=hidden]), select, textarea');
                if (f) setTimeout(() => f.focus(), 30);
            }
            resizeInputs(form);
        };
        lines.forEach(l => { delete l.dataset.touched; l.classList.remove('rs-new'); });
        if (!form.dataset.rsBound) {
            form.dataset.rsBound = '1';
            form.addEventListener('input', () => update(false));
            form.addEventListener('change', () => update(false));
            form.addEventListener('focusin', (e) => {
                const line = e.target.closest('.convo-line');
                if (msgEl && line && line.dataset.msg) msgEl.innerHTML = line.dataset.msg;
            });
            form.addEventListener('focusout', (e) => {
                const line = e.target.closest('.convo-line');
                if (!line) return;
                const leaving = !e.relatedTarget || !line.contains(e.relatedTarget);
                if (leaving) { line.dataset.touched = '1'; update(!e.relatedTarget || !form.contains(e.relatedTarget)); }
            });
            form.addEventListener('keydown', (e) => {
                if (e.key !== 'Enter' || e.target.tagName !== 'INPUT') return;
                const line = e.target.closest('.convo-line');
                const next = lines[lines.indexOf(line) + 1];
                if (!next) return;   // last line: let Enter do nothing special
                e.preventDefault();
                if ('need' in line.dataset && !this._filled(line)) return;
                line.dataset.touched = '1';
                update(true);
                if (!next.hidden) { const f = next.querySelector('input:not([type=hidden]), select'); if (f) f.focus(); }
            });
        }
        if (msgEl && lead) msgEl.innerHTML = lead;
        update(false);
    },

    /** An inline choice inside a sentence. opts: [[value, label], ...] */
    pick(attrs, val, opts) {
        return `<select class="form-input" ${attrs}>${opts.map(([v, l]) => `<option value="${v}" ${String(val) === String(v) ? 'selected' : ''}>${l}</option>`).join('')}</select>`;
    },
    hint(text) { return `<small class="text-brown ms-1">${text}</small>`; },
    /** Assistant line shown above the sentence, like #habit_message. */
    lead(text) { return `<div class="rs-lead" data-rs-msg>${text}</div>`; },

    /**
     * A real Bootstrap modal built like the app's own (modal-content, modal-icon,
     * btn-paper, form-control), so style.css themes it. Removed when hidden.
     */
    dialog(title, bodyHtml, buttons, icon = 'fa-pen', { revealAll = false } = {}) {
        const el = document.createElement('div');
        el.className = 'modal fade rs-modal';
        el.tabIndex = -1;
        el.innerHTML = `<div class="modal-dialog modal-dialog-centered modal-dialog-scrollable"><div class="modal-content">
            <div class="modal-header"><h5 class="modal-title"><div class="modal-icon info"><i class="fas ${icon}"></i></div> ${this.esc(title)}</h5>
                <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button></div>
            <div class="modal-body">${bodyHtml}<div class="rs-err" role="alert"></div></div>
            <div class="modal-footer">${buttons.map((b, i) => `<button type="button" class="btn btn-paper ${b.primary ? 'btn-primary' : ''}" data-idx="${i}">${this.esc(b.label)}</button>`).join('')}</div>
        </div></div>`;
        el.querySelectorAll('input:not([type=checkbox]):not([type=radio]):not([class]), textarea:not([class]), select:not([class])').forEach(x => x.classList.add('form-input'));
        document.body.appendChild(el);
        const modal = new bootstrap.Modal(el);
        el.addEventListener('hidden.bs.modal', () => { modal.dispose(); el.remove(); });
        el.querySelectorAll('[data-rs-convo]').forEach(f => this.convo(f, { revealAll }));
        el.addEventListener('shown.bs.modal', () => {
            resizeInputs(el);
            const f = el.querySelector('.modal-body .convo-line:not([hidden]) input:not([type=checkbox]):not([type=hidden])');
            if (f) f.focus();
        });
        el.addEventListener('click', async (ev) => {
            const btn = ev.target.closest('button[data-idx]');
            if (!btn) return;
            const spec = buttons[Number(btn.dataset.idx)];
            const err = el.querySelector('.rs-err');
            err.textContent = '';
            if (!spec.run) return modal.hide();
            btn.disabled = true;
            const out = await spec.run(el);
            btn.disabled = false;
            if (out === true) modal.hide();
            else if (typeof out === 'string') err.textContent = out;
        });
        modal.show();
        return el;
    },

    slipDialog() {
        this.dialog('I slipped', this.lead('Use this when you give in to something you&rsquo;re cutting down on, like an extra coffee or a late night on your phone. It adds one to your private Slips tracker, doesn&rsquo;t break your streak, and brings up a short reset so the rest of the day still counts.') +
            this.say({ html: `What happened was <input type="text" class="form-input" id="rs-slip-note" maxlength="280" placeholder="optional, just for you">`,
                       msg: 'A word about what led to it helps you spot the pattern later. Only you can see it.' }), [
            { label: 'Cancel' },
            { label: 'Log it', primary: true, run: async (ov) => {
                const res = await apiClient.post('board/api/lapses/', { note: ov.querySelector('#rs-slip-note').value });
                if (res.status !== 'success') return res.error || 'Could not log that';
                await this._refresh();
                return true;
            } },
        ], 'fa-heart-crack');
    },

    /** Off day: travel, a night shift, feeling unwell… The day gets lighter instead of failing. */
    travelDialog() {
        const t = this.logicalToday();
        const reasons = [['night_shift', 'a night shift'], ['travel', 'travel'], ['sick', 'feeling unwell'], ['family', 'family'], ['event', 'an event'], ['other', 'something else']];
        const ov = this.dialog('Off day', this.lead('Taking a day off from your usual routine? It won&rsquo;t break your streak.') + this.say(
            { need: true, msg: 'Which day? For a few days in a row, set the last one next.',
              html: `I&rsquo;m off from <input type="date" class="form-input" id="rs-t-from" value="${t}" min="${t}">
                     until <input type="date" class="form-input" id="rs-t-to" value="${t}" min="${t}">` },
            { msg: 'The reason goes into that day&rsquo;s journal, so you can look back on it later.',
              html: `because of ${this.pick('id="rs-t-reason"', 'night_shift', reasons)}
                     <input type="text" class="form-input" id="rs-t-note" maxlength="120" placeholder="a few words, optional">` },
            { msg: 'A Light day keeps your essentials and anchors. A Disrupted day keeps only essentials, and is followed by Light days to ease back in.',
              html: `Make it ${this.pick('id="rs-t-mode"', 'light', [['light', 'a light day'], ['disrupted', 'a disrupted day']])}.` },
        ), [
            { label: 'Cancel' },
            { label: 'Set off day', primary: true, run: async (o) => {
                const start = o.querySelector('#rs-t-from').value, end = o.querySelector('#rs-t-to').value;
                if (!start || !end || end < start) return 'Choose a valid date range';
                const res = await apiClient.post('board/api/day_plans/travel/', {
                    start, end, reason: o.querySelector('#rs-t-reason').value,
                    note: o.querySelector('#rs-t-note').value, mode: o.querySelector('#rs-t-mode').value,
                });
                if (res.status !== 'success') return res.error || 'Could not set the off day';
                await this._refresh();
                if (typeof JournalPane !== 'undefined' && JournalPane.loadMonthData) JournalPane.loadMonthData();
                return true;
            } },
        ], 'fa-mug-hot');
        // Travel is usually a Disrupted day; the rest default to Light
        ov.querySelector('#rs-t-reason').addEventListener('change', (e) => {
            ov.querySelector('#rs-t-mode').value = e.target.value === 'travel' ? 'disrupted' : 'light';
            resizeInputs(ov);
        });
    },

    // ── Metrics ──────────────────────────────────────────────
    async loadMetrics() {
        const res = await apiClient.get('board/api/metrics/', { silent: true });
        if (res.status === 'success') {
            this.metrics = res.data;
            if (typeof Trackers !== 'undefined') Trackers.onMetrics(this.metrics);
        }
    },

    async logMetric(id, value, extra) {
        const body = Object.assign({ value }, extra || {});
        const res = await this._call('post', `board/api/metrics/${id}/log/`, body);
        if (res.status === 'success') { await this.loadMetrics(); await this._refresh(); }
        return res;
    },

    async undoMetric(id) {
        const res = await this._call('delete', `board/api/metrics/${id}/log/`);
        if (res.status === 'success') { await this.loadMetrics(); await this._refresh(); }
    },

    metricDialog(id) {
        const m = this.metrics.find(x => x.id === id);
        if (!m) return;
        const unit = this.esc(m.unit || '');
        const name = this.esc(m.name.toLowerCase());
        const num = '<input id="rs-m-val" type="number" step="any" class="form-input" placeholder="0">';
        const first = m.system_key === 'sleep' ? { html: `Last night I slept ${num} hours`, need: true, msg: 'Roughly how many hours? Halves are fine, like 6.5.' }
            : m.kind === 'counter' ? { html: `One more ${name}.` }
            : m.kind === 'single' ? { html: `Today my ${name} was ${num} ${unit}`, need: true, msg: `How much ${name} today?` }
            : { html: `Add ${num} ${unit} to my ${name}`, need: true, msg: `How much ${name} are you adding?` };
        const fields = (m.fields || []).map((f, i) => {
            const key = f.key || f.name;
            const raw = f.label || key;
            const label = this.esc(raw.charAt(0).toUpperCase() + raw.slice(1));
            const chips = ((m.chips || {})[key] || []).slice(0, 6);
            const pick = chips.length ? ` <span class="freq-days">${chips.map(c => `<button type="button" class="freq-day-btn" data-chip="${i}" data-v="${this.esc(c)}">${this.esc(c)}</button>`).join('')}</span>` : '';
            const input = f.type === 'scale'
                ? `<input data-field="${this.esc(key)}" type="number" min="1" max="${f.max || 10}" class="form-input" placeholder="1 to ${f.max || 10}">`
                : `<input data-field="${this.esc(key)}" type="text" maxlength="64" class="form-input" placeholder="${f.type === 'choice' && f.options ? this.esc(f.options.slice(0, 2).join(', ')) : ''}">`;
            return { html: `${label}: ${input}${pick}`, msg: chips.length ? 'Tap one of your usual answers, or type a new one. Tab to skip.' : 'Optional. Press Tab to skip.' };
        });
        const ov = this.dialog(`Log ${m.name}`,
            this.lead(m.kind === 'counter' ? `Logging one more ${name}.` : `Let&rsquo;s log your ${name}.`) +
            this.say(first, ...fields, { html: `and a note: <input id="rs-m-note" type="text" maxlength="280" class="form-input" placeholder="optional">`,
                                         msg: `Notes and answers go to your ${this.esc(m.name)} journal, in the Journal pane.` }), [
            { label: 'Cancel' },
            { label: 'Log', primary: true, run: async (o) => {
                const data = {};
                o.querySelectorAll('[data-field]').forEach(i => { if (i.value.trim()) data[i.dataset.field] = i.value.trim(); });
                const valEl = o.querySelector('#rs-m-val');
                const value = valEl ? Number(valEl.value) : 1;
                if (valEl && (valEl.value === '' || Number.isNaN(value))) return 'Enter a value';
                const res = await apiClient.post(`board/api/metrics/${id}/log/`, { value, data, note: o.querySelector('#rs-m-note').value });
                if (res.status !== 'success') return res.error || 'Could not log that';
                await this.loadMetrics(); await this._refresh();
                return true;
            } },
        ], 'fa-chart-line');
        ov.addEventListener('click', (ev) => {
            const chip = ev.target.closest('[data-chip]');
            if (!chip) return;
            const input = ov.querySelectorAll('[data-field]')[Number(chip.dataset.chip)];
            if (input) input.value = chip.dataset.v;
        });
    },

    // ── Privacy ──────────────────────────────────────────────
    async loadPrivateStatus() {
        const res = await apiClient.get('board/api/private/status/', { silent: true });
        if (res.status === 'success') {
            this.privateState = res.data;
            this._renderLockIcon();
        }
    },

    _renderLockIcon() {
        this._renderFooter();
        let icon = document.getElementById('rs-lock-icon');
        if (!this.privateState.has_pin || this.privateState.unlocked) { if (icon) icon.remove(); return; }
        if (!icon) {
            icon = document.createElement('button');
            icon.id = 'rs-lock-icon';
            icon.type = 'button';
            icon.dataset.rs = 'lock';
            icon.className = 'btn btn-paper';
            document.body.appendChild(icon);
        }
        const open = this.privateState.unlocked;
        icon.innerHTML = `<i class="fas ${open ? 'fa-lock-open' : 'fa-lock'}"></i>`;
        icon.title = open ? 'Private items visible. Click to lock' : 'Private items hidden. Click to unlock';
    },

    /** While private items are shown, the footer bar says so; clicking it hides them again. */
    _renderFooter() {
        const bar = document.getElementById('footer-bar');
        if (!bar) return;
        let tag = document.getElementById('footer-private');
        if (!tag) {
            tag = document.createElement('button');
            tag.type = 'button';
            tag.id = 'footer-private';
            tag.dataset.rs = 'lock';
            tag.title = 'Hide private items';
            bar.insertBefore(tag, bar.firstChild);
        }
        const on = !!(this.privateState.has_pin && this.privateState.unlocked);
        bar.classList.toggle('rs-private', on);
        tag.hidden = !on;
        tag.innerHTML = '<i class="fas fa-lock-open"></i><span class="rs-fp-text">Private mode is on &middot; tap to turn it off</span>';
    },

    async _afterPrivacyChange() {
        await this.loadPrivateStatus();
        await this.loadMetrics();
        await this._refresh();
        if (typeof loadHabits === 'function') loadHabits();
        if (typeof JournalPane !== 'undefined' && JournalPane.loadMonthData) {
            JournalPane.loadMonthData();
            const ed = document.getElementById('journal-editor');
            if (typeof Trackers !== 'undefined') Trackers.journalNotes((ed && ed.getAttribute('data-date')) || getDate(new Date()));
        }
        if (typeof TodosPane !== 'undefined' && typeof panesLoaded !== 'undefined' && panesLoaded.todos && TodosPane.loadTodos) TodosPane.loadTodos();
        if (typeof General !== 'undefined' && General.loadProductivityScore) General.loadProductivityScore();
        if (document.getElementById('rs-settings')) this.renderSettings();
    },

    /** Typed in the search bar as /private (the command itself is never put in the field). */
    privateCommand() {
        if (!this.privateState.has_pin) return this.pinSetupDialog();
        return this.toggleLock();
    },

    async toggleLock() {
        await this.loadPrivateStatus();
        if (!this.privateState.has_pin) return this.pinSetupDialog();
        if (this.privateState.unlocked) {
            await apiClient.post('board/api/private/lock/', {});
            return this._afterPrivacyChange();
        }
        this.unlockDialog();
    },

    unlockDialog() {
        this.dialog('Unlock private items', this.lead('Enter your PIN to show private habits and trackers.') + this.say({ html: 'My PIN is <input id="rs-pin" type="password" inputmode="numeric" autocomplete="off" class="form-input" placeholder="&bull;&bull;&bull;&bull;">', need: true }), [
            { label: 'Forgot PIN', run: async () => { this.resetPinDialog(); return true; } },
            { label: 'Unlock', primary: true, run: async (o) => {
                const res = await apiClient.post('board/api/private/unlock/', { pin: o.querySelector('#rs-pin').value });
                if (res.status !== 'success') return res.error || 'Wrong PIN';
                await this._afterPrivacyChange();
                return true;
            } },
        ], 'fa-lock').querySelector('#rs-pin').addEventListener('keydown', (e) => {
            if (e.key === 'Enter') e.target.closest('.modal-content').querySelector('.btn-primary').click();
        });
    },

    pinSetupDialog() {
        this.dialog('Set a PIN for private items',
            this.lead('Private habits and trackers stay hidden until you unlock them with this PIN.') +
            this.say({ html: 'My new PIN is <input id="rs-pin" type="password" inputmode="numeric" autocomplete="off" class="form-input" placeholder="4&ndash;12 digits">', need: true,
                       msg: 'Pick 4 to 12 digits you&rsquo;ll remember.' },
                     { html: 'and once more: <input id="rs-pin2" type="password" inputmode="numeric" autocomplete="off" class="form-input" placeholder="repeat it">', need: true,
                       msg: 'Type it again so we know it&rsquo;s right.' }), [
            { label: 'Cancel' },
            { label: 'Save PIN', primary: true, run: async (o) => {
                const pin = o.querySelector('#rs-pin').value;
                if (pin !== o.querySelector('#rs-pin2').value) return 'PINs do not match';
                const res = await apiClient.post('board/api/private/pin/', { pin });
                if (res.status !== 'success') return res.error || 'Could not set PIN';
                await this._afterPrivacyChange();
                if (document.getElementById('rs-settings')) this.renderSettings();
                return true;
            } },
        ], 'fa-lock');
    },

    resetPinDialog() {
        this.dialog('Reset PIN', this.lead('Tap &ldquo;Send code&rdquo; and we&rsquo;ll email you a code.') +
            this.say({ html: 'The code I got is <input id="rs-code" type="text" autocomplete="one-time-code" class="form-input" placeholder="123456">', need: true,
                       msg: 'Check your email for the code.' },
                     { html: 'and my new PIN is <input id="rs-pin" type="password" inputmode="numeric" autocomplete="off" class="form-input" placeholder="4&ndash;12 digits">', need: true,
                       msg: 'Pick 4 to 12 digits.' }), [
            { label: 'Send code', run: async (o) => {
                const res = await apiClient.post('board/api/private/reset/request/', {});
                return res.status === 'success' ? 'Code sent. Check your email.' : (res.error || 'Could not send a code');
            } },
            { label: 'Reset', primary: true, run: async (o) => {
                const res = await apiClient.post('board/api/private/reset/confirm/', {
                    code: o.querySelector('#rs-code').value, pin: o.querySelector('#rs-pin').value,
                });
                if (res.status !== 'success') return res.error || 'Could not reset the PIN';
                await this._afterPrivacyChange();
                return true;
            } },
        ]);
    },


    // ── Habit options (inside the habit settings modal) ──────
    _bindHabitModal() {
        const modal = document.getElementById('habitSettingsModal');
        if (!modal || modal.dataset.rsBound) return;
        modal.dataset.rsBound = '1';
        modal.addEventListener('shown.bs.modal', () => this.renderHabitOptions());
        // Partner section: pick from your friends instead of typing an email
        const partners = document.getElementById('partnerSection');
        if (partners && typeof MutationObserver !== 'undefined') {
            new MutationObserver(() => { if (partners.style.display !== 'none') this.renderFriendPicker(); })
                .observe(partners, { attributes: true, attributeFilter: ['style'] });
        }
        modal.addEventListener('change', (e) => {
            const el = e.target.closest('[data-hopt]');
            if (el) this._saveHabitOption(el);
        });
        modal.addEventListener('click', (e) => {
            const b = e.target.closest('[data-hstep]');
            if (b) this._habitStepAction(b);
            const d = e.target.closest('[data-hday]');
            if (d) this._toggleHabitDay(d);
        });
    },

    async renderHabitOptions() {
        const modal = document.getElementById('habitSettingsModal');
        const habit = typeof currentHabitData !== 'undefined' ? currentHabitData : null;
        if (!modal || !habit || !habit.id) return;
        let box = document.getElementById('rs-habit-options');
        if (!box) {
            box = document.createElement('div');
            box.id = 'rs-habit-options';
            const host = document.getElementById('rs-habit-sections') || modal.querySelector('.modal-body');
            host.appendChild(box);
        }
        const [hres, sres, mres] = await Promise.all([
            apiClient.get(`board/api/habits/${habit.id}/`, { silent: true }),
            apiClient.get(`board/api/habits/${habit.id}/steps/`, { silent: true }),
            apiClient.get('board/api/metrics/', { silent: true }),
        ]);
        const h = hres.status === 'success' ? hres.data : {};
        const steps = sres.status === 'success' ? sres.data.steps : [];
        const metrics = mres.status === 'success' ? mres.data : [];
        const freq = (h.frequency && h.frequency.length) ? h.frequency : [0, 1, 2, 3, 4, 5, 6];
        const days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
        const P = (k, v, o) => this.pick(`data-hopt="${k}"`, v, o);
        box.dataset.habit = habit.id;
        const section = (title, body) => `<div class="rs-habit-section"><h6 class="mb-2">${title}</h6>${body}</div>`;
        box.innerHTML =
            section('Steps:', this.say(
                steps.length ? `Count it done when ${P('complete_when', h.complete_when || 'all', [['all', 'all the steps'], ['any', 'any step'], ['final', 'the last step']])} ${h.complete_when === 'any' || h.complete_when === 'final' ? 'is' : 'are'} ticked.` : '',
                ...steps.map((st, i) => `${i + 1}. ${this.esc(st.name)} <button type="button" class="tl-link ms-1" data-hstep="del" data-id="${st.id}">remove</button>`),
                `${steps.length ? 'Then' : 'First'} I <input type="text" id="rs-new-step" class="form-input" maxlength="80" placeholder="${steps.length ? 'add another step' : 'add a step'}"> <button type="button" class="btn btn-paper btn-sm" data-hstep="add">Add</button>`,
            )) +
            section('Reminder:', this.say(
                `Remind me at <input type="time" class="form-input" data-hopt="notify_at" value="${this.esc((h.notify_at || '').slice(0, 5))}"> ${this.hint('(empty for none)')}`,
                `on every <span class="freq-days">${days.map((d, i) => `<button type="button" class="freq-day-btn ${freq.includes(i) ? 'active' : ''}" data-hday="${i}">${d}</button>`).join('')}</span>`,
                `and log it in ${P('metric', h.metric ?? '', [['', 'no tracker'], ...metrics.map(m => [m.id, this.esc(m.name)])])}.`,
            )) +
            section('On hard days:', this.say(
                `On Light days this habit is ${P('on_light', h.on_light || 'required', [['required', 'still required'], ['excused', 'excused']])}`,
                `and on Disrupted days it&rsquo;s ${P('on_disrupted', h.on_disrupted || 'excused', [['excused', 'excused'], ['required', 'still required']])}.`,
            )) +
            section('Privacy:', this.say(
                `Keep it ${P('is_private', h.is_private ? 'true' : 'false', [['false', 'visible'], ['true', 'private until I unlock']])}`,
                h.is_private ? `and while locked, remind me with ${P('private_reminder', h.private_reminder ? 'true' : 'false', [['false', 'nothing'], ['true', 'a plain &ldquo;Reminder&rdquo;']])}.` : '',
            ));
        resizeInputs(box);
        const input = box.querySelector('#rs-new-step');
        input.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); box.querySelector('[data-hstep="add"]').click(); } });
    },

    async renderFriendPicker() {
        const section = document.getElementById('partnerSection');
        const assign = section && section.querySelector('.assign-partner');
        if (!assign) return;
        let box = document.getElementById('rs-friend-pick');
        if (!box) {
            box = document.createElement('div');
            box.id = 'rs-friend-pick';
            box.className = 'mb-3';
            assign.parentElement.insertBefore(box, assign);
            box.addEventListener('click', (e) => {
                const b = e.target.closest('[data-friend-email]');
                if (!b || typeof assignPartner !== 'function') return;
                document.getElementById('partnerEmail').value = b.dataset.friendEmail;
                assignPartner();
            });
            const label = assign.querySelector('.form-label');
            if (label) label.textContent = 'Or invite someone by email:';
        }
        const res = await apiClient.get('board/api/friends/', { silent: true });
        const friends = res.status === 'success' ? res.data : [];
        box.innerHTML = friends.length
            ? `<label class="form-label">Pick a friend:</label>
               <div class="freq-days">${friends.map(f => `<button type="button" class="freq-day-btn" data-friend-email="${this.esc(f.friend_email)}" title="${this.esc(f.friend_email)}">${this.esc(f.friend_name || f.friend_username || f.friend_email)}</button>`).join('')}</div>`
            : '<div class="form-text">No friends yet. Add friends from More &rarr; Friends, or invite someone by email below.</div>';
    },

    async _toggleHabitDay(btn) {
        const id = document.getElementById('rs-habit-options').dataset.habit;
        btn.classList.toggle('active');
        const days = [...document.querySelectorAll('#rs-habit-options [data-hday].active')].map(b => Number(b.dataset.hday));
        if (!days.length) { btn.classList.add('active'); return this.habitMessage('A habit needs at least one day.', 'warning'); }
        const res = await this._call('patch', `board/api/habits/${id}/`, { frequency: days });
        if (res.status === 'success') { this.habitMessage('Days saved.'); if (typeof loadHabits === 'function') loadHabits(); }
        else btn.classList.toggle('active');
    },

    /** Uses the settings modal's own message slot, like the rest of that modal. */
    habitMessage(text, kind = 'success') {
        const el = document.getElementById('habit_settings_message');
        if (!el) return;
        el.innerHTML = `<div class="alert alert-${kind}"><i class="fas ${kind === 'success' ? 'fa-check' : 'fa-circle-exclamation'} me-2"></i>${this.esc(text)}</div>`;
        clearTimeout(this._hmsg);
        this._hmsg = setTimeout(() => { el.innerHTML = ''; }, 2500);
    },

    async _saveHabitOption(el) {
        const id = document.getElementById('rs-habit-options').dataset.habit;
        const key = el.dataset.hopt;
        let value = el.value;
        if (key === 'is_private' || key === 'private_reminder') value = value === 'true';
        if (key === 'metric') value = value ? Number(value) : null;
        if (key === 'notify_at') value = value || null;
        const res = await this._call('patch', `board/api/habits/${id}/`, { [key]: value });
        if (res.status === 'success') {
            this.habitMessage('Saved.');
            if (typeof loadHabits === 'function') loadHabits();
            if (key === 'notify_at' && typeof showReminder === 'function') {
                if (typeof currentHabitData !== 'undefined') currentHabitData.notifyAt = value || '';
                showReminder(value || '');
            }
            if (key === 'is_private' || key === 'complete_when') this.renderHabitOptions();
            if (key === 'metric') this.loadMetrics();
        }
    },

    async _habitStepAction(btn) {
        const id = document.getElementById('rs-habit-options').dataset.habit;
        if (btn.dataset.hstep === 'add') {
            const input = document.getElementById('rs-new-step');
            const name = input.value.trim();
            if (!name) return;
            const res = await this._call('post', `board/api/habits/${id}/steps/`, { name });
            if (res.status === 'success') this.renderHabitOptions();
        } else {
            const res = await this._call('delete', `board/api/habit_steps/${btn.dataset.id}/`);
            if (res.status === 'success') this.renderHabitOptions();
        }
    },

    // ── Settings: day preferences sit in Preferences, the PIN in User ──
    mountSettings() {
        const host = document.getElementById('rs-settings');
        if (!host || host.dataset.bound) return;
        host.dataset.bound = '1';
        const user = document.getElementById('rs-user-pin');
        [host, user].filter(Boolean).forEach(el => {
            el.addEventListener('change', (e) => this._saveSetting(e));
            el.addEventListener('click', (e) => {
                const day = e.target.closest('[data-set="weekend"]');
                if (day) { day.classList.toggle('active'); this._saveSetting({ target: day }); }
                if (e.target.closest('[data-rs-set="pin"]')) this.pinSetupDialog();
            });
        });
        this.renderSettings();
    },

    async renderSettings() {
        const body = document.getElementById('rs-settings');
        if (!body) return;
        const d = typeof AppConfig !== 'undefined' ? AppConfig.userDetail : null;
        if (!d) return setTimeout(() => this.renderSettings(), 800);
        const email = document.getElementById('settingsEmail');
        if (email) email.textContent = d.email || '';
        const hres = await apiClient.get('board/api/habits/', { silent: true });
        const habits = hres.status === 'success' ? (hres.data.results || hres.data) : [];
        const names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
        const wk = d.weekend_days || [5, 6];
        const opt = (v, l, cur) => `<option value="${v}" ${String(cur) === String(v) ? 'selected' : ''}>${l}</option>`;
        const row = (label, control, hint, last) => `<div class="${last ? 'mb-0' : 'mb-3'}"><label class="form-label">${label}</label>${control}${hint ? `<small class="form-text text-brown d-block">${hint}</small>` : ''}</div>`;
        body.innerHTML =
            row('Day starts at', `<input type="time" class="form-control" data-set="day_start" value="${this.esc((d.day_start || '04:00').slice(0, 5))}">`,
                'Anything before this time still counts for the previous day. Working nights? Set it after your shift ends.') +
            row('Weekend days', `<div class="freq-days">${names.map((n, i) => `<button type="button" class="freq-day-btn ${wk.includes(i) ? 'active' : ''}" data-set="weekend" data-day="${i}">${n}</button>`).join('')}</div>`,
                'These days use your Holiday routine unless you change the day.') +
            row('Light days after an off day', `<input type="number" class="form-control" min="0" max="7" data-set="travel_ramp_days" value="${this.esc(d.travel_ramp_days ?? 2)}">`,
                'After a Disrupted off day (like travel), this many Light days help you ease back in.') +
            row('Streak counts', `<select class="form-control" data-set="streak_rule">${opt('activity', 'Any activity (default)', d.streak_rule || 'activity')}${opt('routine', 'Routine met (essentials and anchors)', d.streak_rule)}</select>`) +
            row('Journaling habit', `<select class="form-control" data-set="journal_habit">${opt('', 'None', d.journal_habit ?? '')}${habits.map(h => opt(h.id, this.esc(h.habit), d.journal_habit)).join('')}</select>`,
                'Writing in your journal marks this habit done for the day.', true);
        const pin = document.getElementById('rs-user-pin');
        if (pin) pin.innerHTML = row('Privacy PIN',
            `<div><button type="button" class="btn btn-paper btn-sm btn-primary" data-rs-set="pin">${this.privateState.has_pin ? 'Change PIN' : 'Set a PIN'}</button></div>`,
            'Hides private habits, trackers and journals. Type /private in the search bar or press Ctrl+Shift+L to show or hide them.', true);
    },

    async _saveSetting(e) {
        const el = e.target.closest('[data-set]');
        if (!el) return;
        const key = el.dataset.set;
        let payload;
        if (key === 'weekend') {
            payload = { weekend_days: [...document.querySelectorAll('[data-set="weekend"].active')].map(b => Number(b.dataset.day)) };
        } else if (key === 'travel_ramp_days') {
            payload = { travel_ramp_days: Number(el.value) };
        } else if (key === 'journal_habit') {
            payload = { journal_habit: el.value ? Number(el.value) : null };
        } else {
            payload = { [key]: el.value };
        }
        const res = await apiClient.put('board/api/user_details/', payload);
        if (res.status === 'success') {
            if (typeof AppConfig !== 'undefined') { AppConfig.userDetail = Object.assign({}, AppConfig.userDetail, res.data || payload); this._cacheDayStart(); }
            await this._refresh();
        } else if (typeof showError === 'function') {
            showError(res.error || 'Could not save that');
        }
    },
};

/**
 * Size .form-input fields to their text (or placeholder), so sentence forms read
 * naturally. habits.js already calls resizeInputs() when it opens the edit form.
 */
function resizeInputs(root = document) {
    const canvas = resizeInputs._c || (resizeInputs._c = document.createElement('canvas'));
    const ctx = canvas.getContext('2d');
    root.querySelectorAll('input.form-input').forEach(el => {
        if (!['text', 'url', 'email', 'number', 'password', 'search', ''].includes(el.type)) return;
        const cs = getComputedStyle(el);
        ctx.font = `${cs.fontStyle} ${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
        const text = el.value || el.placeholder || '';
        const shown = el.type === 'password' ? '\u2022'.repeat(text.length) : text;
        const pad = parseFloat(cs.paddingLeft) + parseFloat(cs.paddingRight) + (el.type === 'number' ? 28 : 14);
        el.style.width = `${Math.max(40, Math.ceil(ctx.measureText(shown).width + pad))}px`;
    });
}

document.addEventListener('input', (e) => {
    if (e.target.matches && e.target.matches('input.form-input')) resizeInputs(e.target.parentElement || document);
});
// The app's own modals that are sentence forms (Sleep, Reading list, Edit task, Group, New Habit, New Task)
document.addEventListener('shown.bs.modal', (e) => {
    resizeInputs(e.target);
    e.target.querySelectorAll('[data-rs-convo]').forEach(f => {
        if (f.closest('.rs-modal')) return;   // dialogs built here wire themselves
        Resilient.convo(f, { revealAll: f.dataset.rsReveal === 'filled' && Resilient._textInputs(f).some(i => i.value.trim()) });
    });
});

// On phones and tablets the body is overflow:hidden and each pane scrolls on its
// own. scrollIntoView() and focusing a field can still scroll the body itself,
// which pushed everything (bookmarks, greeting) under the top bar until a reload.
// Put it back whenever that happens.
window.addEventListener('scroll', () => {
    const root = document.scrollingElement;
    if (root && root.scrollTop && getComputedStyle(document.body).overflowY === 'hidden') root.scrollTop = 0;
}, { passive: true });

// Where the visible tab starts, so CSS can size it to end at the bottom of the
// screen (the pill and the bookmark strip above it change height).
(function () {
    const fit = () => {
        const root = document.documentElement;
        if (window.innerWidth > 1200) { root.style.removeProperty('--pane-top'); return; }
        const pane = [...document.querySelectorAll('.pane')].find(p => p.offsetParent !== null);
        if (pane) root.style.setProperty('--pane-top', `${Math.max(0, Math.round(pane.getBoundingClientRect().top))}px`);
    };
    window.addEventListener('resize', fit);
    document.addEventListener('DOMContentLoaded', () => {
        fit();
        const strip = document.querySelector('.bookmark-strip');
        if (strip && typeof ResizeObserver !== 'undefined') new ResizeObserver(fit).observe(strip);
        if (typeof MutationObserver !== 'undefined') {
            const mo = new MutationObserver(fit);
            document.querySelectorAll('.pane').forEach(p => mo.observe(p, { attributes: true, attributeFilter: ['style'] }));
        }
    });
})();
