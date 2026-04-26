/**
 * config.js — Loads user config and dashboard config from APIs,
 * applies them to the DOM, and exposes AppConfig globally.
 * Must be loaded after utils.js and before all other JS files.
 */

const AppConfig = {
    userDetail: null,
    dashboardConfig: null,

    async load() {
        const [userRes, configRes] = await Promise.all([
            apiClient.get('board/api/user_details/', { silent: true }),
            apiClient.get('board/api/dashboard_config/', { silent: true }),
        ]);

        if (userRes.status === 'success') {
            this.userDetail = userRes.data;
            this._applyUserDetail(userRes.data);
        }
        if (configRes.status === 'success') {
            this.dashboardConfig = configRes.data;
            this._applyDashboardConfig(configRes.data);
        }
    },

    _applyUserDetail(d) {
        // Body attributes
        document.body.setAttribute('data-theme', d.default_theme || 'light');
        document.body.setAttribute('data-font', d.font_family || 'Montserrat');
        document.body.setAttribute('data-clock', d.clock_format || '12h');
        document.body.style.fontFamily = `'${d.font_family || 'Montserrat'}', sans-serif`;

        // Theme icon
        const icon = document.getElementById('themeIcon');
        if (icon) icon.className = d.default_theme === 'dark' ? 'fas fa-sun' : 'fas fa-moon';

        // Settings — general
        const firstNameEl = document.getElementById('settingsFirstName');
        if (firstNameEl) firstNameEl.value = d.first_name || '';
        const lastNameEl = document.getElementById('settingsLastName');
        if (lastNameEl) lastNameEl.value = d.last_name || '';

        const themeSelect = document.getElementById('themeSelect');
        if (themeSelect) themeSelect.value = d.default_theme || 'light';

        const fontSelect = document.getElementById('fontSelect');
        if (fontSelect) fontSelect.value = d.font_family || 'Montserrat';

        const clockSelect = document.getElementById('clockFormatSelect');
        if (clockSelect) clockSelect.value = d.clock_format || '12h';

        const sleepTime = document.getElementById('sleepTimeInput');
        if (sleepTime) sleepTime.value = d.sleep_time || '';

        // Settings — pomodoro
        const pomFocus = document.getElementById('pomFocus');
        if (pomFocus) pomFocus.value = d.pomodoro_focus ?? 25;

        const pomBreak = document.getElementById('pomBreak');
        if (pomBreak) pomBreak.value = d.pomodoro_break ?? 5;

        const pomLongBreak = document.getElementById('pomLongBreak');
        if (pomLongBreak) pomLongBreak.value = d.pomodoro_long_break ?? 15;

        const pomCycles = document.getElementById('pomCycles');
        if (pomCycles) pomCycles.value = d.pomodoro_cycles ?? 4;

        // Settings — sounds
        const soundPom = document.getElementById('soundPomodoro');
        if (soundPom) soundPom.checked = !!d.sound_pomodoro;

        const soundNotif = document.getElementById('soundNotifications');
        if (soundNotif) soundNotif.checked = !!d.sound_notifications;
    },

    _applyDashboardConfig(d) {
        const titles = d.section_titles || {};
        const titleMap = {
            habits: 'section-title-habits',
            routines: 'section-title-routines',
            sleep_tracker: 'section-title-sleep',
        };
        for (const [key, id] of Object.entries(titleMap)) {
            const el = document.getElementById(id);
            if (el && titles[key]) el.textContent = titles[key];
        }

        const copy = document.getElementById('copyright-text');
        if (copy) copy.innerHTML = d.copyright_text || '';
    },
};
