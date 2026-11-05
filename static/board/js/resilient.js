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
        if (editable) html += '<button type="button" class="timeline-chip rs-chip" data-rs="travel"><i class="fas fa-plane"></i> Travelling&hellip;</button>';
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
    say(...lines) { return `<div class="conversational-form">${lines.filter(Boolean).map(l => `<div class="convo-line">${l}</div>`).join('')}</div>`; },
    /** An inline choice inside a sentence. opts: [[value, label], ...] */
    pick(attrs, val, opts) {
        return `<select class="form-input" ${attrs}>${opts.map(([v, l]) => `<option value="${v}" ${String(val) === String(v) ? 'selected' : ''}>${l}</option>`).join('')}</select>`;
    },
    hint(text) { return `<small class="text-brown ms-1">${text}</small>`; },
    /** Assistant line shown above the sentence, like #habit_message. */
    lead(text) { return `<div class="rs-lead">${text}</div>`; },

    /**
     * A real Bootstrap modal built like the app's own (modal-content, modal-icon,
     * btn-paper, form-control), so style.css themes it. Removed when hidden.
     */
    dialog(title, bodyHtml, buttons, icon = 'fa-pen') {
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
        el.addEventListener('shown.bs.modal', () => { const f = el.querySelector('.modal-body input:not([type=checkbox]):not([type=hidden]),.modal-body textarea'); if (f) f.focus(); });
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
        this.dialog('I slipped', this.lead('That&rsquo;s okay. One slip doesn&rsquo;t undo your progress, and this stays private.') +
            this.say(`What happened was <input type="text" class="form-input rs-wide" id="rs-slip-note" maxlength="280" placeholder="optional, just for you">`), [
            { label: 'Cancel' },
            { label: 'Log it', primary: true, run: async (ov) => {
                const res = await apiClient.post('board/api/lapses/', { note: ov.querySelector('#rs-slip-note').value });
                if (res.status !== 'success') return res.error || 'Could not log that';
                await this._refresh();
                return true;
            } },
        ], 'fa-heart-crack');
    },

    travelDialog() {
        const t = this.logicalToday();
        this.dialog('I\u2019m travelling', this.lead('Travel days run on essentials only, then a few Light days help you ease back in.') +
            this.say(`I&rsquo;m travelling from <input type="date" class="form-input" id="rs-t-from" value="${t}" min="${t}">`,
                     `until <input type="date" class="form-input" id="rs-t-to" value="${t}" min="${t}">`), [
            { label: 'Cancel' },
            { label: 'Set travel', primary: true, run: async (ov) => {
                const start = ov.querySelector('#rs-t-from').value, end = ov.querySelector('#rs-t-to').value;
                if (!start || !end || end < start) return 'Choose a valid date range';
                const res = await apiClient.post('board/api/day_plans/travel/', { start, end });
                if (res.status !== 'success') return res.error || 'Could not set travel';
                await this._refresh();
                return true;
            } },
        ], 'fa-plane');
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
        const num = '<input id="rs-m-val" type="number" step="any" class="form-input rs-num" placeholder="0">';
        const first = m.kind === 'counter' ? `One more ${name}.`
            : m.kind === 'single' ? `Today my ${name} was ${num} ${unit}`
            : `Add ${num} ${unit} to my ${name}`;
        const fields = (m.fields || []).map((f, i) => {
            const key = f.key || f.name;
            const raw = f.label || key;
            const label = this.esc(raw.charAt(0).toUpperCase() + raw.slice(1));
            const chips = ((m.chips || {})[key] || []).slice(0, 6);
            const pick = chips.length ? ` <span class="freq-days">${chips.map(c => `<button type="button" class="freq-day-btn" data-chip="${i}" data-v="${this.esc(c)}">${this.esc(c)}</button>`).join('')}</span>` : '';
            const input = f.type === 'scale'
                ? `<input data-field="${this.esc(key)}" type="number" min="1" max="${f.max || 10}" class="form-input rs-num" placeholder="1&ndash;${f.max || 10}">`
                : `<input data-field="${this.esc(key)}" type="text" maxlength="64" class="form-input" placeholder="${f.type === 'choice' && f.options ? this.esc(f.options.slice(0, 2).join(', ')) : ''}">`;
            return `${label}? ${input}${pick}`;
        });
        const ov = this.dialog(`Log ${m.name}`,
            this.say(first, ...fields, `and a note: <input id="rs-m-note" type="text" maxlength="280" class="form-input rs-wide" placeholder="optional">`), [
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
        let icon = document.getElementById('rs-lock-icon');
        if (!this.privateState.has_pin) { if (icon) icon.remove(); return; }
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

    async _afterPrivacyChange() {
        await this.loadPrivateStatus();
        await this.loadMetrics();
        await this._refresh();
        if (typeof Habits !== 'undefined' && Habits.init) Habits.init();
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
        this.dialog('Unlock private items', this.say('My PIN is <input id="rs-pin" type="password" inputmode="numeric" autocomplete="off" class="form-input rs-num" placeholder="&bull;&bull;&bull;&bull;">'), [
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
            this.say('My new PIN is <input id="rs-pin" type="password" inputmode="numeric" autocomplete="off" class="form-input rs-num" placeholder="4&ndash;12 digits">',
                     'and once more: <input id="rs-pin2" type="password" inputmode="numeric" autocomplete="off" class="form-input rs-num" placeholder="repeat">'), [
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
            this.say('The code I got is <input id="rs-code" type="text" autocomplete="one-time-code" class="form-input rs-num" placeholder="123456">',
                     'and my new PIN is <input id="rs-pin" type="password" inputmode="numeric" autocomplete="off" class="form-input rs-num" placeholder="4&ndash;12 digits">'), [
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
        modal.addEventListener('change', (e) => {
            const el = e.target.closest('[data-hopt]');
            if (el) this._saveHabitOption(el);
        });
        modal.addEventListener('click', (e) => {
            const b = e.target.closest('[data-hstep]');
            if (b) this._habitStepAction(b);
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
            box.className = 'mt-4 pt-3 border-top';
            const body = modal.querySelector('.modal-body') || modal;
            body.appendChild(box);
        }
        const [hres, sres] = await Promise.all([
            apiClient.get(`board/api/habits/${habit.id}/`, { silent: true }),
            apiClient.get(`board/api/habits/${habit.id}/steps/`, { silent: true }),
        ]);
        const h = hres.status === 'success' ? hres.data : {};
        const steps = sres.status === 'success' ? sres.data.steps : [];
        const mres = await apiClient.get('board/api/metrics/', { silent: true });
        const metrics = mres.status === 'success' ? mres.data : [];
        box.dataset.habit = habit.id;
        box.innerHTML = `<h6 class="mb-2">On hard days and privacy:</h6>` + this.say(
            `On Light days this habit is ${this.pick('data-hopt="on_light"', h.on_light || 'required', [['required', 'still required'], ['excused', 'excused']])}`,
            `and on Disrupted days it&rsquo;s ${this.pick('data-hopt="on_disrupted"', h.on_disrupted || 'excused', [['excused', 'excused'], ['required', 'still required']])}.`,
            `Keep it ${this.pick('data-hopt="is_private"', h.is_private ? 'true' : 'false', [['false', 'visible'], ['true', 'private until I unlock']])}`,
            h.is_private ? `and while locked, remind me with ${this.pick('data-hopt="private_reminder"', h.private_reminder ? 'true' : 'false', [['false', 'nothing'], ['true', 'a plain &ldquo;Reminder&rdquo;']])}.` : '',
            `Track it with ${this.pick('data-hopt="metric"', h.metric ?? '', [['', 'no tracker'], ...metrics.map(m => [m.id, this.esc(m.name)])])}.`,
        ) + `<h6 class="mt-3 mb-2">Steps:</h6>` + this.say(
            steps.length ? `Count it done when ${this.pick('data-hopt="complete_when"', h.complete_when || 'all', [['all', 'all the steps'], ['any', 'any step'], ['final', 'the last step']])} ${h.complete_when === 'any' || h.complete_when === 'final' ? 'is' : 'are'} ticked.` : '',
            ...steps.map((st, i) => `${i + 1}. ${this.esc(st.name)} <button type="button" class="tl-link ms-1" data-hstep="del" data-id="${st.id}">remove</button>`),
            `${steps.length ? 'Then' : 'First'} I <input type="text" id="rs-new-step" class="form-input" maxlength="80" placeholder="${steps.length ? 'add another step' : 'add a step'}"> <button type="button" class="btn btn-paper btn-sm" data-hstep="add">Add</button>`,
        );
        const input = box.querySelector('#rs-new-step');
        input.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); box.querySelector('[data-hstep="add"]').click(); } });
    },

    async _saveHabitOption(el) {
        const id = document.getElementById('rs-habit-options').dataset.habit;
        const key = el.dataset.hopt;
        let value = el.value;
        if (key === 'is_private' || key === 'private_reminder') value = value === 'true';
        if (key === 'metric') value = value ? Number(value) : null;
        const res = await this._call('patch', `board/api/habits/${id}/`, { [key]: value });
        if (res.status === 'success') {
            if (typeof loadHabits === 'function') loadHabits();
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

    // ── Settings card ────────────────────────────────────────
    mountSettings() {
        const host = document.getElementById('sp-general');
        if (!host || document.getElementById('rs-settings')) return;
        const card = document.createElement('div');
        card.id = 'rs-settings';
        card.className = 'settings-card mt-4';
        card.innerHTML = '<h6 class="settings-card-title"><i class="fas fa-calendar-day me-2"></i>Days &amp; streaks</h6><div id="rs-settings-body"></div>';
        host.appendChild(card);
        card.addEventListener('change', (e) => this._saveSetting(e));
        card.addEventListener('click', (e) => {
            const day = e.target.closest('[data-set="weekend"]');
            if (day) { day.classList.toggle('active'); this._saveSetting({ target: day }); }
            if (e.target.closest('[data-rs-set="pin"]')) this.pinSetupDialog();
        });
        this.renderSettings();
    },

    async renderSettings() {
        const body = document.getElementById('rs-settings-body');
        if (!body) return;
        const d = typeof AppConfig !== 'undefined' ? AppConfig.userDetail : null;
        if (!d) return setTimeout(() => this.renderSettings(), 800);
        const mres = await apiClient.get('board/api/metrics/', { silent: true });
        const metrics = mres.status === 'success' ? mres.data : [];
        const names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
        const wk = d.weekend_days || [5, 6];
        const opt = (v, l, cur) => `<option value="${v}" ${String(cur) === String(v) ? 'selected' : ''}>${l}</option>`;
        body.innerHTML = `
            <div class="mb-3"><label class="form-label">Weekend days</label>
                <div class="freq-days">${names.map((n, i) => `<button type="button" class="freq-day-btn ${wk.includes(i) ? 'active' : ''}" data-set="weekend" data-day="${i}">${n}</button>`).join('')}</div>
                <small class="form-text text-brown">These days use the Holiday routine unless you change the day.</small></div>
            <div class="mb-3"><label class="form-label">Day starts at</label>
                <input type="time" class="form-control" data-set="day_start" value="${this.esc((d.day_start || '04:00').slice(0, 5))}">
                <small class="form-text text-brown">Anything before this time still counts for the previous day.</small></div>
            <div class="mb-3"><label class="form-label">Light days after travel</label>
                <input type="number" class="form-control" min="0" max="7" data-set="travel_ramp_days" value="${this.esc(d.travel_ramp_days ?? 2)}"></div>
            <div class="mb-3"><label class="form-label">Streak counts</label>
                <select class="form-control" data-set="streak_rule">${opt('activity', 'Any activity (default)', d.streak_rule || 'activity')}${opt('routine', 'Routine met (essentials and anchors)', d.streak_rule)}</select></div>
            <div class="mb-3"><label class="form-label">&ldquo;I slipped&rdquo; adds one to</label>
                <select class="form-control" data-set="slip_metric">${opt('', 'Nothing (just opens the reset)', d.slip_metric ?? '')}${metrics.filter(m => m.kind !== 'single').map(m => opt(m.id, this.esc(m.name), d.slip_metric)).join('')}</select></div>
            <div class="mb-0"><label class="form-label">Private items</label>
                <div><button type="button" class="btn btn-paper btn-sm btn-primary" data-rs-set="pin">${this.privateState.has_pin ? 'Change PIN' : 'Set a PIN'}</button></div>
                <small class="form-text text-brown">Type /private in the search bar or press Ctrl+Shift+L to show or hide them.</small></div>`;
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
        } else if (key === 'slip_metric') {
            payload = { slip_metric: el.value ? Number(el.value) : null };
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
