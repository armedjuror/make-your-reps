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
        Timeline.events = [];
        Timeline.hasMore = true;
        await Timeline.loadEvents();
        if (typeof General !== 'undefined' && General.loadProductivityScore) General.loadProductivityScore();
        if (typeof Gamification !== 'undefined' && Gamification.load) Gamification.load();
    },

    // ── Styles ───────────────────────────────────────────────
    _injectStyles() {
        if (document.getElementById('resilient-css')) return;
        const css = `
        .rs-bar{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:0 0 10px}
        .rs-chip{border:1px solid var(--border-color,#ccc);background:transparent;color:inherit;border-radius:999px;padding:3px 12px;font-size:.8rem;cursor:pointer}
        .rs-chip:hover{background:rgba(127,127,127,.12)}
        .rs-chip.rs-light{border-color:#d4a017}
        .rs-chip.rs-disrupted{border-color:#c0392b}
        .rs-menu{position:absolute;z-index:50;background:var(--card-bg,#fff);color:inherit;border:1px solid var(--border-color,#ccc);border-radius:10px;padding:6px;min-width:190px;box-shadow:0 6px 24px rgba(0,0,0,.18)}
        .rs-menu h6{font-size:.7rem;text-transform:uppercase;letter-spacing:.05em;opacity:.6;margin:6px 8px 2px}
        .rs-menu button{display:block;width:100%;text-align:left;background:none;border:0;color:inherit;padding:5px 8px;border-radius:6px;font-size:.85rem;cursor:pointer}
        .rs-menu button:hover{background:rgba(127,127,127,.15)}
        .rs-menu button.on{font-weight:600}
        .rs-banner{font-size:.8rem;opacity:.85;margin:0 0 8px}
        .rs-warn{font-size:.8rem;color:#c0392b;margin:0 0 8px}
        .rs-metrics{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 10px}
        .rs-metric{display:flex;align-items:center;gap:6px;border:1px solid var(--border-color,#ccc);border-radius:10px;padding:4px 8px;font-size:.8rem}
        .rs-metric.rs-over{border-color:#c0392b}
        .rs-metric.rs-met{border-color:#2e8b57}
        .rs-metric button{border:1px solid var(--border-color,#ccc);background:transparent;color:inherit;border-radius:6px;padding:0 7px;font-size:.78rem;cursor:pointer}
        .tl-st-done .timeline-event-text,.tl-st-skipped .timeline-event-text,.tl-st-dropped .timeline-event-text{opacity:.55}
        .tl-st-dropped .timeline-event-text{text-decoration:line-through}
        .tl-st-missed .timeline-event-text{color:#c0392b}
        .rs-tier{font-size:.65rem;text-transform:uppercase;letter-spacing:.05em;opacity:.55;margin-left:6px}
        .rs-note{font-size:.72rem;opacity:.65;margin-left:6px}
        .rs-link{background:none;border:0;color:inherit;opacity:.65;font-size:.75rem;text-decoration:underline;cursor:pointer;padding:0 4px}
        .rs-steps{margin:6px 0}
        .rs-steps label{display:flex;gap:6px;align-items:center;font-size:.85rem;margin:2px 0}
        .rs-overlay{position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:2000;display:flex;align-items:center;justify-content:center}
        .rs-dialog{background:var(--card-bg,#fff);color:inherit;border-radius:12px;padding:18px;width:min(92vw,360px);box-shadow:0 10px 40px rgba(0,0,0,.3)}
        .rs-dialog h5{margin:0 0 10px;font-size:1rem}
        .rs-dialog input,.rs-dialog select,.rs-dialog textarea{width:100%;margin:4px 0 8px;padding:6px 8px;border-radius:6px;border:1px solid var(--border-color,#ccc);background:transparent;color:inherit}
        .rs-dialog .rs-row{display:flex;gap:8px;justify-content:flex-end;margin-top:6px}
        .rs-err{color:#c0392b;font-size:.8rem;min-height:1em}
        .rs-chips{display:flex;flex-wrap:wrap;gap:4px;margin-bottom:6px}
        `;
        const style = document.createElement('style');
        style.id = 'resilient-css';
        style.textContent = css;
        document.head.appendChild(style);
    },

    // ── Boot ─────────────────────────────────────────────────
    init() {
        this._injectStyles();
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
        const row = document.querySelector('.timeline-bar');
        if (!row) return;
        const bar = document.createElement('div');
        bar.id = 'day-bar';
        bar.style.cssText = 'display:flex;flex-wrap:wrap;gap:6px;align-items:center';
        row.appendChild(bar);
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
        let html = `<button type="button" class="rs-chip rs-${this.esc(d.mode)}" data-rs="menu-day" ${editable ? '' : 'disabled'}>${tpl} &middot; ${mode} <i class="fas fa-chevron-down" style="font-size:.6rem"></i></button>`;
        if (today) {
            html += '<button type="button" class="rs-chip" data-rs="menu-late"><i class="fas fa-person-running"></i> Running late</button>';
            html += '<button type="button" class="rs-chip" data-rs="slip"><i class="fas fa-heart-crack"></i> I slipped</button>';
        }
        if (editable) html += '<button type="button" class="rs-chip" data-rs="travel"><i class="fas fa-plane"></i> Travelling&hellip;</button>';
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
        m.className = 'rs-menu';
        m.innerHTML = html;
        const r = anchor.getBoundingClientRect();
        m.style.top = `${window.scrollY + r.bottom + 4}px`;
        m.style.left = `${Math.max(8, window.scrollX + r.left)}px`;
        document.body.appendChild(m);
    },

    _dayMenu(anchor) {
        const d = this.day;
        const opt = (rs, val, label, cur) =>
            `<button type="button" data-rs="${rs}" data-val="${val}" class="${cur === val ? 'on' : ''}">${label}</button>`;
        this._menu(anchor,
            '<h6>Day type</h6>' + opt('set-template', 'workday', 'Workday', d.template) + opt('set-template', 'holiday', 'Holiday', d.template) +
            '<h6>Mode</h6>' + opt('set-mode', 'normal', 'Normal &mdash; everything', d.mode) +
            opt('set-mode', 'light', 'Light &mdash; essentials + anchors', d.mode) +
            opt('set-mode', 'disrupted', 'Disrupted &mdash; essentials only', d.mode));
    },

    _lateMenu(anchor) {
        this._menu(anchor, '<h6>Running late by</h6>' +
            [15, 30, 60].map(m => `<button type="button" data-rs="late" data-val="${m}">${m} minutes</button>`).join(''));
    },

    async setDayPlan(patch) {
        if (!this.day) return;
        const res = await this._call('put', `board/api/day_plans/${this.day.date}/`, patch);
        if (res.status === 'success') await this._refresh();
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
            ? `<div class="rs-steps">${steps.map(s => `<label><input type="checkbox" data-rs="reset-step" data-step="${this.esc(s.id)}" ${s.done ? 'checked' : ''}> ${this.esc(s.name)}</label>`).join('')}</div>`
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
        if (event.tier) out += `<span class="rs-tier">${this.esc(event.tier)}</span>`;
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
    dialog(title, bodyHtml, buttons) {
        const ov = document.createElement('div');
        ov.className = 'rs-overlay';
        ov.innerHTML = `<div class="rs-dialog" role="dialog" aria-modal="true"><h5>${this.esc(title)}</h5>${bodyHtml}
            <div class="rs-err"></div>
            <div class="rs-row">${buttons.map((b, i) => `<button type="button" class="btn btn-paper btn-sm ${b.primary ? 'btn-primary' : ''}" data-idx="${i}">${this.esc(b.label)}</button>`).join('')}</div></div>`;
        const close = () => ov.remove();
        ov.addEventListener('click', async (ev) => {
            if (ev.target === ov) return close();
            const btn = ev.target.closest('button[data-idx]');
            if (!btn) return;
            const spec = buttons[Number(btn.dataset.idx)];
            const err = ov.querySelector('.rs-err');
            err.textContent = '';
            if (!spec.run) return close();
            const out = await spec.run(ov);
            if (out === true) close();
            else if (typeof out === 'string') err.textContent = out;
        });
        document.body.appendChild(ov);
        const first = ov.querySelector('input,select,textarea');
        if (first) first.focus();
        return ov;
    },

    slipDialog() {
        this.dialog('I slipped', '<p style="font-size:.85rem;margin:0 0 6px">That is okay. This stays private. Want to note what happened?</p><textarea rows="2" maxlength="280" placeholder="Optional note"></textarea>', [
            { label: 'Cancel' },
            { label: 'Log it', primary: true, run: async (ov) => {
                const note = ov.querySelector('textarea').value;
                const res = await apiClient.post('board/api/lapses/', { note });
                if (res.status !== 'success') return res.error || 'Could not log that';
                await this._refresh();
                return true;
            } },
        ]);
    },

    travelDialog() {
        const t = this.logicalToday();
        this.dialog('I’m travelling', `<label style="font-size:.8rem">From</label><input type="date" id="rs-t-from" value="${t}" min="${t}">
            <label style="font-size:.8rem">To</label><input type="date" id="rs-t-to" value="${t}" min="${t}">
            <p style="font-size:.78rem;opacity:.7;margin:0">Those days become Disrupted, followed by a few Light days to ease back in.</p>`, [
            { label: 'Cancel' },
            { label: 'Set travel', primary: true, run: async (ov) => {
                const start = ov.querySelector('#rs-t-from').value, end = ov.querySelector('#rs-t-to').value;
                if (!start || !end || end < start) return 'Choose a valid date range';
                const res = await apiClient.post('board/api/day_plans/travel/', { start, end });
                if (res.status !== 'success') return res.error || 'Could not set travel';
                await this._refresh();
                return true;
            } },
        ]);
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
            const label = this.esc(f.label || f.name || f.key);
            const chips = ((m.chips || {})[f.key || f.name] || []).slice(0, 6);
            return `<label style="font-size:.8rem">${label}</label>
                <div class="rs-chips">${chips.map(c => `<button type="button" class="rs-chip" data-chip="${i}" data-v="${this.esc(c)}">${this.esc(c)}</button>`).join('')}</div>
                <input data-field="${this.esc(f.key || f.name)}" type="text" maxlength="64">`;
        }).join('');
        const needValue = m.kind !== 'counter';
        const ov = this.dialog(`Log ${m.name}`,
            `${needValue ? `<label style="font-size:.8rem">Value ${this.esc(m.unit ? '(' + m.unit + ')' : '')}</label><input id="rs-m-val" type="number" step="any">` : ''}
             ${fields}<label style="font-size:.8rem">Note</label><input id="rs-m-note" type="text" maxlength="280">`, [
            { label: 'Cancel' },
            { label: 'Log', primary: true, run: async (o) => {
                const data = {};
                o.querySelectorAll('[data-field]').forEach(i => { if (i.value.trim()) data[i.dataset.field] = i.value.trim(); });
                const valEl = o.querySelector('#rs-m-val');
                const value = valEl ? Number(valEl.value) : 1;
                if (valEl && (valEl.value === '' || Number.isNaN(value))) return 'Enter a value';
                const res = await apiClient.post(`board/api/metrics/${id}/log/`, {
                    value, data, note: o.querySelector('#rs-m-note').value,
                });
                if (res.status !== 'success') return res.error || 'Could not log that';
                await this.loadMetrics(); await this._refresh();
                return true;
            } },
        ]);
        ov.addEventListener('click', (ev) => {
            const chip = ev.target.closest('[data-chip]');
            if (!chip) return;
            const inputs = ov.querySelectorAll('[data-field]');
            const input = inputs[Number(chip.dataset.chip)];
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
            icon.style.cssText = 'position:fixed;right:12px;bottom:12px;z-index:900;border:1px solid var(--border-color,#ccc);background:var(--card-bg,#fff);color:inherit;border-radius:50%;width:34px;height:34px;cursor:pointer;opacity:.7';
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
        this.dialog('Unlock private items', '<input id="rs-pin" type="password" inputmode="numeric" autocomplete="off" placeholder="PIN">', [
            { label: 'Forgot PIN', run: async () => { this.resetPinDialog(); return true; } },
            { label: 'Unlock', primary: true, run: async (o) => {
                const res = await apiClient.post('board/api/private/unlock/', { pin: o.querySelector('#rs-pin').value });
                if (res.status !== 'success') return res.error || 'Wrong PIN';
                await this._afterPrivacyChange();
                return true;
            } },
        ]).querySelector('#rs-pin').addEventListener('keydown', (e) => {
            if (e.key === 'Enter') e.target.closest('.rs-dialog').querySelector('.btn-primary').click();
        });
    },

    pinSetupDialog() {
        this.dialog('Set a PIN for private items', '<input id="rs-pin" type="password" inputmode="numeric" autocomplete="off" placeholder="New PIN (4 to 12 digits)"><input id="rs-pin2" type="password" inputmode="numeric" autocomplete="off" placeholder="Repeat PIN">', [
            { label: 'Cancel' },
            { label: 'Save PIN', primary: true, run: async (o) => {
                const pin = o.querySelector('#rs-pin').value;
                if (pin !== o.querySelector('#rs-pin2').value) return 'PINs do not match';
                const res = await apiClient.post('board/api/private/pin/', { pin });
                if (res.status !== 'success') return res.error || 'Could not set PIN';
                await this._afterPrivacyChange();
                return true;
            } },
        ]);
    },

    resetPinDialog() {
        this.dialog('Reset PIN', '<p style="font-size:.85rem;margin:0 0 6px">We will email you a code.</p><input id="rs-code" type="text" placeholder="Code from email"><input id="rs-pin" type="password" inputmode="numeric" autocomplete="off" placeholder="New PIN">', [
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
        const sel = (key, val, opts) => `<select data-hopt="${key}" class="form-control form-control-sm d-inline-block" style="width:auto">${
            opts.map(([v, l]) => `<option value="${v}" ${val === v ? 'selected' : ''}>${l}</option>`).join('')}</select>`;
        box.dataset.habit = habit.id;
        box.innerHTML = `
            <h6>Hard days</h6>
            <div class="small mb-1">On Light days ${sel('on_light', h.on_light || 'required', [['required', 'still required'], ['excused', 'excused']])}</div>
            <div class="small mb-2">On Disrupted days ${sel('on_disrupted', h.on_disrupted || 'excused', [['required', 'still required'], ['excused', 'excused']])}</div>
            <label class="small d-block"><input type="checkbox" data-hopt="is_private" ${h.is_private ? 'checked' : ''}> Private (hidden until you unlock)</label>
            <label class="small d-block mb-2"><input type="checkbox" data-hopt="private_reminder" ${h.private_reminder ? 'checked' : ''}> Show a plain &ldquo;Reminder&rdquo; while locked</label>
            <h6>Checklist</h6>
            <div class="small mb-1">Complete when ${sel('complete_when', h.complete_when || 'all', [['all', 'all steps are done'], ['any', 'any step is done'], ['final', 'the last step is done']])}</div>
            <div id="rs-steps-list">${steps.map(st => `<div class="d-flex align-items-center gap-2 small mb-1"><span class="flex-grow-1">${this.esc(st.name)}</span><button type="button" class="rs-link" data-hstep="del" data-id="${st.id}">Remove</button></div>`).join('')}</div>
            <div class="d-flex gap-2 mt-1"><input type="text" id="rs-new-step" class="form-control form-control-sm" maxlength="80" placeholder="Add a step"><button type="button" class="btn btn-paper btn-sm" data-hstep="add">Add</button></div>`;
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
        card.className = 'mt-4';
        card.innerHTML = '<h6>Days &amp; streaks</h6><div id="rs-settings-body" style="font-size:.85rem"></div>';
        host.appendChild(card);
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
        body.innerHTML = `
            <div class="mb-2">Weekend days<div class="rs-chips">${names.map((n, i) =>
                `<label style="margin-right:8px"><input type="checkbox" data-set="weekend" value="${i}" ${wk.includes(i) ? 'checked' : ''}> ${n}</label>`).join('')}</div></div>
            <label>Day starts at <input type="time" data-set="day_start" value="${this.esc((d.day_start || '04:00').slice(0, 5))}"></label>
            <label class="d-block mt-2">Travel ramp (Light days after travel) <input type="number" min="0" max="7" data-set="travel_ramp_days" value="${this.esc(d.travel_ramp_days ?? 2)}"></label>
            <label class="d-block mt-2">Streak counts
                <select data-set="streak_rule">
                    <option value="activity" ${d.streak_rule !== 'routine' ? 'selected' : ''}>Any activity (default)</option>
                    <option value="routine" ${d.streak_rule === 'routine' ? 'selected' : ''}>Routine met (essentials + anchors)</option>
                </select></label>
            <label class="d-block mt-2">&ldquo;I slipped&rdquo; counts on
                <select data-set="slip_metric">
                    <option value="">Nothing (just opens the reset)</option>
                    ${metrics.filter(m => m.kind !== 'single').map(m => `<option value="${m.id}" ${d.slip_metric === m.id ? 'selected' : ''}>${this.esc(m.name)}</option>`).join('')}
                </select></label>
            <div class="mt-2"><button type="button" class="btn btn-paper btn-sm" data-rs="pin-setup">${this.privateState.has_pin ? 'Change PIN' : 'Set a PIN for private items'}</button></div>`;
        body.addEventListener('change', (e) => this._saveSetting(e), { once: false });
        body.querySelector('[data-rs="pin-setup"]').addEventListener('click', () => this.pinSetupDialog());
    },

    async _saveSetting(e) {
        const el = e.target.closest('[data-set]');
        if (!el) return;
        const key = el.dataset.set;
        let payload;
        if (key === 'weekend') {
            payload = { weekend_days: [...document.querySelectorAll('[data-set="weekend"]:checked')].map(i => Number(i.value)) };
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
