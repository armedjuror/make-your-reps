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