/**
 * settings.js — Settings modal handler for all tabs
 */

const Settings = {
    searchEngines: [],

    async loadSearchEngines() {
        if (this.searchEngines.length > 0) return; // already loaded
        const res = await apiClient.get('board/api/search_engines/');
        if (res.status === 'success') {
            this.searchEngines = res.data;
            this.populateSearchEngineSelect();
        }
    },

    populateSearchEngineSelect() {
        const select = document.getElementById('searchEngineSelect');
        if (!select) return;
        select.innerHTML = this.searchEngines.map(e =>
            `<option value="${e.key}" ${e.key === (AppConfig.userDetail?.default_search_engine || 'google') ? 'selected' : ''}>${e.name}</option>`
        ).join('');
    },

    changeTheme() {
        const selected = document.getElementById('themeSelect').value;
        currentTheme = selected;
        document.body.setAttribute('data-theme', selected);
        document.getElementById('themeIcon').className = selected === 'light' ? 'fas fa-moon' : 'fas fa-sun';
        apiClient.put('board/api/user_details/', { default_theme: selected });
    },

    changeFont() {
        const font = document.getElementById('fontSelect').value;
        if (AppConfig.userDetail) AppConfig.userDetail.font_family = font;
        applyFont(font);
        apiClient.put('board/api/user_details/', { font_family: font });
    },

    changeClockFormat() {
        const format = document.getElementById('clockFormatSelect').value;
        if (AppConfig.userDetail) AppConfig.userDetail.clock_format = format;
        document.body.setAttribute('data-clock', format);
        apiClient.put('board/api/user_details/', { clock_format: format });
        // Refresh the clock display
        DefaultPane.startClock();
    },

    changeSearchEngine() {
        const engine = document.getElementById('searchEngineSelect').value;
        if (AppConfig.userDetail) AppConfig.userDetail.default_search_engine = engine;
        DefaultPane.currentEngine = engine;
        DefaultPane.updateSearchIcon();
        DefaultPane.buildSearchDropdown();
        apiClient.put('board/api/user_details/', { default_search_engine: engine });
    },

    changeSleepTime() {
        const time = document.getElementById('sleepTimeInput').value;
        if (AppConfig.userDetail) AppConfig.userDetail.sleep_time = time || null;
        apiClient.put('board/api/user_details/', { sleep_time: time || null });
    },

    savePomodoroSettings() {
        const focus = parseInt(document.getElementById('pomFocus').value) || 25;
        const brk = parseInt(document.getElementById('pomBreak').value) || 5;
        const longBreak = parseInt(document.getElementById('pomLongBreak').value) || 15;
        const cycles = parseInt(document.getElementById('pomCycles').value) || 4;

        apiClient.put('board/api/user_details/', {
            pomodoro_focus: focus,
            pomodoro_break: brk,
            pomodoro_long_break: longBreak,
            pomodoro_cycles: cycles,
        });

        Pomodoro.updateSettings({
            focusMin: focus,
            breakMin: brk,
            longBreakMin: longBreak,
            cycles: cycles,
        });
    },

    async saveName() {
        const first_name = document.getElementById('settingsFirstName').value.trim();
        const last_name = document.getElementById('settingsLastName').value.trim();
        const btn = document.getElementById('settings-name-save-btn');
        btn.disabled = true;
        const res = await apiClient.put('board/api/user_details/', { first_name, last_name });
        btn.disabled = false;
        if (res.status === 'success') {
            if (AppConfig.userDetail) {
                AppConfig.userDetail.first_name = first_name;
                AppConfig.userDetail.last_name = last_name;
            }
            btn.textContent = 'Saved!';
            setTimeout(() => { btn.textContent = 'Save'; }, 2000);
        }
    },

    saveSoundSettings() {
        const pomSound = document.getElementById('soundPomodoro').checked;
        const notifSound = document.getElementById('soundNotifications').checked;
        if (AppConfig.userDetail) {
            AppConfig.userDetail.sound_pomodoro = pomSound;
            AppConfig.userDetail.sound_notifications = notifSound;
        }
        apiClient.put('board/api/user_details/', {
            sound_pomodoro: pomSound,
            sound_notifications: notifSound,
        });
    }
};

/**
 * GoogleCalendar — Integrations tab UI for connecting and managing Google Calendars.
 */
window.GoogleCalendar = {
    loaded: false,

    async connect() {
        const res = await apiClient.get('board/api/calendar/auth/');
        if (res.url) {
            window.location.href = res.url;
        }
    },

    async load() {
        if (this.loaded) return;
        this.loaded = true;
        const res = await apiClient.get('board/api/calendar/accounts/');
        if (res.status === 'success') {
            this._render(res.data);
        }
    },

    async refresh(tokenId) {
        await apiClient.post(`board/api/calendar/accounts/${tokenId}/refresh/`);
        this.loaded = false;
        await this.load();
    },

    async disconnect(tokenId) {
        this._pendingDisconnectId = tokenId;
        new bootstrap.Modal(document.getElementById('calendarDisconnectModal')).show();
    },

    async _confirmDisconnect() {
        const tokenId = this._pendingDisconnectId;
        if (!tokenId) return;
        this._pendingDisconnectId = null;
        bootstrap.Modal.getInstance(document.getElementById('calendarDisconnectModal'))?.hide();
        await apiClient.delete(`board/api/calendar/accounts/${tokenId}/disconnect/`);
        this.loaded = false;
        await this.load();
    },

    async toggleCalendar(calId, field, value) {
        await apiClient.patch(`board/api/calendar/calendars/${calId}/`, { [field]: value });
        this.loaded = false;
        await this.load();
    },

    _render(accounts) {
        const container = document.getElementById('calendar-accounts-list');
        if (!container) return;
        if (!accounts.length) {
            container.innerHTML = '<p class="text-brown small">No Google accounts connected yet.</p>';
            return;
        }
        container.innerHTML = accounts.map(account => `
            <div class="settings-card mb-3">
                <div class="d-flex align-items-center justify-content-between mb-3">
                    <div>
                        <i class="fab fa-google me-2" style="color:var(--ink-brown)"></i>
                        <strong style="font-size:0.9rem">${account.google_email}</strong>
                    </div>
                    <div class="d-flex gap-2">
                        <button class="btn btn-paper btn-sm" data-cal-action="refresh" data-cal-id="${account.id}" title="Refresh calendar list">
                            <i class="fas fa-sync-alt"></i>
                        </button>
                        <button class="btn btn-paper btn-sm" data-cal-action="disconnect" data-cal-id="${account.id}">
                            <i class="fas fa-unlink me-1"></i>Disconnect
                        </button>
                    </div>
                </div>
                ${account.calendars.map(cal => `
                    <div class="d-flex align-items-start gap-3 mb-3 pb-3" style="border-bottom:1px solid rgba(152,117,63,0.1)">
                        <span style="width:12px;height:12px;border-radius:50%;background:${cal.color || '#98753f'};flex-shrink:0;margin-top:3px"></span>
                        <div style="flex:1;min-width:0">
                            <div style="font-size:0.88rem;font-weight:600;color:var(--ink-brown)">${cal.name}</div>
                            <div class="d-flex flex-wrap gap-3 mt-2">
                                <label class="d-flex align-items-center gap-2" style="font-size:0.8rem;cursor:pointer">
                                    <input type="checkbox" ${cal.is_enabled ? 'checked' : ''}
                                        data-cal-id="${cal.id}" data-cal-toggle="is_enabled">
                                    Show in timeline
                                </label>
                                <label class="d-flex align-items-center gap-2" style="font-size:0.8rem;cursor:pointer">
                                    <input type="checkbox" ${cal.sync_habits ? 'checked' : ''}
                                        data-cal-id="${cal.id}" data-cal-toggle="sync_habits">
                                    Push habit reminders
                                </label>
                                <label class="d-flex align-items-center gap-2" style="font-size:0.8rem;cursor:pointer">
                                    <input type="checkbox" ${cal.sync_tasks ? 'checked' : ''}
                                        data-cal-id="${cal.id}" data-cal-toggle="sync_tasks">
                                    Push task deadlines
                                </label>
                            </div>
                        </div>
                    </div>
                `).join('')}
            </div>
        `).join('');
    },
};

(function initCalendarUI() {
    const intTab = document.getElementById('tab-integrations');
    const connectBtn = document.getElementById('btn-calendar-connect');

    if (intTab) {
        intTab.addEventListener('shown.bs.tab', () => window.GoogleCalendar.load());
    }
    if (connectBtn) {
        connectBtn.addEventListener('click', () => window.GoogleCalendar.connect());
    }

    const disconnectConfirmBtn = document.getElementById('calendar-disconnect-confirm-btn');
    if (disconnectConfirmBtn) {
        disconnectConfirmBtn.addEventListener('click', () => window.GoogleCalendar._confirmDisconnect());
    }

    // Delegate clicks for dynamically rendered disconnect/refresh/toggle buttons
    const accountsList = document.getElementById('calendar-accounts-list');
    if (accountsList) {
        accountsList.addEventListener('click', e => {
            const btn = e.target.closest('[data-cal-action]');
            if (!btn) return;
            const action = btn.dataset.calAction;
            const id = btn.dataset.calId;
            if (action === 'disconnect') window.GoogleCalendar.disconnect(id);
            if (action === 'refresh') window.GoogleCalendar.refresh(id);
        });
        accountsList.addEventListener('change', e => {
            const input = e.target.closest('[data-cal-toggle]');
            if (!input) return;
            window.GoogleCalendar.toggleCalendar(input.dataset.calId, input.dataset.calToggle, input.checked);
        });
    }

    // Auto-open Integrations tab if redirected back from Google OAuth
    const params = new URLSearchParams(window.location.search);
    if (params.get('calendar') === 'connected' && params.get('pane') === 'settings') {
        history.replaceState({}, '', window.location.pathname);
        setTimeout(() => {
            switchPane('settings');
            if (intTab) intTab.click();
        }, 300);
    }
}());