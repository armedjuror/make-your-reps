/**
 * timeline.js — Timeline rendering with lazy loading and action handling
 */

const Timeline = {
    events: [],
    loading: false,
    hasMore: true,
    currentDate: null,
    generatedDates: new Set(),

    _maxDate() {
        return getDate(new Date(Date.now() + 3 * 86400000));
    },

    init() {
        this.events = [];
        this.hasMore = true;
        this.currentDate = getDate(new Date());
        this.updateDateLabel();
        this.loadEvents();
        this.setupScroll();
        if (!this._bound) { this._bound = true; this._bindListEvents(); }

        document.getElementById('timeline-prev-btn')?.addEventListener('click', () => this.navigateDate(-1));
        document.getElementById('timeline-next-btn')?.addEventListener('click', () => this.navigateDate(1));
    },

    updateDateLabel() {
        const el = document.getElementById('timeline-date-label');
        if (!el) return;
        const today = getDate(new Date());
        const yesterday = getDate(new Date(Date.now() - 86400000));
        const tomorrow = getDate(new Date(Date.now() + 86400000));
        if (this.currentDate === today) el.textContent = 'Today';
        else if (this.currentDate === yesterday) el.textContent = 'Yesterday';
        else if (this.currentDate === tomorrow) el.textContent = 'Tomorrow';
        else el.textContent = new Date(this.currentDate + 'T12:00:00').toLocaleDateString('en-US', {
            weekday: 'short', month: 'short', day: 'numeric'
        });

        const nextBtn = document.getElementById('timeline-next-btn');
        if (nextBtn) nextBtn.disabled = this.currentDate >= this._maxDate();
    },

    async navigateDate(direction) {
        if (this.loading) return;
        const d = new Date(this.currentDate + 'T12:00:00');
        d.setDate(d.getDate() + direction);
        const newDate = getDate(d);

        if (newDate > this._maxDate()) return;

        this.currentDate = newDate;
        this.events = [];
        this.hasMore = true;
        this.updateDateLabel();
        await this.loadEvents();
    },

    async loadEvents(before = null) {
        if (this.loading || !this.hasMore) return;
        this.loading = true;

        let url = 'board/api/timeline/';
        if (before) {
            url += `?before=${before}`;
        } else {
            url += `?date=${this.currentDate}`;
        }

        const res = await apiClient.get(url);
        this.loading = false;

        if (res.status === 'success') {
            // Auto-generate if no real events exist yet for this date
            const realTypes = ['habit', 'todo', 'meeting', 'accountability_habit', 'accountability_invite', 'friend_request'];
            const hasRealEvents = res.data.some(e => realTypes.includes(e.event_type));
            if (!before && !hasRealEvents && !this.generatedDates.has(this.currentDate)) {
                this.generatedDates.add(this.currentDate);
                await apiClient.post('board/api/timeline/generate/', { date: this.currentDate });
                await this.loadEvents();
                return;
            }
            this.events = this.events.concat(res.data);
            this.hasMore = res.has_more;
            this.render();
            if (typeof Greeting !== 'undefined') Greeting.schedule();
        }
    },

    setupScroll() {
        const container = document.getElementById('timeline-container');
        if (!container) return;

        container.addEventListener('scroll', () => {
            const { scrollTop, scrollHeight, clientHeight } = container;
            if (scrollHeight - scrollTop - clientHeight < 50 && this.hasMore && !this.loading) {
                const lastEvent = this.events[this.events.length - 1];
                if (lastEvent) {
                    this.loadEvents(lastEvent.timestamp);
                }
            }
        });
    },

    // ── Filters (All / Habits / Todos / Routine) ──
    filter: 'all',
    showEarlier: false,
    reschedTarget: null,   // event id, or 'all', while the date picker is open
    reschedDate: '',
    showAllOverdue: false,
    groupFilter: '',   // '' = all groups, otherwise a task group id
    FILTER_TYPES: {
        habits: ['habit', 'accountability_habit'],
        todos: ['todo'],
        routine: ['routine', 'sleep_tracker', 'journal'],
    },

    esc(str) {
        const d = document.createElement('div');
        d.textContent = str == null ? '' : String(str);
        return d.innerHTML;
    },

    /** Fill the group select from the task groups present in the loaded events. */
    _syncGroupSelect(events) {
        const sel = document.getElementById('timeline-group-filter');
        if (!sel) return;
        const groups = new Map();
        events.forEach(e => { if (e.group) groups.set(String(e.group.id), e.group.name); });
        if (this.groupFilter && !groups.has(this.groupFilter)) this.groupFilter = '';
        sel.hidden = groups.size === 0;
        const opts = ['<option value="">All groups</option>']
            .concat([...groups].sort((a, b) => a[1].localeCompare(b[1]))
                .map(([id, name]) => `<option value="${this.esc(id)}">${this.esc(name)}</option>`));
        const html = opts.join('');
        if (sel.dataset.sig !== html) { sel.innerHTML = html; sel.dataset.sig = html; }
        sel.value = this.groupFilter;
    },

    setFilter(filter) {
        this.filter = filter;
        document.querySelectorAll('.timeline-chip').forEach(b =>
            b.classList.toggle('active', b.dataset.tlFilter === filter));
        this.render();
    },

    _fmtTime(ts) {
        const clockFormat = document.body.getAttribute('data-clock') || '12h';
        return clockFormat === '24h'
            ? ts.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
            : ts.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true });
    },

    _until(ts, now) {
        const min = Math.max(0, Math.round((ts - now) / 60000));
        const h = Math.floor(min / 60), m = min % 60;
        return h ? `${h}h ${m}m` : `${m}m`;
    },

    _tomorrow() {
        return getDate(new Date(Date.now() + 86400000));
    },

    /** Inline date chooser for rescheduling one overdue task or all of them. */
    _pickerHtml(target, verb) {
        if (!this.reschedDate) this.reschedDate = this._tomorrow();
        const d = this.reschedDate;
        const quick = (label, days) => {
            const v = getDate(new Date(Date.now() + days * 86400000));
            return `<button type="button" class="tl-link" data-tl-action="resched-quick" data-date="${v}">${label}</button>`;
        };
        return `
            <div class="tl-resched">
                <input type="date" class="tl-date" data-tl-date min="${getDate(new Date())}" value="${this.esc(d)}" aria-label="New date">
                ${quick('Tomorrow', 1)}${quick('In a week', 7)}
                <button type="button" class="btn btn-paper btn-sm btn-primary" data-tl-action="resched-go" data-target="${this.esc(target)}">${verb}</button>
                <button type="button" class="tl-link" data-tl-action="resched-cancel">Cancel</button>
            </div>`;
    },

    _actionsFor(event, extraClass) {
        const html = this.renderAction(event);
        if (!extraClass.includes('timeline-overdue') || event.action_response) return html;
        if (this.reschedTarget === event.id) return html + this._pickerHtml(String(event.id), 'Move');
        const btn = `<button type="button" class="btn btn-paper btn-sm ms-1" data-tl-action="resched-open" data-target="${event.id}"><i class="fas fa-calendar-day me-1"></i>Reschedule</button>`;
        return html.includes('timeline-actions') ? html.replace(/<\/div>\s*$/, btn + '</div>') : html;
    },

    _itemHtml(event, extraClass = '', label = '') {
        const ts = new Date(event.timestamp);
        const responded = event.action_response ? 'responded' : '';
        return `
            <div class="timeline-item ${this.esc('timeline-type-' + event.event_type)} ${responded} ${extraClass}" data-id="${event.id}">
                <div class="timeline-time">${this._fmtTime(ts)}</div>
                <div class="timeline-icon"><i class="${this.getTypeIcon(event.event_type)}"></i></div>
                <div class="timeline-content">
                    ${label ? `<div class="timeline-label">${label}</div>` : ''}
                    <div class="timeline-event-text">${this.esc(event.event)}${event.group ? ` <span class="timeline-group">${this.esc(event.group.name)}</span>` : ''}</div>
                    ${this._actionsFor(event, extraClass)}
                </div>
            </div>`;
    },

    render() {
        const list = document.getElementById('timeline-list');
        if (!list) return;

        let events = this.events.filter(e => !(e.action_response && e.action_response.snooze));
        this._syncGroupSelect(events);
        const types = this.FILTER_TYPES[this.filter];
        if (types) events = events.filter(e => types.includes(e.event_type));
        if (this.groupFilter) events = events.filter(e => e.group && String(e.group.id) === this.groupFilter);

        if (events.length === 0) {
            list.innerHTML = `<div class="timeline-empty">${this.filter === 'all'
                ? 'Nothing scheduled for this day.' : 'Nothing here for this filter.'}</div>`;
            return;
        }

        const now = new Date();
        const todayStr = getDate(now);
        const sorted = [...events].sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));

        // Other days: a plain chronological list
        if (this.currentDate !== todayStr) {
            list.innerHTML = sorted.map(e => this._itemHtml(e)).join('');
            return;
        }

        // Today: overdue card, earlier (collapsed), NOW, next, upcoming
        const isOverdue = e => this._isOverdue(e);
        const overdue = sorted.filter(isOverdue);
        const rest = sorted.filter(e => !isOverdue(e));
        const past = rest.filter(e => new Date(e.timestamp) <= now);
        const upcoming = rest.filter(e => new Date(e.timestamp) > now);

        let html = '';

        if (overdue.length) {
            const shown = this.showAllOverdue ? overdue : overdue.slice(0, 1);
            html += `
                <div class="tl-overdue">
                    <div class="tl-overdue-head">
                        <span><i class="fas fa-triangle-exclamation"></i> ${this.esc(Theme.text('overdue'))} &middot; ${overdue.length}</span>
                        <span class="tl-overdue-actions">
                            ${overdue.length > 1 ? `<button type="button" class="tl-link" data-tl-action="toggle-overdue">${this.showAllOverdue ? 'Show less' : `Show all ${overdue.length}`}</button>` : ''}
                            <button type="button" class="tl-link" data-tl-action="resched-open" data-target="all">Reschedule all</button>
                        </span>
                    </div>
                    ${this.reschedTarget === 'all' ? this._pickerHtml('all', `Move all ${overdue.length}`) : ''}
                    ${shown.map(e => this._itemHtml(e, 'timeline-overdue')).join('')}
                </div>`;
        }

        // Past: keep the most recent one visible, fold the rest
        const latest = past.length ? past[past.length - 1] : null;
        const folded = past.slice(0, -1);
        if (folded.length) {
            const pending = folded.filter(e => e.action && !e.action_response).length;
            const names = folded.slice(-6).map(e => this.esc(e.event)).join(' &middot; ');
            html += `
                <div class="tl-earlier ${this.showEarlier ? 'open' : ''}">
                    <button type="button" class="tl-earlier-head" data-tl-action="toggle-earlier" aria-expanded="${this.showEarlier}">
                        <span class="tl-earlier-title">${folded.length} earlier today${pending ? ` <em>&middot; ${pending} not done</em>` : ''}</span>
                        <i class="fas fa-chevron-down"></i>
                    </button>
                    ${this.showEarlier
                        ? `<div class="tl-earlier-body">${folded.map(e => this._itemHtml(e)).join('')}</div>`
                        : `<div class="tl-earlier-names">${names}</div>`}
                </div>`;
        }
        if (latest) html += this._itemHtml(latest, 'timeline-previous');

        html += `
            <div class="timeline-now" id="timeline-now-anchor">
                <div class="timeline-time">${this._fmtTime(now)}</div>
                <div class="timeline-now-dot"></div>
                <div class="timeline-now-label">${this.esc(Theme.text('now'))}</div>
                <div class="timeline-now-line"></div>
            </div>`;

        upcoming.forEach((e, i) => {
            html += i === 0
                ? this._itemHtml(e, 'timeline-next', this.esc(Theme.text('next', this._until(new Date(e.timestamp), now).toUpperCase())))
                : this._itemHtml(e);
        });
        if (!upcoming.length) html += '<div class="timeline-empty">Nothing else today.</div>';

        list.innerHTML = html;

        // First paint of Today: bring NOW into view if it landed below the fold
        if (!this._scrolled) {
            this._scrolled = true;
            requestAnimationFrame(() => {
                const a = document.getElementById('timeline-now-anchor');
                if (!a) return;
                // The scrolling element is the window on desktop, an inner pane on mobile
                let scroller = a.parentElement;
                while (scroller && scroller !== document.body) {
                    const oy = getComputedStyle(scroller).overflowY;
                    if ((oy === 'auto' || oy === 'scroll') && scroller.scrollHeight > scroller.clientHeight) break;
                    scroller = scroller.parentElement;
                }
                const top = a.getBoundingClientRect().top;
                if (top <= window.innerHeight * 0.55) return;
                if (scroller && scroller !== document.body) {
                    let target = scroller.scrollTop + top - 200;
                    // Never scroll the greeting out of view on small screens
                    const g = document.getElementById('greeting-text');
                    if (g) target = Math.min(target, scroller.scrollTop + g.getBoundingClientRect().top - scroller.getBoundingClientRect().top - 12);
                    scroller.scrollTo({ top: Math.max(0, target), behavior: 'smooth' });
                } else {
                    window.scrollTo({ top: window.scrollY + top - 160, behavior: 'smooth' });
                }
            });
        }
    },

    _bindListEvents() {
        const list = document.getElementById('timeline-list');
        if (list) list.addEventListener('click', (e) => {
            const btn = e.target.closest('[data-tl-action]');
            if (!btn) return;
            if (btn.dataset.tlAction === 'toggle-earlier') this.showEarlier = !this.showEarlier;
            const act = btn.dataset.tlAction;
            if (act === 'toggle-overdue') this.showAllOverdue = !this.showAllOverdue;
            if (act === 'resched-open') {
                const t = btn.dataset.target;
                this.reschedTarget = t === 'all' ? 'all' : Number(t);
                this.reschedDate = this._tomorrow();
            }
            if (act === 'resched-cancel') this.reschedTarget = null;
            if (act === 'resched-quick') this.reschedDate = btn.dataset.date;
            if (act === 'resched-go') {
                const date = this.reschedDate;
                if (!date || date < getDate(new Date())) return;
                const t = btn.dataset.target;
                btn.disabled = true;
                if (t === 'all') this.snoozeAllOverdue(date); else this.snooze(Number(t), date);
                return;
            }
            this.render();
        });
        if (list) list.addEventListener('change', (e) => {
            if (e.target.matches('[data-tl-date]')) this.reschedDate = e.target.value;
        });
        document.querySelectorAll('.timeline-chip').forEach(b =>
            b.addEventListener('click', () => this.setFilter(b.dataset.tlFilter)));
        const gsel = document.getElementById('timeline-group-filter');
        if (gsel) gsel.addEventListener('change', () => { this.groupFilter = gsel.value; this.render(); });
        // Keep the NOW marker honest while the tab stays open
        setInterval(() => {
            const pane = document.getElementById('pane-home');
            if (pane && pane.style.display !== 'none' && !document.activeElement?.closest?.('#timeline-list')) this.render();
        }, 60000);
    },

    async snooze(eventId, date = 'tomorrow') {
        const res = await apiClient.put(`board/api/timeline/${eventId}/respond/`, {
            action_response: { snooze: date }
        });
        if (res.status === 'success') {
            this.reschedTarget = null;
            const idx = this.events.findIndex(e => e.id === eventId);
            if (idx >= 0) this.events[idx] = res.data;
            this.render();
            if (typeof TodosPane !== 'undefined' && panesLoaded?.todos) TodosPane.loadTodos();
        }
        return res.status === 'success';
    },

    async snoozeAllOverdue(date = 'tomorrow') {
        const ids = this.events
            .filter(e => this._isOverdue(e) && !(e.action_response && e.action_response.snooze))
            .map(e => e.id);
        for (const id of ids) {
            const idx = this.events.findIndex(e => e.id === id);
            const res = await apiClient.put(`board/api/timeline/${id}/respond/`, { action_response: { snooze: date } });
            if (res.status === 'success' && idx >= 0) this.events[idx] = res.data;
        }
        this.reschedTarget = null;
        this.render();
        if (typeof TodosPane !== 'undefined' && panesLoaded?.todos) TodosPane.loadTodos();
    },

    _isOverdue(e) {
        return e.event_type === 'todo' && !e.action_response && /^overdue/i.test(e.event || '');
    },

    scrollToNow() {
        const anchor = document.getElementById('timeline-now-anchor');
        const container = document.getElementById('timeline-container');
        if (!anchor || !container) return;
        requestAnimationFrame(() => {
            const anchorTop = anchor.getBoundingClientRect().top;
            const containerTop = container.getBoundingClientRect().top;
            container.scrollTop += anchorTop - containerTop - 8;
        });
    },

    getTypeIcon(type) {
        const icons = {
            habit: 'fas fa-bolt',
            todo: 'fas fa-check-square',
            routine: 'fas fa-clock',
            sleep_tracker: 'fas fa-moon',
            journal: 'fas fa-pen-fancy',
            text: 'fas fa-comment',
            meeting: 'fas fa-video',
            friend_request: 'fas fa-user-plus',
            accountability_invite: 'fas fa-handshake',
            accountability_habit: 'fas fa-user-check',
        };
        return icons[type] || 'fas fa-circle';
    },

    renderAction(event) {
        if (!event.action) return '';
        if (event.action_response) {
            // Already responded
            return this.renderActionResponse(event);
        }

        const keys = Object.keys(event.action);
        let html = '<div class="timeline-actions">';

        for (const key of keys) {
            const values = event.action[key];

            if (key === 'accept') {
                // Friend request or accountability invite — Accept + Decline
                html += `
                    <button class="btn btn-paper btn-sm btn-primary timeline-toggle"
                        onclick="Timeline.respondAccept(${event.id}, true)">
                        <i class="fas fa-check me-1"></i>Accept
                    </button>
                    <button class="btn btn-paper btn-sm ms-1"
                        onclick="Timeline.respondAccept(${event.id}, false)">
                        <i class="fas fa-times me-1"></i>Decline
                    </button>`;
            } else if (key === 'check') {
                const apId = event.reference?.id;
                html += `<button class="btn btn-paper btn-sm" id="check-btn-${event.id}"
                    onclick="Timeline.checkHabit(${event.id}, ${apId})">
                    <i class="fas fa-eye me-1"></i>Check
                </button>`;
            } else if (key === 'remind') {
                const apId = event.reference?.id;
                html += `<button class="btn btn-paper btn-sm ms-1" id="remind-btn-${event.id}"
                    onclick="Timeline.remindHabit(${event.id}, ${apId})">
                    <i class="fas fa-bell me-1"></i>Remind
                </button>`;
            } else if (key === 'join' || (typeof values === 'string' && values.startsWith('http'))) {
                html += `<a href="${values}" target="_blank" class="btn btn-paper btn-sm btn-primary">
                    <i class="fas fa-external-link-alt me-1"></i>Join
                </a>`;
            } else if (key === 'open_journal') {
                html += `<button class="btn btn-paper btn-sm btn-primary" onclick="switchPane('journals')">
                    <i class="fas fa-pen me-1"></i>Write
                </button>`;
            } else if (key === 'log_sleep') {
                html += `<button class="btn btn-paper btn-sm btn-primary" onclick="openSleepModal()">
                    <i class="fas fa-moon me-1"></i>Log Sleep
                </button>`;
            } else if (Array.isArray(values) && values.length === 2 &&
                       values.includes(true) && values.includes(false)) {
                html += `<button class="btn btn-paper btn-sm btn-primary timeline-toggle"
                    onclick="Timeline.respondToggle(${event.id}, '${key}', true)">
                    <i class="fas fa-check me-1"></i>Done
                </button>`;
            } else if (Array.isArray(values) && values.length > 2) {
                html += `<select class="form-control form-control-sm timeline-select"
                    onchange="Timeline.respondSelect(${event.id}, '${key}', this.value)">
                    <option value="">Choose...</option>
                    ${values.map(v => `<option value="${v}">${v}</option>`).join('')}
                </select>`;
            }
        }

        html += '</div>';
        return html;
    },

    renderActionResponse(event) {
        const resp = event.action_response;
        const keys = Object.keys(resp);
        let label = '';
        for (const key of keys) {
            const val = resp[key];
            if (val === true) label = '<span class="badge-done"><i class="fas fa-check"></i> Done</span>';
            else if (val === false) label = '<span class="badge-skipped">Skipped</span>';
            else label = `<span class="badge-done">${val}</span>`;
        }
        return `<div class="timeline-actions">${label}</div>`;
    },

    async respondToggle(eventId, key, value) {
        const res = await apiClient.put(`board/api/timeline/${eventId}/respond/`, {
            action_response: { [key]: value }
        });
        if (res.status === 'success') {
            // Update local event
            const idx = this.events.findIndex(e => e.id === eventId);
            if (idx >= 0) {
                this.events[idx] = res.data;
            }
            this.render();
            if (value === true && typeof Theme !== 'undefined') Theme.celebrate();
            // Refresh productivity score
            General.loadProductivityScore();
        }
    },

    async respondSelect(eventId, key, value) {
        if (!value) return;
        const res = await apiClient.put(`board/api/timeline/${eventId}/respond/`, {
            action_response: { [key]: value }
        });
        if (res.status === 'success') {
            const idx = this.events.findIndex(e => e.id === eventId);
            if (idx >= 0) {
                this.events[idx] = res.data;
            }
            this.render();
            General.loadProductivityScore();
        }
    },

    async respondAccept(eventId, accept) {
        const res = await apiClient.put(`board/api/timeline/${eventId}/respond/`, {
            action_response: { accept }
        });
        if (res.status === 'success') {
            const idx = this.events.findIndex(e => e.id === eventId);
            if (idx >= 0) this.events[idx] = res.data;
            this.render();
            // Refresh misc pane if open
            if (typeof MiscPane !== 'undefined' && panesLoaded.misc) MiscPane.load();
        }
    },

    async checkHabit(eventId, apId) {
        const btn = document.getElementById(`check-btn-${eventId}`);
        if (btn) btn.disabled = true;
        const res = await apiClient.post(`board/api/accountability_partners/${apId}/check/`, { date: this.currentDate });
        if (res.status === 'success') {
            const { is_done } = res.data;
            const label = is_done
                ? '<i class="fas fa-check-circle me-1 text-success"></i>Done'
                : '<i class="fas fa-circle me-1"></i>Not done';
            if (btn) {
                btn.innerHTML = label;
                setTimeout(() => {
                    btn.innerHTML = '<i class="fas fa-eye me-1"></i>Check';
                    btn.disabled = false;
                }, 5000);
            }
        } else {
            if (btn) btn.disabled = false;
        }
    },

    async remindHabit(eventId, apId) {
        const btn = document.getElementById(`remind-btn-${eventId}`);
        if (btn) btn.disabled = true;
        const res = await apiClient.post(`board/api/accountability_partners/${apId}/remind/`);
        if (res.status === 'success') {
            if (btn) {
                btn.innerHTML = '<i class="fas fa-check me-1"></i>Sent!';
                setTimeout(() => {
                    btn.innerHTML = '<i class="fas fa-bell me-1"></i>Remind';
                    btn.disabled = false;
                }, 3000);
            }
        } else {
            if (btn) btn.disabled = false;
        }
    },
};