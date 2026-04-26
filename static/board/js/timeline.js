/**
 * timeline.js — Timeline rendering with lazy loading and action handling
 */

const Timeline = {
    events: [],
    loading: false,
    hasMore: true,

    init() {
        this.events = [];
        this.hasMore = true;
        this.loadEvents();
        this.setupScroll();
    },

    async loadEvents(before = null) {
        if (this.loading || !this.hasMore) return;
        this.loading = true;

        let url = 'board/api/timeline/';
        const today = getDate(new Date());
        if (before) {
            url += `?before=${before}`;
        } else {
            url += `?date=${today}`;
        }

        const res = await apiClient.get(url);
        this.loading = false;

        if (res.status === 'success') {
            this.events = this.events.concat(res.data);
            this.hasMore = res.has_more;
            this.render();
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

    render() {
        const list = document.getElementById('timeline-list');
        if (!list) return;

        if (this.events.length === 0) {
            const now = new Date();
            const clockFormat = document.body.getAttribute('data-clock') || '12h';
            const fmt = t => clockFormat === '24h'
                ? t.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
                : t.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true });
            const t = (offsetMin) => {
                const d = new Date(now); d.setMinutes(d.getMinutes() - offsetMin); return fmt(d);
            };
            const todayLabel = now.toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' });
            list.innerHTML = `
                <div class="timeline-date-separator">${todayLabel}</div>
                <div class="timeline-item timeline-type-routine" style="opacity:0.45;">
                    <div class="timeline-time">${t(90)}</div>
                    <div class="timeline-icon"><i class="fas fa-clock"></i></div>
                    <div class="timeline-content"><div class="timeline-event-text">Morning routine — Wake up &amp; stretch</div></div>
                </div>
                <div class="timeline-item timeline-type-habit" style="opacity:0.45;">
                    <div class="timeline-time">${t(60)}</div>
                    <div class="timeline-icon"><i class="fas fa-bolt"></i></div>
                    <div class="timeline-content"><div class="timeline-event-text">Habit reminder — Read 10 pages</div><div class="timeline-actions"><span class="badge-done"><i class="fas fa-check"></i> Done</span></div></div>
                </div>
                <div class="timeline-item timeline-type-todo" style="opacity:0.45;">
                    <div class="timeline-time">${t(30)}</div>
                    <div class="timeline-icon"><i class="fas fa-check-square"></i></div>
                    <div class="timeline-content"><div class="timeline-event-text">Task due — Finish project draft</div></div>
                </div>
                <div class="timeline-item timeline-type-journal" style="opacity:0.45;" id="timeline-now-anchor">
                    <div class="timeline-time">${t(5)}</div>
                    <div class="timeline-icon"><i class="fas fa-pen-fancy"></i></div>
                    <div class="timeline-content"><div class="timeline-event-text">Journal reminder — How was your morning?</div></div>
                </div>
                <div class="timeline-empty" style="margin-top:12px;">No real events yet — these are previews.</div>
            `;
            this.scrollToNow();
            return;
        }

        const clockFormat = document.body.getAttribute('data-clock') || '12h';
        const now = new Date();

        // Sort ascending (oldest first)
        const sorted = [...this.events].sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));

        let lastDateStr = null;
        const today = getDate(now);
        const yesterday = getDate(new Date(Date.now() - 86400000));

        const dateLabel = (dateStr) => {
            if (dateStr === today) return 'Today';
            if (dateStr === yesterday) return 'Yesterday';
            return new Date(dateStr + 'T12:00:00').toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' });
        };

        // Find the last event at or before now to use as scroll anchor
        let anchorId = null;
        for (const event of sorted) {
            if (new Date(event.timestamp) <= now) anchorId = event.id;
            else break;
        }

        list.innerHTML = sorted.map(event => {
            const ts = new Date(event.timestamp);
            const dateStr = getDate(ts);
            let timeStr;
            if (clockFormat === '24h') {
                timeStr = ts.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
            } else {
                timeStr = ts.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true });
            }

            const typeIcon = this.getTypeIcon(event.event_type);
            const typeClass = `timeline-type-${event.event_type}`;
            const actionHtml = this.renderAction(event);
            const responded = event.action_response ? 'responded' : '';
            const anchorAttr = event.id === anchorId ? 'id="timeline-now-anchor"' : '';

            let separator = '';
            if (dateStr !== lastDateStr) {
                separator = `<div class="timeline-date-separator">${dateLabel(dateStr)}</div>`;
                lastDateStr = dateStr;
            }

            return `${separator}
                <div class="timeline-item ${typeClass} ${responded}" data-id="${event.id}" ${anchorAttr}>
                    <div class="timeline-time">${timeStr}</div>
                    <div class="timeline-icon"><i class="${typeIcon}"></i></div>
                    <div class="timeline-content">
                        <div class="timeline-event-text">${event.event}</div>
                        ${actionHtml}
                    </div>
                </div>
            `;
        }).join('');

        this.scrollToNow();
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
                html += `<button class="btn btn-paper btn-sm btn-primary" id="check-btn-${event.id}"
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
        const res = await apiClient.post(`board/api/accountability_partners/${apId}/check/`);
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