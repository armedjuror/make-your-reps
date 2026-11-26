/**
 * Squads UI: right dock (desktop), Squads | Bookmarks pager (mobile), slide-over,
 * Squads page, squad page (Today · Goals · Leaderboard · Focus · Challenges · Feed ·
 * Heatmap · Settings), Today pulse (at-risk + nudges), push setup.
 *
 * Forms are conversational sentences, like the New Habit modal.
 */
const Squads = {
    boards: [],
    current: null,       // squad detail being shown
    tab: 'today',
    flags: {},
    TABS: ['today', 'goals', 'leaderboard', 'focus', 'challenges', 'feed', 'heatmap', 'settings'],
    TAB_LABELS: { today: 'Today', goals: 'Goals', leaderboard: 'Leaderboard', focus: 'Focus', challenges: 'Challenges',
                  feed: 'Feed', heatmap: 'Heatmap', settings: 'Settings' },

    // ── plumbing ──
    esc(s) { const d = document.createElement('div'); d.textContent = s == null ? '' : String(s); return d.innerHTML; },
    api(path) { return `squads/api/${path}`; },
    async get(path) { return apiClient.get(this.api(path), { silent: true }); },
    async send(method, path, body) {
        return apiClient.makeRequest(this.api(path), { method, body: JSON.stringify(body || {}), silent: method === 'GET' });
    },
    ok(res) { return res && res.status === 'success'; },
    fail(res, fallback) {
        if (res && res.error === 'limit_reached') {
            showError(res.message + ' The owner can upgrade from Settings.', 'Plan limit');
        } else {
            showError((res && res.error) || fallback || 'Something went wrong');
        }
    },
    tz() { try { return Intl.DateTimeFormat().resolvedOptions().timeZone; } catch (e) { return null; } },
    when(iso) {
        const d = new Date(iso);
        return d.toLocaleString(undefined, { weekday: 'short', day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' });
    },
    ago(iso) {
        const m = Math.round((Date.now() - new Date(iso)) / 60000);
        if (m < 1) return 'just now';
        if (m < 60) return `${m} min ago`;
        if (m < 1440) return `${Math.round(m / 60)} h ago`;
        return new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
    },
    initials(name) { return (name || '?').split(/\s+/).slice(0, 2).map(w => w[0]).join('').toUpperCase(); },

    // ── boot ──
    async init() {
        this.bindDock();
        this.bindPager();
        document.getElementById('sq-slideover-backdrop')?.addEventListener('click', () => this.closeSlideover());
        await this.refresh();
        this.loadPrefs();
        setInterval(() => this.refresh(), 5 * 60 * 1000);
    },

    async refresh() {
        const res = await this.get('boards/');
        if (!this.ok(res)) return;
        this.boards = res.data;
        this.flags = res.flags || {};
        if (this.flags.squads === false) {
            document.getElementById('squads-tab')?.setAttribute('hidden', '');
            return;
        }
        this.renderDock();
        this.renderPager();
        this.renderPulse();
        if (document.getElementById('pane-squads')?.style.display === 'block') this.renderPage();
    },

    route(hash) {
        const parts = hash.split('/');            // squad/<id>[/<tab>|/join]
        const id = parseInt(parts[1], 10);
        if (!id) return switchPane('squads');
        this.open(id, parts[2] || 'today');
    },

    // ── right dock (desktop) ──
    tileHtml(b, compact) {
        const isChallenge = b.type === 'challenge';
        const badge = isChallenge ? `${b.day || 0}/${b.days || ''}` : (b.streak ? `🔥${b.streak}` : '');
        const dot = b.at_risk && b.pending_me ? '<span class="tile-dot" title="At risk and you are pending"></span>' : '';
        const title = `${b.name}${isChallenge ? ` · day ${b.day}/${b.days}` : b.streak ? ` · ${b.streak}-day streak` : ''}`;
        const click = isChallenge ? `window.location.href='/c/${b.slug}/'` : `Squads.openSlideover(${b.id})`;
        return `<button class="squad-tile ${isChallenge ? 'challenge' : ''}" data-alert="${b.at_risk && b.pending_me ? 1 : 0}"
                    onclick="${click}" title="${this.esc(title)}">${this.esc(b.emoji || '✨')}${dot}${badge && !compact ? `<span class="tile-badge">${this.esc(badge)}</span>` : ''}</button>`;
    },

    renderDock() {
        const el = document.getElementById('squad-dock-scroll');
        if (!el) return;
        el.innerHTML = this.boards.map(b => this.tileHtml(b)).join('');
        this.updateDockFades();
    },

    bindDock() {
        document.getElementById('squad-dock-scroll')?.addEventListener('scroll', () => this.updateDockFades(), { passive: true });
        window.addEventListener('resize', () => this.updateDockFades());
    },

    /** Fades only on the side where tiles are hidden; a red dot there if a hidden squad is alerting. */
    updateDockFades() {
        const list = document.getElementById('squad-dock-list');
        const sc = document.getElementById('squad-dock-scroll');
        if (!list || !sc) return;
        const top = sc.scrollTop > 2;
        const bottom = sc.scrollTop + sc.clientHeight < sc.scrollHeight - 2;
        list.classList.toggle('fade-top', top);
        list.classList.toggle('fade-bottom', bottom);
        let hiddenTop = false, hiddenBottom = false;
        const box = sc.getBoundingClientRect();
        sc.querySelectorAll('.squad-tile[data-alert="1"]').forEach(t => {
            const r = t.getBoundingClientRect();
            if (r.bottom <= box.top + 8) hiddenTop = true;
            if (r.top >= box.bottom - 8) hiddenBottom = true;
        });
        list.querySelector('.dock-edge-dot.top')?.classList.toggle('on', hiddenTop);
        list.querySelector('.dock-edge-dot.bottom')?.classList.toggle('on', hiddenBottom);
    },

    // ── mobile pager: Squads | Bookmarks ──
    PAGE_MAX: 9,   // 5 x 2 grid; the 10th cell is the +N / + tile

    renderPager() {
        const el = document.getElementById('dock-page-squads');
        if (!el) return;
        const shown = this.boards.slice(0, this.PAGE_MAX);
        const extra = this.boards.length - shown.length;
        el.innerHTML = shown.map(b => this.tileHtml(b, false)).join('')
            + (extra > 0 ? `<button class="squad-tile add" onclick="switchPane('squads')">+${extra}</button>`
                         : `<button class="squad-tile add" onclick="Squads.openCreate()" title="New squad"><i class="fas fa-plus"></i></button>`);
        const alerting = this.boards.some(b => b.at_risk && b.pending_me);
        const pages = document.getElementById('dock-pages');
        if (!this._pagerPlaced && pages) {
            this._pagerPlaced = true;
            let last = 0;
            try { last = parseInt(localStorage.getItem('mr_dock_page') || '0', 10); } catch (e) {}
            this.goPage(alerting ? 0 : last, true);
            try {
                if (!localStorage.getItem('mr_dock_peeked')) {
                    pages.classList.add('peek');
                    localStorage.setItem('mr_dock_peeked', '1');
                }
            } catch (e) {}
        }
        this._alerting = alerting;
        this.syncPagerLabels();
    },

    bindPager() {
        const pages = document.getElementById('dock-pages');
        if (!pages) return;
        document.querySelectorAll('.dock-pager-labels button').forEach(b =>
            b.addEventListener('click', () => this.goPage(parseInt(b.dataset.page, 10))));
        pages.addEventListener('scroll', () => {
            clearTimeout(this._pagerT);
            this._pagerT = setTimeout(() => {
                const page = Math.round(pages.scrollLeft / Math.max(1, pages.clientWidth));
                try { localStorage.setItem('mr_dock_page', String(page)); } catch (e) {}
                this.syncPagerLabels();
            }, 80);
        }, { passive: true });
        // Bookmarks page: 5 x 2 grid with a +N tile, no horizontal scroll inside a page
        const bm = document.getElementById('dock-page-bookmarks');
        if (bm) new MutationObserver(() => this.trimBookmarks(bm)).observe(bm, { childList: true });
    },

    trimBookmarks(bm) {
        if (this._trimming) return;
        this._trimming = true;
        const tiles = [...bm.querySelectorAll('.reading-list-item')];
        if (tiles.length > this.PAGE_MAX) {
            tiles.slice(this.PAGE_MAX).forEach(t => t.remove());
            bm.querySelector('.reading-list-add-btn')?.remove();
            const more = document.createElement('button');
            more.className = 'reading-list-add-btn';
            more.textContent = `+${tiles.length - this.PAGE_MAX}`;
            more.onclick = () => switchPane('reading-list');
            bm.appendChild(more);
        }
        this._trimming = false;
    },

    goPage(n, instant) {
        const pages = document.getElementById('dock-pages');
        if (!pages) return;
        pages.scrollTo({ left: n * pages.clientWidth, behavior: instant ? 'auto' : 'smooth' });
        setTimeout(() => this.syncPagerLabels(), instant ? 0 : 350);
    },

    syncPagerLabels() {
        const pages = document.getElementById('dock-pages');
        if (!pages) return;
        const page = Math.round(pages.scrollLeft / Math.max(1, pages.clientWidth));
        document.querySelectorAll('.dock-pager-labels button').forEach(b =>
            b.classList.toggle('on', parseInt(b.dataset.page, 10) === page));
        const dot = document.querySelector('.dock-pager-labels button[data-page="0"] .label-dot');
        if (dot) dot.hidden = !(this._alerting && page === 1);
    },

    // ── slide-over (dock click) ──
    async openSlideover(id) {
        const panel = document.getElementById('sq-slideover');
        const b = this.boards.find(x => x.id === id) || { name: '', emoji: '' };
        panel.innerHTML = `<button class="sq-close" onclick="Squads.closeSlideover()" aria-label="Close"><i class="fas fa-times"></i></button>
            <h3>${this.esc(b.emoji)} ${this.esc(b.name)}</h3><div class="sq-empty">Loading…</div>`;
        panel.classList.add('open');
        document.getElementById('sq-slideover-backdrop').classList.add('open');
        const res = await this.get(`boards/${id}/today/`);
        if (!this.ok(res)) { panel.querySelector('.sq-empty').textContent = res.error || 'Could not load'; return; }
        const t = res.data;
        panel.innerHTML = `<button class="sq-close" onclick="Squads.closeSlideover()" aria-label="Close"><i class="fas fa-times"></i></button>
            <h3>${this.esc(b.emoji)} ${this.esc(b.name)}</h3>
            <p class="small text-brown mb-2">${t.started ? `${t.in}/${t.counted} in today · needs ${t.threshold}%` : this.esc(t.invite_prompt)}</p>
            ${this.membersToday(id, t)}
            ${t.goal ? this.goalHtml(t.goal) : ''}
            ${t.next_focus ? `<div class="mt-3 small"><i class="fas fa-stopwatch me-1"></i>Next focus: <strong>${this.esc(this.when(t.next_focus.start_at))}</strong>
                · ${t.next_focus.blocks} × ${t.next_focus.block_minutes} min <a href="${t.next_focus.room_url}">Room →</a></div>` : ''}
            <div class="mt-4"><button class="btn btn-paper btn-primary w-100" onclick="Squads.closeSlideover(); Squads.open(${id})">Open squad →</button></div>`;
    },

    closeSlideover() {
        document.getElementById('sq-slideover')?.classList.remove('open');
        document.getElementById('sq-slideover-backdrop')?.classList.remove('open');
    },

    membersToday(boardId, t) {
        const label = { in: 'in', out: 'pending', away: 'away', off: 'off day', first_day: 'first day', none: '—' };
        return `<ul class="sq-list">${t.members.map(m => `
            <li class="sq-member-row">
                <span class="sq-ring ${m.state}">${this.esc(m.initials)}</span>
                <span class="grow">${this.esc(m.name)}${m.pending && m.pending.length ? `<br><small>hasn't done ${this.esc(m.pending.join(', '))}</small>` : ''}</span>
                <span class="state ${m.state}">${label[m.state] || ''}</span>
                ${m.state === 'out' && t.can_nudge && !m.nudged && m.user_id !== AppConfig.userDetail?.user ? `<button class="btn btn-paper btn-sm" onclick="Squads.nudge(${boardId}, ${m.user_id}, this)">Nudge</button>` : ''}
                ${m.nudged ? '<small>nudged</small>' : ''}
            </li>`).join('')}</ul>`;
    },

    async nudge(boardId, userId, btn) {
        btn.disabled = true;
        const res = await this.send('POST', `boards/${boardId}/nudge/`, { user_id: userId });
        if (this.ok(res)) { btn.outerHTML = '<small>nudged</small>'; } else { btn.disabled = false; this.fail(res); }
    },

    // ── Today: at-risk alerts and nudge rows ──
    async renderPulse() {
        const el = document.getElementById('sq-pulse');
        if (!el) return;
        const squads = this.boards.filter(b => b.type === 'squad' && b.started);
        const atRisk = squads.filter(b => b.at_risk && b.pending_me);
        const canNudge = squads.filter(b => b.my_state === 'in' && b.counted_today > b.in_today);
        let html = atRisk.map(b => `
            <div class="sq-pulse-card anomaly-card">
                <div class="head"><span>${this.esc(b.emoji)}</span><span class="grow">${this.esc(b.name)} streak at risk</span>
                    <span class="small">${b.in_today}/${b.counted_today} in · needs ${b.threshold}%</span></div>
                <div class="small mt-1">Your check-in could save ${b.streak ? `the ${b.streak}-day streak` : 'today'}.
                    <a href="#squad/${b.id}" class="ms-1">Open →</a></div>
            </div>`).join('');
        const panels = await Promise.all(canNudge.slice(0, 3).map(b => this.get(`boards/${b.id}/today/`).then(r => [b, r])));
        panels.forEach(([b, res]) => {
            if (!this.ok(res)) return;
            res.data.members.filter(m => m.state === 'out' && !m.nudged).forEach(m => {
                const what = (m.pending || [])[0] || 'their check-in';
                html += `<div class="sq-pulse-row accountability-row">
                    <span class="sq-ring out">${this.esc(m.initials)}</span>
                    <span class="grow">${this.esc(m.name)} hasn't done <em>${this.esc(what)}</em> · ${res.data.in}/${res.data.counted} in
                        <small class="text-brown">${this.esc(b.emoji)} ${this.esc(b.name)}</small></span>
                    <button class="btn btn-paper btn-sm" onclick="Squads.nudge(${b.id}, ${m.user_id}, this)">Nudge</button>
                    <button class="btn btn-paper btn-sm" onclick="Squads.openSlideover(${b.id})">Check</button>
                </div>`;
            });
        });
        el.innerHTML = html;
    },

    // ── Squads page ──
    loadPage() { this.renderPage(); this.refresh(); },

    renderPage() {
        const grid = document.getElementById('squads-grid');
        if (!grid) return;
        const squads = this.boards.filter(b => b.type === 'squad');
        grid.innerHTML = squads.map(b => `
            <div class="sq-tile-card" onclick="Squads.open(${b.id})">
                ${b.at_risk && b.pending_me ? '<span class="risk">AT RISK</span>' : ''}
                <div class="emoji">${this.esc(b.emoji || '✨')}</div>
                <div class="name">${this.esc(b.name)}</div>
                <div class="meta">${b.members} member${b.members === 1 ? '' : 's'}${b.started ? ` · 🔥 ${b.streak} · ${b.in_today}/${b.counted_today} in today` : ' · invite 1 friend to start'}${b.status !== 'active' ? ` · ${b.status.replace('_', '-')}` : ''}</div>
            </div>`).join('') + `<div class="sq-tile-card new" onclick="Squads.openCreate()"><i class="fas fa-plus"></i> New squad</div>`;
        const ch = document.getElementById('challenges-grid');
        const challenges = this.boards.filter(b => b.type === 'challenge');
        if (ch) ch.innerHTML = challenges.map(c => `
            <a class="sq-tile-card text-decoration-none" href="/c/${c.slug}/" style="color:inherit">
                <div class="emoji">${this.esc(c.emoji)}</div><div class="name">${this.esc(c.name)}</div>
                <div class="meta">Day ${c.day}/${c.days} · ${this.esc(c.status)}</div></a>`).join('')
            || '<p class="text-brown small">No challenges yet. Start one or find one in Discover.</p>';
        const notices = document.getElementById('squads-notices');
        if (notices) notices.innerHTML = squads.filter(b => b.needs_ack).map(b => `
            <div class="sq-notice"><span class="grow">${this.esc(b.added_by || 'Someone')} added you to <strong>${this.esc(b.emoji)} ${this.esc(b.name)}</strong></span>
                <button class="btn btn-paper btn-sm btn-primary" onclick="Squads.ack(${b.id}, true)">Stay</button>
                <button class="btn btn-paper btn-sm" onclick="Squads.ack(${b.id}, false)">Leave</button></div>`).join('');
    },

    async ack(id, stay) {
        const res = await this.send('POST', `boards/${id}/ack/`, { stay });
        if (!this.ok(res)) return this.fail(res);
        await this.refresh();
        if (!stay && this.current?.id === id) switchPane('squads');
        else if (this.current?.id === id) this.open(id, this.tab);
    },

    async toggleDiscover() {
        const box = document.getElementById('discover-box');
        if (!box) return;
        if (!box.hidden) { box.hidden = true; return; }
        box.hidden = false;
        box.innerHTML = '<div class="sq-empty">Loading…</div>';
        const res = await this.get('challenges/discover/');
        if (!this.ok(res)) { box.innerHTML = `<div class="sq-empty">${this.esc(res.error)}</div>`; return; }
        const row = c => `<a class="sq-row" href="${c.url}"><span class="sq-row-emoji">${this.esc(c.emoji)}</span>
            <span class="sq-row-main"><strong>${this.esc(c.title)}</strong><small>${c.days} days · starts ${c.start_date} · ${c.participant_count} joined</small></span>
            <i class="fas fa-chevron-right"></i></a>`;
        box.innerHTML = `<div class="row"><div class="col-md-6"><h3 class="section-title-sm">Starting soon</h3>${res.data.starting_soon.map(row).join('') || '<p class="small text-brown">Nothing yet</p>'}</div>
            <div class="col-md-6"><h3 class="section-title-sm">Most joined</h3>${res.data.most_joined.map(row).join('') || '<p class="small text-brown">Nothing yet</p>'}</div></div>`;
    },

    // ── modal helper ──
    modal(id, title, body, saveLabel, onSave) {
        document.getElementById(id)?.remove();
        const wrap = document.createElement('div');
        wrap.innerHTML = `<div class="modal fade" id="${id}" tabindex="-1"><div class="modal-dialog modal-dialog-centered modal-lg"><div class="modal-content">
            <div class="modal-header"><h5 class="modal-title">${title}</h5><button type="button" class="btn-close" data-bs-dismiss="modal"></button></div>
            <div class="modal-body">${body}</div>
            <div class="modal-footer"><button class="btn btn-paper" data-bs-dismiss="modal">Cancel</button>
                <button class="btn btn-paper btn-primary" id="${id}-save">${saveLabel}</button></div></div></div></div>`;
        document.body.appendChild(wrap.firstElementChild);
        const el = document.getElementById(id);
        const m = new bootstrap.Modal(el);
        document.getElementById(`${id}-save`).addEventListener('click', async () => {
            const btn = document.getElementById(`${id}-save`);
            btn.disabled = true;
            try { if (await onSave(el)) m.hide(); } finally { btn.disabled = false; }
        });
        el.addEventListener('hidden.bs.modal', () => el.remove());
        m.show();
        return el;
    },

    // ── create a squad (B1) ──
    openCreate() {
        const body = `
            <div class="sq-sentence">I'm starting a squad called
                <input class="form-control" id="sqc-name" placeholder="DSA grind" maxlength="80">
                <input class="form-control" id="sqc-emoji" placeholder="📚" maxlength="4" style="min-width:60px;width:60px">
                for <select class="form-select" id="sqc-template">
                    <option value="study">studying</option><option value="fitness">fitness</option>
                    <option value="family">family</option><option value="custom">something else</option></select>.</div>
            <div class="mt-3" id="sqc-items"></div>`;
        const el = this.modal('sq-create-modal', 'New squad', body, 'Create squad', () => this.saveCreate());
        el.querySelector('#sqc-template').addEventListener('change', e => this.loadTemplate(e.target.value));
        this.loadTemplate('study');
        setTimeout(() => el.querySelector('#sqc-name')?.focus(), 300);
    },

    async loadTemplate(name) {
        const res = await this.get(`templates/${name}/`);
        const box = document.getElementById('sqc-items');
        if (!this.ok(res) || !box) return;
        const t = res.data;
        const emoji = document.getElementById('sqc-emoji');
        if (emoji && (!emoji.value || emoji.dataset.auto)) { emoji.value = t.emoji; emoji.dataset.auto = '1'; }
        const habitRow = (h, i) => `<label><input type="checkbox" class="form-check-input sqc-h-on" checked>
            <input class="form-control form-control-sm sqc-h-name" value="${this.esc(h.habit)}">
            <select class="form-select form-select-sm sqc-h-core" style="width:auto"><option value="1" ${h.is_core ? 'selected' : ''}>core</option><option value="0" ${h.is_core ? '' : 'selected'}>optional</option></select></label>`;
        box.innerHTML = `<div class="sq-label mb-1">Suggested habits (edit or untick)</div>
            <div class="sq-tpl-items" id="sqc-habits">${t.habits.map(habitRow).join('')}</div>
            <button class="btn btn-link btn-sm p-0" type="button" onclick="Squads.addTemplateHabit()">+ add a habit</button>
            ${t.tracker ? `<div class="sq-label mt-3 mb-1">Shared goal</div>
            <label class="sq-sentence"><input type="checkbox" class="form-check-input" id="sqc-t-on" checked>
                Together we'll hit <input class="form-control form-control-sm" id="sqc-t-goal" type="number" value="${t.tracker.goal}" style="width:100px">
                <input class="form-control form-control-sm" id="sqc-t-unit" value="${this.esc(t.tracker.unit)}" style="width:110px">
                tracked as <input class="form-control form-control-sm" id="sqc-t-name" value="${this.esc(t.tracker.name)}"></label>` : ''}
            ${t.focus ? `<div class="sq-label mt-3 mb-1">Weekly focus session</div>
            <label class="sq-sentence"><input type="checkbox" class="form-check-input" id="sqc-f-on" checked>
                Let's focus on <select class="form-select form-select-sm" id="sqc-f-day">${['Mon','Tue','Wed','Thu','Fri','Sat','Sun'].map((d, i) => `<option value="${i}" ${i === t.focus.weekday ? 'selected' : ''}>${d}</option>`).join('')}</select>
                at <input class="form-control form-control-sm" type="time" id="sqc-f-time" value="${String(t.focus.hour).padStart(2, '0')}:00" style="width:110px">
                for <input class="form-control form-control-sm" type="number" id="sqc-f-blocks" value="${t.focus.blocks}" style="width:70px"> ×
                <input class="form-control form-control-sm" type="number" id="sqc-f-min" value="${t.focus.block_minutes}" style="width:80px"> min</label>` : ''}`;
    },

    addTemplateHabit() {
        const box = document.getElementById('sqc-habits');
        box.insertAdjacentHTML('beforeend', `<label><input type="checkbox" class="form-check-input sqc-h-on" checked>
            <input class="form-control form-control-sm sqc-h-name" placeholder="New habit">
            <select class="form-select form-select-sm sqc-h-core" style="width:auto"><option value="1">core</option><option value="0" selected>optional</option></select></label>`);
    },

    nextWeekday(weekday, time) {
        const d = new Date();
        const today = (d.getDay() + 6) % 7;
        let add = (weekday - today + 7) % 7 || 7;
        d.setDate(d.getDate() + add);
        const [h, m] = time.split(':').map(Number);
        d.setHours(h, m || 0, 0, 0);
        return d.toISOString();
    },

    async saveCreate() {
        const name = document.getElementById('sqc-name').value.trim();
        if (!name) { showError('Give your squad a name'); return false; }
        const habits = [...document.querySelectorAll('#sqc-habits label')].filter(l => l.querySelector('.sqc-h-on').checked)
            .map(l => ({ habit: l.querySelector('.sqc-h-name').value.trim(), is_core: l.querySelector('.sqc-h-core').value === '1' }))
            .filter(h => h.habit);
        const body = { name, emoji: document.getElementById('sqc-emoji').value.trim(), template: document.getElementById('sqc-template').value,
                       habits, timezone: this.tz() };
        if (document.getElementById('sqc-t-on')?.checked) body.tracker = {
            name: document.getElementById('sqc-t-name').value.trim(), unit: document.getElementById('sqc-t-unit').value.trim(),
            goal: parseFloat(document.getElementById('sqc-t-goal').value) || null };
        if (document.getElementById('sqc-f-on')?.checked) body.focus = {
            start_at: this.nextWeekday(parseInt(document.getElementById('sqc-f-day').value, 10), document.getElementById('sqc-f-time').value || '07:00'),
            blocks: parseInt(document.getElementById('sqc-f-blocks').value, 10) || 1,
            block_minutes: parseInt(document.getElementById('sqc-f-min').value, 10) || 50 };
        const res = await this.send('POST', 'boards/', body);
        if (!this.ok(res)) { this.fail(res); return false; }
        await this.refresh();
        this.open(res.data.id, 'settings');
        return true;
    },

    // ── squad page ──
    async open(id, tab) {
        if (currentPane !== 'squad') switchPane('squad');
        this.tab = this.TABS.includes(tab) ? tab : 'today';
        const joining = tab === 'join';
        history.replaceState(null, '', `#squad/${id}/${this.tab}`);
        const page = document.getElementById('squad-page');
        if (!this.current || this.current.id !== id) page.innerHTML = '<div class="sq-empty">Loading…</div>';
        const res = await this.get(`boards/${id}/`);
        if (!this.ok(res)) { page.innerHTML = `<div class="sq-empty">${this.esc(res.error || 'Squad not found')}</div>`; return; }
        this.current = res.data;
        this.renderSquad(joining);
    },

    isAdmin() { return ['owner', 'admin'].includes(this.current?.role); },

    renderSquad(joining) {
        const b = this.current;
        const page = document.getElementById('squad-page');
        const rings = b.member_list.map(m => {
            return `<span class="sq-ring" data-ring="${m.user_id}" title="${this.esc(m.name)}">${this.esc(m.initials)}</span>`;
        }).join('');
        page.innerHTML = `
            ${b.needs_ack ? `<div class="sq-notice"><span class="grow">${this.esc(b.added_by || 'Someone')} added you to <strong>${this.esc(b.name)}</strong></span>
                <button class="btn btn-paper btn-sm btn-primary" onclick="Squads.ack(${b.id}, true)">Stay</button>
                <button class="btn btn-paper btn-sm" onclick="Squads.ack(${b.id}, false)">Leave</button></div>` : ''}
            ${b.status !== 'active' ? `<div class="sq-notice"><span class="grow">This squad is ${b.status === 'archived' ? 'archived' : 'read-only on the current plan'}: you can look, not log.</span></div>` : ''}
            <div class="sq-header">
                <span class="emoji">${this.esc(b.emoji || '✨')}</span>
                <div><h2>${this.esc(b.name)}</h2>
                    <div class="stats"><span>🔥 <strong>${b.streak}</strong> day streak</span><span>best <strong>${b.best_streak}</strong></span>
                        <span><strong>${b.members}</strong> member${b.members === 1 ? '' : 's'}</span><span id="sq-team-score"></span></div></div>
                <span class="spacer"></span>
                <button class="btn btn-paper btn-primary" onclick="Squads.share()"><i class="fa-brands fa-whatsapp me-1"></i>Invite</button>
            </div>
            <div class="sq-rings" id="sq-rings">${rings}</div>
            <div class="sq-tabs">${this.TABS.map(t => `<button class="${t === this.tab ? 'on' : ''}" onclick="Squads.switchTab('${t}')">${this.TAB_LABELS[t]}</button>`).join('')}</div>
            <div id="sq-tab-body"></div>`;
        this.loadTab(joining);
        this.get(`boards/${b.id}/leaderboard/`).then(r => {
            if (this.ok(r)) { const s = document.getElementById('sq-team-score'); if (s) s.innerHTML = `team <strong>${r.data.team_score}</strong> this week`; }
        });
    },

    switchTab(t) {
        this.tab = t;
        history.replaceState(null, '', `#squad/${this.current.id}/${t}`);
        document.querySelectorAll('.sq-tabs button').forEach(b => b.classList.toggle('on', b.textContent === this.TAB_LABELS[t]));
        this.loadTab();
    },

    body() { return document.getElementById('sq-tab-body'); },

    async loadTab(joining) {
        const fn = { today: 'tabToday', goals: 'tabGoals', leaderboard: 'tabLeaderboard', focus: 'tabFocus',
                     challenges: 'tabChallenges', feed: 'tabFeed', heatmap: 'tabHeatmap', settings: 'tabSettings' }[this.tab];
        this.body().innerHTML = '<div class="sq-empty">Loading…</div>';
        try { await this[fn](joining); } catch (e) { this.body().innerHTML = `<div class="sq-empty">${this.esc(e.message)}</div>`; }
    },

    // Today tab
    async tabToday(joining) {
        const b = this.current;
        const [today, overlaps] = await Promise.all([this.get(`boards/${b.id}/today/`), this.get(`boards/${b.id}/overlaps/`)]);
        const t = today.data;
        if (this.ok(today)) t.members.forEach(m => document.querySelector(`[data-ring="${m.user_id}"]`)?.classList.add(m.state));
        let html = '';
        if (this.ok(overlaps) && overlaps.data.length) {
            html += `<div class="sq-card mb-3"><div class="sq-label mb-2">You already track something similar</div>
                ${overlaps.data.map(o => `<div class="sq-inline-form"><span class="grow">Squad: <strong>${this.esc(o.squad_name)}</strong> · yours: <strong>${this.esc(o.personal_name)}</strong></span>
                    <button class="btn btn-paper btn-sm btn-primary" onclick="Squads.resolve('${o.type}', ${o.squad_item}, ${o.personal_item}, 'link')" title="One log counts for both">Link</button>
                    <button class="btn btn-paper btn-sm" onclick="Squads.resolve('${o.type}', ${o.squad_item}, ${o.personal_item}, 'adopt')" title="Your item takes the squad's setup">Adopt squad's</button>
                    <button class="btn btn-paper btn-sm" onclick="Squads.resolve('${o.type}', ${o.squad_item}, ${o.personal_item}, 'separate')">Keep separate</button></div>`).join('')}</div>`;
        }
        if (this.ok(today) && !t.started) {
            html += `<div class="sq-invite-cta mb-3"><div class="sq-join-emoji">👋</div><p class="mb-2"><strong>${this.esc(t.invite_prompt)}</strong></p>
                <p class="small text-brown">Streak, leaderboard and heatmap start once there are 2 of you.</p>
                <button class="btn btn-paper btn-primary" onclick="Squads.share()"><i class="fa-brands fa-whatsapp me-1"></i>Share invite link</button></div>`;
        }
        if (this.ok(today)) {
            html += `<h3 class="section-title-sm">Who's in today ${t.started ? `<small class="text-brown">· ${t.in}/${t.counted} · needs ${t.threshold}%</small>` : ''}</h3>${this.membersToday(b.id, t)}`;
        }
        const mine = b.habits.filter(h => h.assigned_to_me);
        html += `<h3 class="section-title-sm mt-4">Habits <small class="text-brown">· log them in your Today; one log counts everywhere</small></h3>
            <ul class="sq-list">${b.habits.map(h => `<li>
                <span class="grow"><strong>${this.esc(h.habit)}</strong> ${h.is_core ? '<span class="sq-chip">core</span>' : '<span class="sq-chip sq-chip-quiet">optional</span>'}
                    ${h.pending_rule ? `<small> · becomes ${h.pending_rule.is_core ? 'core' : 'optional'} from ${this.esc(h.pending_rule.from)}</small>` : ''}
                    ${h.steps.length ? `<br><small>${h.steps.map(s => this.esc(s.name + (s.target ? ' ' + s.target : ''))).join(' · ')}</small>` : ''}
                    ${!h.assigned_to_me ? '<br><small>not assigned to you</small>' : ''}</span>
                ${h.my_copy ? `<small>${h.my_reminder ? `remind ${this.esc(h.my_reminder.slice(0, 5))}` : 'in your Today'}</small>
                    <button class="btn btn-paper btn-sm" onclick="Squads.myTiming(${h.id})" title="Your own reminder time and slot">My timing</button>` : ''}
                ${!h.is_core && h.assigned_to_me ? (h.opted_out ? `<button class="btn btn-paper btn-sm" onclick="Squads.opt(${h.id}, true)">Opt in</button>`
                    : `<button class="btn btn-paper btn-sm" onclick="Squads.opt(${h.id}, false)">Opt out</button>`) : ''}
                ${this.isAdmin() ? `<button class="btn btn-paper btn-sm" onclick="Squads.toggleCore(${h.id}, ${!h.is_core})" title="Applies from tomorrow">${h.is_core ? 'Make optional' : 'Make core'}</button>` : ''}
            </li>`).join('') || '<li class="text-brown small">No habits yet.</li>'}</ul>
            ${this.isAdmin() ? `<div class="sq-inline-form sq-sentence">We all
                <input class="form-control form-control-sm" id="sq-new-habit" placeholder="solve 2 problems">
                every day, and it <select class="form-select form-select-sm" id="sq-new-habit-core"><option value="1">decides the streak</option><option value="0">is optional</option></select>.
                <button class="btn btn-paper btn-sm btn-primary" onclick="Squads.addHabit()">Add</button></div>` : ''}`;
        html += `<h3 class="section-title-sm mt-4">Todos</h3>
            <ul class="sq-list">${b.todos.map(td => `<li>
                <input type="checkbox" class="form-check-input" ${td.is_done ? 'checked' : ''} ${td.completion_mode === 'assigned' && td.assignee !== AppConfig.userDetail?.user ? 'disabled title="Only the assignee can close this"' : ''}
                    onchange="Squads.closeTodo(${td.id}, this.checked, this)">
                <span class="grow ${td.is_done ? 'text-decoration-line-through' : ''}">${this.esc(td.task_name)}
                    <br><small>${td.completion_mode === 'assigned' ? `assigned to ${this.esc(td.assignee_name)}` : 'anyone can close it'}${td.completed_by ? ` · done by ${this.esc(td.completed_by)}` : ''}${td.deadline ? ` · due ${this.esc(this.when(td.deadline))}` : ''}</small></span>
            </li>`).join('') || '<li class="text-brown small">No squad todos.</li>'}</ul>
            <div class="sq-inline-form sq-sentence">Someone needs to
                <input class="form-control form-control-sm" id="sq-new-todo" placeholder="book the court">
                and <select class="form-select form-select-sm" id="sq-new-todo-who"><option value="">anyone can close it</option>
                    ${b.member_list.map(m => `<option value="${m.user_id}">${this.esc(m.name)} closes it</option>`).join('')}</select>
                <button class="btn btn-paper btn-sm btn-primary" onclick="Squads.addTodo()">Add</button></div>`;
        if (b.trackers.length) {
            html += `<h3 class="section-title-sm mt-4">Trackers</h3><ul class="sq-list">${b.trackers.map(m => `<li><span class="grow">${this.esc(m.name)} <small>${this.esc(m.unit)}</small></span>
                <small>${m.my_copy ? 'logs from your tracker count' : 'not linked'}</small></li>`).join('')}</ul>`;
        }
        if (this.isAdmin()) html += `<div class="sq-inline-form sq-sentence mt-2">Track
            <input class="form-control form-control-sm" id="sq-new-tracker" placeholder="problems solved"> in
            <input class="form-control form-control-sm" id="sq-new-tracker-unit" placeholder="problems" style="width:110px">
            <button class="btn btn-paper btn-sm" onclick="Squads.addTracker()">Add tracker</button></div>`;
        this.body().innerHTML = html;
        if (joining) window.scrollTo({ top: 0 });
    },

    async resolve(type, squadItem, personalItem, choice) {
        const res = await this.send('POST', `boards/${this.current.id}/overlaps/`, { type, squad_item: squadItem, personal_item: personalItem, choice });
        if (!this.ok(res)) return this.fail(res);
        this.open(this.current.id, 'today');
    },

    /** Each member sets their own reminder time on their linked copy. */
    myTiming(squadHabitId) {
        const h = this.current.habits.find(x => x.id === squadHabitId);
        if (!h || !h.my_copy) return;
        if (typeof showHabitSettings === 'function') showHabitSettings(String(h.my_copy), h.habit, h.detail || '', h.habit, h.my_reminder);
        else switchPane('trackers');
    },

    async opt(habitId, optIn) {
        const res = await this.send('POST', `boards/${this.current.id}/opt/`, { habit: habitId, opt_in: optIn });
        if (!this.ok(res)) return this.fail(res);
        this.open(this.current.id, 'today');
    },

    async toggleCore(habitId, isCore) {
        const res = await this.send('PATCH', `boards/${this.current.id}/habits/${habitId}/`, { is_core: isCore });
        if (!this.ok(res)) return this.fail(res);
        showSuccess('This applies from tomorrow. Nothing already logged is recomputed.', 'Scheduled');
        this.open(this.current.id, 'today');
    },

    async addHabit() {
        const habit = document.getElementById('sq-new-habit').value.trim();
        if (!habit) return;
        const res = await this.send('POST', `boards/${this.current.id}/habits/`, { habit, is_core: document.getElementById('sq-new-habit-core').value === '1' });
        if (!this.ok(res)) return this.fail(res);
        this.open(this.current.id, 'today');
    },

    async addTracker() {
        const name = document.getElementById('sq-new-tracker').value.trim();
        if (!name) return;
        const res = await this.send('POST', `boards/${this.current.id}/trackers/`, { name, unit: document.getElementById('sq-new-tracker-unit').value.trim() });
        if (!this.ok(res)) return this.fail(res);
        this.open(this.current.id, 'today');
    },

    async addTodo() {
        const task_name = document.getElementById('sq-new-todo').value.trim();
        if (!task_name) return;
        const who = document.getElementById('sq-new-todo-who').value;
        const res = await this.send('POST', `boards/${this.current.id}/todos/`, who
            ? { task_name, completion_mode: 'assigned', assignee: parseInt(who, 10) } : { task_name });
        if (!this.ok(res)) return this.fail(res);
        this.open(this.current.id, 'today');
    },

    async closeTodo(id, done, box) {
        const res = await apiClient.put(`board/api/tasks/${id}/`, { is_done: done }, { silent: true });
        if (!res || res.status === 'failed') { box.checked = !done; return this.fail(res); }
        this.open(this.current.id, 'today');
    },

    // Goals tab
    goalHtml(g) {
        return `<div class="sq-goal"><div class="top"><strong>${this.esc(g.title)}</strong><span>${g.total} / ${g.target} ${this.esc(g.unit)}</span></div>
            <div class="sq-bar"><span style="width:${g.pct}%"></span></div>
            <div class="small text-brown mt-1">${g.pct}% · ${g.pace_per_day != null && g.days_left ? `${g.pace_per_day}/day to finish · ${g.days_left} days left` : 'period over'}</div></div>`;
    },

    async tabGoals() {
        const b = this.current;
        const res = await this.get(`boards/${b.id}/goals/`);
        if (!this.ok(res)) throw new Error(res.error);
        let html = res.data.map(g => `${this.goalHtml(g)}
            <ul class="sq-list mb-3">${g.shares.map(s => `<li><span class="grow">${this.esc(s.name)}</span><span>${s.value} <small>· fair share ${s.fair_share}</small></span></li>`).join('')}</ul>
            ${this.isAdmin() ? `<button class="btn btn-link btn-sm p-0 mb-3" onclick="Squads.deleteGoal(${g.id})">Remove goal</button>` : ''}`).join('')
            || '<div class="sq-empty">No goal yet.</div>';
        if (this.isAdmin()) {
            const sources = b.trackers.map(m => `<option value="t:${m.id}">${this.esc(m.unit || m.name)} (${this.esc(m.name)})</option>`)
                .concat(b.habits.map(h => `<option value="h:${h.id}">check-ins of ${this.esc(h.habit)}</option>`)).join('');
            html += sources ? `<div class="sq-inline-form sq-sentence mt-3">Together we'll hit
                <input class="form-control form-control-sm" type="number" id="sq-goal-target" placeholder="500" style="width:100px">
                <select class="form-select form-select-sm" id="sq-goal-source">${sources}</select> by
                <input class="form-control form-control-sm" type="date" id="sq-goal-end" style="width:160px">.
                <button class="btn btn-paper btn-sm btn-primary" onclick="Squads.addGoal()">Set goal</button></div>
                <p class="small text-brown">The unit is locked once the goal is set. Late joiners' shares are pro-rated from when they joined.</p>`
                : '<p class="small text-brown">Add a squad tracker on the Today tab first.</p>';
        }
        this.body().innerHTML = html;
    },

    async addGoal() {
        const [kind, id] = document.getElementById('sq-goal-source').value.split(':');
        const body = { target: document.getElementById('sq-goal-target').value, period_end: document.getElementById('sq-goal-end').value || null };
        body[kind === 't' ? 'tracker' : 'habit'] = parseInt(id, 10);
        if (kind === 'h') body.aggregation = 'count';
        const res = await this.send('POST', `boards/${this.current.id}/goals/`, body);
        if (!this.ok(res)) return this.fail(res);
        this.tabGoals();
    },

    async deleteGoal(id) {
        const res = await this.send('DELETE', `boards/${this.current.id}/goals/${id}/`);
        if (!this.ok(res)) return this.fail(res);
        this.tabGoals();
    },

    // Leaderboard tab (cooperative: team score prominent, no last place)
    async tabLeaderboard(week) {
        const b = this.current;
        const res = await this.get(`boards/${b.id}/leaderboard/${week ? `?week=${week}` : ''}`);
        if (!this.ok(res)) throw new Error(res.error);
        const d = res.data;
        const prev = new Date(d.week_start); prev.setDate(prev.getDate() - 7);
        const next = new Date(d.week_start); next.setDate(next.getDate() + 7);
        this.body().innerHTML = d.hidden ? '<div class="sq-empty">History beyond your plan\'s window is hidden, not deleted.</div>' : `
            <div class="d-flex align-items-center gap-2 mb-2">
                <button class="btn btn-paper btn-sm" onclick="Squads.tabLeaderboard('${prev.toISOString().slice(0, 10)}')"><i class="fas fa-chevron-left"></i></button>
                <span class="small">Week of ${this.esc(d.week_start)}</span>
                <button class="btn btn-paper btn-sm" onclick="Squads.tabLeaderboard('${next.toISOString().slice(0, 10)}')"><i class="fas fa-chevron-right"></i></button>
                <small class="text-brown ms-auto">Resets ${this.esc(d.resets)}</small></div>
            <div class="text-center my-3"><div class="sq-team-score">${d.team_score}</div><div class="sq-label">team score</div></div>
            <ul class="sq-list sq-lb">${d.rows.map(r => `<li><span class="grow">${this.esc(r.name)}${r.me ? ' <small>(you)</small>' : ''} ${r.mvp ? '<span class="sq-mvp">★ MVP</span>' : ''}</span><span class="pts">${r.points} pts</span></li>`).join('')
                || '<li class="text-brown small">No points yet this week.</li>'}</ul>
            <p class="small text-brown mt-3">10 for your own core check-in, +5 each when the day survives, +5 for the check-in that saves it, 15 for a focus session with 2+ people completing, +3 when your nudge works.</p>
            <button class="btn btn-paper btn-sm mt-2" onclick="Squads.recap('${d.week_start}')"><i class="fas fa-share me-1"></i>Weekly recap card</button>`;
    },

    async recap(week) {
        const res = await this.get(`boards/${this.current.id}/recap/?week=${week}`);
        if (!this.ok(res)) return this.fail(res);
        window.open(res.data.share_url, '_blank', 'noopener');
    },

    // Focus tab
    async tabFocus() {
        const b = this.current;
        const res = await this.get(`boards/${b.id}/focus/`);
        if (!this.ok(res)) throw new Error(res.error);
        const me = AppConfig.userDetail?.user;
        const up = res.data.upcoming.map(s => `<li><span class="grow"><strong>${this.esc(this.when(s.start_at))}</strong> · ${s.blocks} × ${s.block_minutes} min
                <br><small>${this.esc(s.title)} · host ${this.esc(s.host)} · ${s.rsvp.yes} yes · ${s.rsvp.no} no (optional)</small></span>
            <button class="btn btn-paper btn-sm ${s.rsvp.mine === 'yes' ? 'btn-primary' : ''}" onclick="Squads.rsvp(${s.id}, 'yes')">Yes</button>
            <button class="btn btn-paper btn-sm ${s.rsvp.mine === 'no' ? 'btn-primary' : ''}" onclick="Squads.rsvp(${s.id}, 'no')">No</button>
            <a class="btn btn-paper btn-sm" href="${s.room_url}">Room</a>
            ${s.host_id === me || this.isAdmin() ? `<button class="btn btn-paper btn-sm" onclick="Squads.cancelFocus(${s.id})" title="Sends a calendar cancellation"><i class="fas fa-times"></i></button>` : ''}</li>`).join('');
        const past = res.data.past.map(s => `<li><span class="grow"><strong>${this.esc(new Date(s.start_at).toLocaleDateString())}</strong> · ${s.duration_minutes} min
                ${s.quorum_met ? '<span class="sq-chip">points</span>' : '<span class="sq-chip sq-chip-quiet">solo</span>'}
                <br><small>${s.attendance.map(a => `${this.esc(a.name)} ${a.minutes} min${a.completed ? ' ✓' : ''}`).join(' · ') || 'nobody joined'}</small></span></li>`).join('');
        const habits = b.habits.map(h => `<option value="${h.id}">${this.esc(h.habit)}</option>`).join('');
        this.body().innerHTML = `
            <h3 class="section-title-sm">Upcoming</h3><ul class="sq-list">${up || '<li class="text-brown small">Nothing scheduled.</li>'}</ul>
            <div class="sq-inline-form sq-sentence mt-2">Let's focus on <input class="form-control form-control-sm" type="datetime-local" id="sq-f-start" style="width:220px">
                for <input class="form-control form-control-sm" type="number" id="sq-f-blocks" value="2" min="1" max="8" style="width:70px"> ×
                <input class="form-control form-control-sm" type="number" id="sq-f-min" value="50" min="5" max="180" style="width:80px"> min
                ${habits ? `and count it as <select class="form-select form-select-sm" id="sq-f-habit"><option value="">nothing</option>${habits}</select>` : ''}.
                <button class="btn btn-paper btn-sm btn-primary" onclick="Squads.scheduleFocus()">Schedule</button></div>
            <p class="small text-brown">Members with Google Calendar connected get it in their calendar; everyone else gets an email invite. Stay for 80% of the focus time to complete it; points need 2 or more people completing.</p>
            <h3 class="section-title-sm mt-4">Past sessions</h3><ul class="sq-list">${past || '<li class="text-brown small">No sessions yet.</li>'}</ul>`;
    },

    async scheduleFocus() {
        const start = document.getElementById('sq-f-start').value;
        if (!start) return showError('Pick a time');
        const body = { start_at: new Date(start).toISOString(), blocks: parseInt(document.getElementById('sq-f-blocks').value, 10),
                       block_minutes: parseInt(document.getElementById('sq-f-min').value, 10) };
        const habit = document.getElementById('sq-f-habit')?.value;
        if (habit) body.linked_habit = parseInt(habit, 10);
        const res = await this.send('POST', `boards/${this.current.id}/focus/`, body);
        if (!this.ok(res)) return this.fail(res);
        this.tabFocus();
    },

    async rsvp(id, response) {
        const res = await this.send('POST', `focus/${id}/rsvp/`, { response });
        if (!this.ok(res)) return this.fail(res);
        this.tabFocus();
    },

    async cancelFocus(id) {
        if (!confirm('Cancel this session for everyone?')) return;
        const res = await this.send('DELETE', `boards/${this.current.id}/focus/${id}/`);
        if (!this.ok(res)) return this.fail(res);
        this.tabFocus();
    },

    // Challenges tab
    async tabChallenges() {
        const b = this.current;
        const res = await this.get(`challenges/?board=${b.id}`);
        if (!this.ok(res)) throw new Error(res.error);
        this.body().innerHTML = `<ul class="sq-list">${res.data.map(c => `<li><span class="grow"><a href="${c.url}"><strong>${this.esc(c.emoji)} ${this.esc(c.title)}</strong></a>
                <br><small>${this.esc(c.kind)} · ${c.days} days from ${this.esc(c.start_date)} · ${c.participant_count} in${c.me ? ` · you: day ${c.me.day}/${c.me.days}, ${c.me.skips_left} skips left` : ''}</small></span>
                ${!c.me && c.join_open ? `<button class="btn btn-paper btn-sm btn-primary" onclick="Squads.joinChallenge('${c.slug}')">Join</button>` : ''}</li>`).join('')
            || '<li class="text-brown small">No challenges in this squad yet.</li>'}</ul>
            <button class="btn btn-paper btn-sm mt-3" onclick="Squads.openChallenge(${b.id})"><i class="fas fa-flag-checkered me-1"></i>New challenge</button>`;
    },

    async joinChallenge(slug) {
        const res = await this.send('POST', `challenges/${slug}/join/`, { timezone: this.tz() });
        if (!this.ok(res)) return this.fail(res);
        this.refresh();
        if (this.current) this.tabChallenges();
    },

    openChallenge(boardId) {
        const squads = this.boards.filter(b => b.type === 'squad');
        const parent = boardId || this.current?.id || squads[0]?.id;
        const start = new Date(); start.setDate(start.getDate() + 1);
        const body = `<div class="sq-sentence">I challenge
                <select class="form-select" id="chc-vis">${squads.length ? `<option value="squad">my squad</option>` : ''}<option value="link">anyone with the link</option><option value="public">everyone</option></select>
                ${squads.length ? `<select class="form-select" id="chc-parent">${squads.map(s => `<option value="${s.id}" ${s.id === parent ? 'selected' : ''}>${this.esc(s.emoji)} ${this.esc(s.name)}</option>`).join('')}</select>` : ''}
                to <input class="form-control" id="chc-item" placeholder="solve 2 problems">
                <span id="chc-target-wrap" hidden><input class="form-control" type="number" id="chc-target" placeholder="10" style="width:90px">
                    <input class="form-control" id="chc-unit" placeholder="reps" style="width:100px">
                    <span id="chc-step-wrap" hidden>, adding <input class="form-control" type="number" id="chc-step" value="1" style="width:80px"> each day</span></span>
                every day for <input class="form-control" type="number" id="chc-days" value="30" min="1" max="365" style="width:90px"> days,
                starting <input class="form-control" type="date" id="chc-start" value="${start.toISOString().slice(0, 10)}" style="width:170px">,
                with <input class="form-control" type="number" id="chc-skips" value="2" min="0" max="30" style="width:80px"> skips.</div>
            <div class="sq-sentence mt-2">It's a <select class="form-select" id="chc-kind"><option value="streak">streak</option><option value="target">daily target</option>
                <option value="ladder">ladder</option><option value="versus">squad versus squad</option></select> challenge;
                late joiners <select class="form-select" id="chc-late"><option value="prorate">count pro-rated</option><option value="ineligible">can't complete officially</option></select>.</div>`;
        const el = this.modal('sq-challenge-modal', 'New challenge', body, 'Start challenge', () => this.saveChallenge());
        const kind = el.querySelector('#chc-kind');
        kind.addEventListener('change', () => {
            el.querySelector('#chc-target-wrap').hidden = !['target', 'ladder'].includes(kind.value);
            el.querySelector('#chc-step-wrap').hidden = kind.value !== 'ladder';
        });
        const vis = el.querySelector('#chc-vis');
        vis.addEventListener('change', () => { const p = el.querySelector('#chc-parent'); if (p) p.hidden = vis.value !== 'squad' && kind.value !== 'versus'; });
    },

    async saveChallenge() {
        const g = id => document.getElementById(id);
        const item = g('chc-item').value.trim();
        if (!item) { showError('What is the challenge?'); return false; }
        const body = { title: item.charAt(0).toUpperCase() + item.slice(1), item_name: item, visibility: g('chc-vis').value, kind: g('chc-kind').value,
                       days: parseInt(g('chc-days').value, 10) || 30, start_date: g('chc-start').value, skip_tokens: parseInt(g('chc-skips').value, 10) || 0,
                       late_join: g('chc-late').value, timezone: this.tz(), daily_target: g('chc-target').value || null,
                       unit: g('chc-unit').value, ladder_step: g('chc-step').value || null };
        if (g('chc-parent') && (body.visibility === 'squad' || body.kind === 'versus')) body.parent_board = parseInt(g('chc-parent').value, 10);
        const res = await this.send('POST', 'challenges/', body);
        if (!this.ok(res)) { this.fail(res); return false; }
        await this.refresh();
        if (body.visibility !== 'squad') {
            const url = `${location.origin}${res.data.url}`;
            try { await navigator.clipboard.writeText(url); } catch (e) {}
            showSuccess(`Share it: ${url} (copied)`, 'Challenge created');
        }
        if (this.current && this.tab === 'challenges') this.tabChallenges();
        return true;
    },

    // Feed tab
    async tabFeed() {
        const b = this.current;
        const res = await this.get(`boards/${b.id}/feed/`);
        if (!this.ok(res)) throw new Error(res.error);
        const emojis = res.emojis || [];
        this.body().innerHTML = res.data.map(f => `<div class="sq-feed-item"><div class="text">${this.esc(f.text)}
                <div><time>${this.esc(this.ago(f.created_at))}</time></div>
                ${f.reactable ? `<div class="sq-reacts">${emojis.map(e => {
                    const n = f.reactions.counts[e] || 0;
                    return `<button class="sq-react ${f.reactions.mine === e ? 'mine' : ''}" onclick="Squads.react(${f.id}, '${e}', ${f.reactions.mine === e})">${e}${n ? ` ${n}` : ''}</button>`;
                }).join('')}</div>` : ''}</div></div>`).join('') || '<div class="sq-empty">Nothing yet. Check-ins, sessions and milestones show up here.</div>';
    },

    async react(feedId, emoji, isMine) {
        const res = await this.send(isMine ? 'DELETE' : 'POST', `boards/${this.current.id}/feed/${feedId}/react/`, { emoji });
        if (!this.ok(res)) return this.fail(res);
        this.tabFeed();
    },

    // Heatmap tab
    async tabHeatmap() {
        const b = this.current;
        const res = await this.get(`boards/${b.id}/heatmap/`);
        if (!this.ok(res)) throw new Error(res.error);
        const first = res.data[0] ? (new Date(res.data[0].day).getDay() + 6) % 7 : 0;
        const pad = Array(first).fill('<span></span>').join('');
        this.body().innerHTML = `<div class="sq-heatmap">${pad}${res.data.map(c => `<button class="sq-cell ${c.status}" style="--pct:${c.pct || 0}"
                title="${this.esc(c.day)}: ${this.esc(c.status.replace('_', ' '))}${c.counted ? ` · ${c.in}/${c.counted} in` : ''}"
                onclick="Squads.heatDay('${c.day}')"></button>`).join('')}</div>
            <div class="sq-legend"><span><span class="sq-cell survived"></span>survived</span><span><span class="sq-cell broken"></span>broken</span>
                <span><span class="sq-cell below" style="--pct:50"></span>below threshold</span><span><span class="sq-cell off"></span>off / away</span>
                <span><span class="sq-cell pre_start"></span>before start</span></div>
            <div id="sq-heat-day" class="mt-3"></div>`;
    },

    async heatDay(day) {
        const res = await this.get(`boards/${this.current.id}/heatmap/${day}/`);
        const box = document.getElementById('sq-heat-day');
        if (!this.ok(res) || !box) return;
        const d = res.data;
        box.innerHTML = d.status ? `<h3 class="section-title-sm">${this.esc(day)} · ${this.esc(d.status)} · ${d.pct}% in</h3>
            <ul class="sq-list">${d.members.map(m => `<li><span class="grow">${this.esc(m.name)}</span><span class="small">${this.esc(m.state.replace('_', ' '))}</span><span class="small ms-2">${m.points} pts</span></li>`).join('')}</ul>`
            : '<p class="small text-brown">Not evaluated yet: a day closes at the late-log cutoff.</p>';
    },

    // Settings tab
    async tabSettings() {
        const b = this.current;
        const admin = this.isAdmin();
        const [members, suggestions] = await Promise.all([this.get(`boards/${b.id}/members/`), admin ? this.get(`boards/${b.id}/suggestions/`) : null]);
        const me = AppConfig.userDetail?.user;
        const friends = this.ok(members) ? members.data.addable_friends : [];
        this.body().innerHTML = `
            <h3 class="section-title-sm">Invite</h3>
            <div class="sq-inline-form"><button class="btn btn-paper btn-primary btn-sm" onclick="Squads.share()"><i class="fa-brands fa-whatsapp me-1"></i>Share link</button>
                <button class="btn btn-paper btn-sm" onclick="Squads.copyInvite()"><i class="fas fa-link me-1"></i>Copy link</button>
                ${admin ? `<button class="btn btn-paper btn-sm" onclick="Squads.regenerate()">New link</button><button class="btn btn-paper btn-sm" onclick="Squads.revoke()">Revoke links</button>` : ''}
                <small class="text-brown">Links expire after 7 days.</small></div>
            ${friends.length ? `<div class="sq-inline-form sq-sentence">${admin ? 'Add' : 'Suggest'} <select class="form-select form-select-sm" id="sq-add-friend">${friends.map(f => `<option value="${f.user_id}">${this.esc(f.name)}</option>`).join('')}</select>
                ${admin ? 'to the squad right away' : 'to an admin'}. <button class="btn btn-paper btn-sm btn-primary" onclick="Squads.addFriend()">${admin ? 'Add' : 'Suggest'}</button></div>` : '<p class="small text-brown">Accepted friends you can add directly show up here.</p>'}
            ${suggestions && this.ok(suggestions) && suggestions.data.length ? `<ul class="sq-list">${suggestions.data.map(s => `<li><span class="grow">${this.esc(s.suggested_by)} suggests <strong>${this.esc(s.name)}</strong></span>
                <button class="btn btn-paper btn-sm btn-primary" onclick="Squads.decide(${s.id}, true)">Add</button><button class="btn btn-paper btn-sm" onclick="Squads.decide(${s.id}, false)">Decline</button></li>`).join('')}</ul>` : ''}

            <h3 class="section-title-sm mt-4">Members</h3>
            <ul class="sq-list">${b.member_list.map(m => `<li><span class="sq-ring">${this.esc(m.initials)}</span><span class="grow">${this.esc(m.name)} <small>${m.role}</small></span>
                ${admin && m.role !== 'owner' && m.user_id !== me ? `<button class="btn btn-paper btn-sm" onclick="Squads.setRole(${m.user_id}, '${m.role === 'admin' ? 'member' : 'admin'}')">${m.role === 'admin' ? 'Make member' : 'Make admin'}</button>
                    <button class="btn btn-paper btn-sm" onclick="Squads.remove(${m.user_id})">Remove</button>` : ''}
                ${b.role === 'owner' && m.user_id !== me ? `<button class="btn btn-paper btn-sm" onclick="Squads.transfer(${m.user_id})">Make owner</button>` : ''}
                ${m.user_id !== me ? `<button class="btn btn-link btn-sm" onclick="Squads.blockUser(${m.user_id})">Block</button>` : ''}</li>`).join('')}</ul>

            <h3 class="section-title-sm mt-4">Me</h3>
            <div class="sq-inline-form sq-sentence">I'm away until <input class="form-control form-control-sm" type="date" id="sq-away" value="${this.esc(b.my_away_until || '')}" style="width:170px">
                <button class="btn btn-paper btn-sm" onclick="Squads.setAway()">Save</button>
                ${b.my_away_until ? '<button class="btn btn-paper btn-sm" onclick="Squads.setAway(true)">I\'m back</button>' : ''}
                <small class="text-brown">Away days don't count against the streak.</small></div>
            <div class="form-check form-switch my-2"><input class="form-check-input" type="checkbox" id="sq-mute" ${b.muted ? 'checked' : ''} onchange="Squads.mute(this.checked)">
                <label class="form-check-label" for="sq-mute">Mute this squad (you still hear about being added and calendar events)</label></div>

            ${admin ? `<h3 class="section-title-sm mt-4">Squad</h3>
            <div class="sq-sentence">We're called <input class="form-control form-control-sm" id="sq-set-name" value="${this.esc(b.name)}">
                <input class="form-control form-control-sm" id="sq-set-emoji" value="${this.esc(b.emoji)}" style="width:60px;min-width:60px">,
                a day survives when <input class="form-control form-control-sm" type="number" id="sq-set-threshold" min="10" max="100" placeholder="auto" value="${b.settings.streak_threshold_pct || ''}" style="width:90px">% of us are in
                <small class="text-brown">(auto: 100% for 2, 70% for 3+${b.settings.pending_threshold ? `; ${b.settings.pending_threshold.pct || 'auto'}% from ${this.esc(b.settings.pending_threshold.from)}` : ''})</small>,
                and late logs close at <input class="form-control form-control-sm" type="number" id="sq-set-cutoff" min="0" max="23" value="${b.settings.late_log_cutoff_hour}" style="width:80px">:00 next day,
                <input class="form-control form-control-sm" id="sq-set-tz" value="${this.esc(b.timezone)}" style="width:170px"> time.
                <button class="btn btn-paper btn-sm btn-primary" onclick="Squads.saveSettings()">Save</button></div>
            <p class="small text-brown">Threshold and core-habit changes apply from tomorrow; nothing is recomputed.</p>` : ''}

            <h3 class="section-title-sm mt-4">More</h3>
            <div class="sq-inline-form">
                <button class="btn btn-paper btn-sm" onclick="Squads.leave()">Leave squad</button>
                ${admin ? `<button class="btn btn-paper btn-sm" onclick="Squads.archive(${b.status === 'archived'})">${b.status === 'archived' ? 'Restore' : 'Archive (read-only)'}</button>` : ''}
                ${b.role === 'owner' ? '<button class="btn btn-paper btn-sm text-danger" onclick="Squads.deleteSquad()">Delete squad</button>' : ''}
                <button class="btn btn-link btn-sm" onclick="Squads.report('squad', ${b.id})">Report</button>
                <a class="btn btn-link btn-sm" href="/squads/api/export/?format=csv">Export my history</a></div>`;
    },

    async invite(body) {
        const res = body ? await this.send('POST', `boards/${this.current.id}/invite/`, body) : await this.get(`boards/${this.current.id}/invite/`);
        if (!this.ok(res)) { this.fail(res); return null; }
        return res.data;
    },

    /** One tap: the share sheet (WhatsApp first on phones), else WhatsApp web. */
    async share() {
        const inv = await this.invite({ channel: navigator.share ? 'share_sheet' : 'whatsapp' });
        if (!inv) return;
        if (navigator.share) {
            try { await navigator.share({ title: this.current.name, text: inv.text, url: inv.url }); return; } catch (e) { if (e.name === 'AbortError') return; }
        }
        window.open(inv.whatsapp, '_blank', 'noopener');
    },

    async copyInvite() {
        const inv = await this.invite({ channel: 'copy' });
        if (!inv) return;
        try { await navigator.clipboard.writeText(inv.url); showSuccess('Invite link copied', 'Copied'); } catch (e) { prompt('Invite link', inv.url); }
    },

    async regenerate() {
        const inv = await this.invite({ regenerate: true });
        if (inv) showSuccess('Old links stop working. New link: ' + inv.url, 'New invite link');
    },

    async revoke() {
        const res = await this.send('DELETE', `boards/${this.current.id}/invite/`);
        if (!this.ok(res)) return this.fail(res);
        showSuccess('All invite links for this squad are revoked.', 'Revoked');
    },

    async addFriend() {
        const res = await this.send('POST', `boards/${this.current.id}/members/`, { user_id: parseInt(document.getElementById('sq-add-friend').value, 10) });
        if (!this.ok(res)) return this.fail(res);
        showSuccess(res.data.added ? 'Added. They can stay or leave.' : 'Suggested to the admins.', 'Done');
        this.open(this.current.id, 'settings');
    },

    async decide(id, approve) {
        const res = await this.send('POST', `boards/${this.current.id}/suggestions/${id}/`, { approve });
        if (!this.ok(res)) return this.fail(res);
        this.open(this.current.id, 'settings');
    },

    async setRole(uid, role) {
        const res = await this.send('PATCH', `boards/${this.current.id}/members/${uid}/`, { role });
        if (!this.ok(res)) return this.fail(res);
        this.open(this.current.id, 'settings');
    },

    async remove(uid) {
        if (!confirm('Remove this member? Their contributions stay as "former member".')) return;
        const res = await this.send('DELETE', `boards/${this.current.id}/members/${uid}/`);
        if (!this.ok(res)) return this.fail(res);
        this.open(this.current.id, 'settings');
    },

    async transfer(uid) {
        if (!confirm('Make them the owner? You become an admin.')) return;
        const res = await this.send('POST', `boards/${this.current.id}/transfer/`, { user_id: uid });
        if (!this.ok(res)) return this.fail(res);
        this.open(this.current.id, 'settings');
    },

    async setAway(back) {
        const until = back ? null : document.getElementById('sq-away').value || null;
        const res = await this.send('POST', `boards/${this.current.id}/away/`, { until });
        if (!this.ok(res)) return this.fail(res);
        this.open(this.current.id, 'settings');
    },

    async mute(muted) {
        const res = await this.send('POST', `boards/${this.current.id}/mute/`, { muted });
        if (!this.ok(res)) this.fail(res);
    },

    async saveSettings() {
        const g = id => document.getElementById(id).value;
        const res = await this.send('PATCH', `boards/${this.current.id}/`, {
            name: g('sq-set-name'), emoji: g('sq-set-emoji'), timezone: g('sq-set-tz'),
            late_log_cutoff_hour: parseInt(g('sq-set-cutoff'), 10), streak_threshold_pct: g('sq-set-threshold') || null });
        if (!this.ok(res)) return this.fail(res);
        await this.refresh();
        this.open(this.current.id, 'settings');
    },

    async leave() {
        if (!confirm('Leave this squad? Your personal habits and history stay.')) return;
        const res = await this.send('POST', `boards/${this.current.id}/leave/`);
        if (!this.ok(res)) return this.fail(res);
        this.current = null;
        await this.refresh();
        switchPane('squads');
    },

    async archive(restore) {
        const res = await this.send('POST', `boards/${this.current.id}/archive/`, { restore });
        if (!this.ok(res)) return this.fail(res);
        await this.refresh();
        this.open(this.current.id, 'settings');
    },

    async deleteSquad() {
        const name = prompt(`Type the squad's name to delete it for everyone: ${this.current.name}`);
        if (name == null) return;
        const res = await this.send('DELETE', `boards/${this.current.id}/`, { confirm_name: name });
        if (!this.ok(res)) return this.fail(res);
        this.current = null;
        await this.refresh();
        switchPane('squads');
    },

    async blockUser(uid) {
        if (!confirm('Block this person? It ends your friendship and stops adds, invites and nudges between you.')) return;
        const res = await this.send('POST', 'block/', { user_id: uid });
        if (!this.ok(res)) return this.fail(res);
        showSuccess('Blocked.', 'Done');
    },

    async report(targetType, targetId) {
        const reason = prompt('What happened? This goes to the makeyourreps team.');
        if (!reason) return;
        const res = await this.send('POST', 'report/', { target_type: targetType, target_id: targetId, reason });
        if (!this.ok(res)) return this.fail(res);
        showSuccess('Thanks. We\'ll take a look.', 'Reported');
    },

    // ── notifications: web push + prefs ──
    async loadPrefs() {
        const [prefs, push] = await Promise.all([this.get('notification_prefs/'), this.get('push/')]);
        if (this.ok(prefs)) {
            const p = prefs.data;
            const set = (id, v) => { const el = document.getElementById(id); if (el) el.value = v || ''; };
            set('sq-quiet-start', p.quiet_start && p.quiet_start.slice(0, 5));
            set('sq-quiet-end', p.quiet_end && p.quiet_end.slice(0, 5));
            set('sq-daily-cap', p.daily_cap);
            if (this.tz() && p.timezone !== this.tz()) this.send('PUT', 'notification_prefs/', { timezone: this.tz() });
        }
        if (this.ok(push)) {
            this._vapid = push.data.vapid_public_key;
            this.syncPushUI();
        }
    },

    async savePrefs() {
        const g = id => document.getElementById(id).value;
        const res = await this.send('PUT', 'notification_prefs/', { quiet_start: g('sq-quiet-start') || null,
            quiet_end: g('sq-quiet-end') || null, daily_cap: parseInt(g('sq-daily-cap'), 10) || 6, timezone: this.tz() });
        if (!this.ok(res)) return this.fail(res);
        showSuccess('Saved', 'Notifications');
    },

    async pushSub() {
        if (!('serviceWorker' in navigator) || !('PushManager' in window)) return null;
        const reg = await navigator.serviceWorker.getRegistration('/board/');
        return reg ? reg.pushManager.getSubscription() : null;
    },

    async syncPushUI() {
        const btn = document.getElementById('sq-push-btn'), state = document.getElementById('sq-push-state');
        if (!btn) return;
        if (!this._vapid || !('PushManager' in window)) { btn.disabled = true; state.textContent = 'Push isn\'t available here; you get emails instead.'; return; }
        const sub = await this.pushSub();
        btn.textContent = sub ? 'Turn off push on this device' : 'Turn on push on this device';
        state.textContent = sub ? 'On' : 'Off: time-sensitive alerts come by email';
    },

    b64ToUint8(b64) {
        const pad = '='.repeat((4 - b64.length % 4) % 4);
        const raw = atob((b64 + pad).replace(/-/g, '+').replace(/_/g, '/'));
        return Uint8Array.from([...raw].map(c => c.charCodeAt(0)));
    },

    async togglePush() {
        const existing = await this.pushSub();
        if (existing) {
            await this.send('DELETE', 'push/', { endpoint: existing.endpoint });
            await existing.unsubscribe();
            return this.syncPushUI();
        }
        if ((await Notification.requestPermission()) !== 'granted') return showError('Notifications are blocked for this site in your browser settings.');
        const reg = await navigator.serviceWorker.getRegistration('/board/') || await navigator.serviceWorker.register('/sw.js', { scope: '/board/' });
        const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: this.b64ToUint8(this._vapid) });
        const json = sub.toJSON();
        const res = await this.send('POST', 'push/', { endpoint: json.endpoint, keys: json.keys });
        if (!this.ok(res)) this.fail(res);
        this.syncPushUI();
    },
};
