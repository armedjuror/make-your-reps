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
    /** Markup helpers: the same field classes the rest of the app uses. */
    field(label, control, hint) {
        return `<label class="form-label">${label}</label>${control}${hint ? `<div class="form-text">${hint}</div>` : ''}`;
    },
    check(attrs, label, checked) {
        const id = 'rs-c-' + Math.random().toString(36).slice(2, 8);
        return `<div class="form-check form-switch"><input class="form-check-input" type="checkbox" id="${id}" ${attrs} ${checked ? 'checked' : ''}><label class="form-check-label" for="${id}">${label}</label></div>`;
    },

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
        el.querySelectorAll('input:not([type=checkbox]):not([type=radio]), textarea, select').forEach(x => x.classList.add('form-control'));
        document.body.appendChild(el);
        const modal = new bootstrap.Modal(el);
        el.addEventListener('hidden.bs.modal', () => { modal.dispose(); el.remove(); });
        el.addEventListener('shown.bs.modal', () => { const f = el.querySelector('.modal-body input:not([type=checkbox]),.modal-body select,.modal-body textarea'); if (f) f.focus(); });
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
        this.dialog('I slipped', `<p>That&rsquo;s okay. This stays private, and the reset card will help you get back on track.</p>
            ${this.field('What happened? (optional)', '<textarea rows="2" maxlength="280"></textarea>')}`, [
            { label: 'Cancel' },
            { label: 'Log it', primary: true, run: async (ov) => {
                const res = await apiClient.post('board/api/lapses/', { note: ov.querySelector('textarea').value });
                if (res.status !== 'success') return res.error || 'Could not log that';
                await this._refresh();
                return true;
            } },
        ], 'fa-heart-crack');
    },

    travelDialog() {
        const t = this.logicalToday();
        this.dialog('I\u2019m travelling',
            this.field('From', `<input type="date" id="rs-t-from" value="${t}" min="${t}">`) +
            this.field('To', `<input type="date" id="rs-t-to" value="${t}" min="${t}">`,
                'Those days become Disrupted, followed by a few Light days to ease back in.'), [
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
        const fields = (m.fields || []).map((f, i) => {
            const key = f.key || f.name;
            const chips = ((m.chips || {})[key] || []).slice(0, 6);
            const pick = chips.length ? `<div class="rs-pick">${chips.map(c => `<button type="button" class="freq-day-btn" data-chip="${i}" data-v="${this.esc(c)}">${this.esc(c)}</button>`).join('')}</div>` : '';
            const input = f.type === 'scale'
                ? `<input data-field="${this.esc(key)}" type="number" min="1" max="${f.max || 10}" placeholder="1 to ${f.max || 10}">`
                : `<input data-field="${this.esc(key)}" type="text" maxlength="64">`;
            return this.field(this.esc(f.label || key), pick + input);
        }).join('');
        const needValue = m.kind !== 'counter';
        const ov = this.dialog(`Log ${m.name}`,
            (needValue ? this.field(`Value${m.unit ? ' (' + this.esc(m.unit) + ')' : ''}`, '<input id="rs-m-val" type="number" step="any">') : '') +
            fields + this.field('Note (optional)', '<input id="rs-m-note" type="text" maxlength="280">'), [
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
        this.dialog('Unlock private items', this.field('PIN', '<input id="rs-pin" type="password" inputmode="numeric" autocomplete="off">'), [
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
            this.field('New PIN', '<input id="rs-pin" type="password" inputmode="numeric" autocomplete="off">', '4 to 12 digits') +
            this.field('Repeat PIN', '<input id="rs-pin2" type="password" inputmode="numeric" autocomplete="off">'), [
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
        this.dialog('Reset PIN', '<p>We&rsquo;ll email you a code.</p>' +
            this.field('Code from email', '<input id="rs-code" type="text" autocomplete="one-time-code">') +
            this.field('New PIN', '<input id="rs-pin" type="password" inputmode="numeric" autocomplete="off">'), [
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
            box.className = 'mt-3';
            const body = modal.querySelector('.modal-body') || modal;
            body.appendChild(box);
        }
        const [hres, sres] = await Promise.all([
            apiClient.get(`board/api/habits/${habit.id}/`, { silent: true }),
            apiClient.get(`board/api/habits/${habit.id}/steps/`, { silent: true }),
        ]);
        const h = hres.status === 'success' ? hres.data : {};
        const steps = sres.status === 'success' ? sres.data.steps : [];
        const sel = (key, val, opts) => `<select data-hopt="${key}" class="form-control">${
            opts.map(([v, l]) => `<option value="${v}" ${val === v ? 'selected' : ''}>${l}</option>`).join('')}</select>`;
        box.dataset.habit = habit.id;
        box.innerHTML = `
            <div class="settings-card mt-3">
                <h6 class="settings-card-title"><i class="fas fa-cloud-sun-rain me-2"></i>Hard days</h6>
                ${this.field('On Light days', sel('on_light', h.on_light || 'required', [['required', 'Still required'], ['excused', 'Excused']]))}
                ${this.field('On Disrupted days', sel('on_disrupted', h.on_disrupted || 'excused', [['required', 'Still required'], ['excused', 'Excused']]))}
                <div class="mt-3">${this.check('data-hopt="is_private"', 'Private (hidden until you unlock)', h.is_private)}
                ${this.check('data-hopt="private_reminder"', 'Show a plain &ldquo;Reminder&rdquo; while locked', h.private_reminder)}</div>
            </div>
            <div class="settings-card mt-3">
                <h6 class="settings-card-title"><i class="fas fa-list-check me-2"></i>Checklist</h6>
                ${this.field('Complete when', sel('complete_when', h.complete_when || 'all', [['all', 'All steps are done'], ['any', 'Any step is done'], ['final', 'The last step is done']]))}
                <div id="rs-steps-list" class="mt-2">${steps.map(st => `<div class="d-flex align-items-center gap-2 py-1"><span class="flex-grow-1">${this.esc(st.name)}</span><button type="button" class="rs-link" data-hstep="del" data-id="${st.id}">Remove</button></div>`).join('') || '<div class="form-text">No steps yet.</div>'}</div>
                <div class="d-flex gap-2 mt-2 align-items-end"><input type="text" id="rs-new-step" class="form-control" maxlength="80" placeholder="Add a step"><button type="button" class="btn btn-paper btn-sm" data-hstep="add">Add</button></div>
            </div>`;
    },

    async _saveHabitOption(el) {
        const id = document.getElementById('rs-habit-options').dataset.habit;
        const key = el.dataset.hopt;
        const value = el.type === 'checkbox' ? el.checked : el.value;
        const res = await this._call('patch', `board/api/habits/${id}/`, { [key]: value });
        if (res.status === 'success' && typeof loadHabits === 'function') loadHabits();
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
