/**
 * dashboard.js — Main orchestrator
 * Handles pane switching, keyboard shortcuts, initialization
 */

let currentPane = 'home';
let panesLoaded = { home: false, todos: false, trackers: false, journals: false, achievements: false, 'reading-list': false, friends: false, settings: false, help: false };
let currentTheme = 'light';

// ── Pane Switching ──
function switchPane(pane) {
    if (pane === currentPane) return;

    // Hide all panes
    document.querySelectorAll('.pane').forEach(p => p.style.display = 'none');
    // Show target pane
    const target = document.getElementById(`pane-${pane}`);
    if (target) target.style.display = 'block';

    // Update tab bar (desktop)
    document.querySelectorAll('.tab-item').forEach(t => t.classList.remove('active'));
    const activeTab = document.querySelector(`.tab-item[data-pane="${pane}"]`);
    if (activeTab) activeTab.classList.add('active');

    // Update mobile menu
    document.querySelectorAll('.mobile-menu-item[data-pane]').forEach(t => t.classList.remove('active'));
    const activeMobileItem = document.querySelector(`.mobile-menu-item[data-pane="${pane}"]`);
    if (activeMobileItem) activeMobileItem.classList.add('active');

    // Update mobile bottom nav
    document.querySelectorAll('.mobile-bottom-nav-item[data-pane]').forEach(t => t.classList.remove('active'));
    const activeBottomItem = document.querySelector(`.mobile-bottom-nav-item[data-pane="${pane}"]`);
    if (activeBottomItem) activeBottomItem.classList.add('active');

    currentPane = pane;

    // Refresh footer bar pomodoro visibility on pane switch
    if (typeof Pomodoro !== 'undefined' && Pomodoro.state) Pomodoro.render();

    // Sync URL hash
    history.replaceState(null, '', pane === 'home' ? window.location.pathname : `#${pane}`);

    // Lazy load pane data on first visit
    if (!panesLoaded[pane]) {
        panesLoaded[pane] = true;
        if (pane === 'home') initHomePane();
        else if (pane === 'trackers') initTrackersPane();
        else if (pane === 'journals') initJournalsPane();
        else if (pane === 'todos') initTodosPane();
        else if (pane === 'achievements') MiscPane.loadAchievements();
        else if (pane === 'reading-list') ReadingList.loadAll();
        else if (pane === 'friends') MiscPane.initFriends();
        else if (pane === 'settings') Settings.loadSearchEngines();
    } else {
        // Refresh data-driven panes on every visit
        if (pane === 'achievements') MiscPane.loadAchievements();
        else if (pane === 'reading-list') ReadingList.loadAll();
        else if (pane === 'friends') MiscPane.load();
    }
}

// ── Mobile Menu ──
function toggleMobileMenu() {
    document.getElementById('mobile-menu').classList.toggle('open');
    document.getElementById('mobile-menu-overlay').classList.toggle('open');
}

function closeMobileMenu() {
    document.getElementById('mobile-menu').classList.remove('open');
    document.getElementById('mobile-menu-overlay').classList.remove('open');
}

// ── Theme ──
function toggleTheme() {
    currentTheme = currentTheme === 'light' ? 'dark' : 'light';
    document.body.setAttribute('data-theme', currentTheme);
    document.getElementById('themeIcon').className = currentTheme === 'light' ? 'fas fa-moon' : 'fas fa-sun';
    apiClient.put('board/api/user_details/', {default_theme: currentTheme});
}

// ── Font ──
function applyFont(fontFamily) {
    document.body.style.fontFamily = `'${fontFamily}', sans-serif`;
    document.body.setAttribute('data-font', fontFamily);
}

// ── Settings ──
function showSettings() {
    switchPane('settings');
}

// ── Keyboard Shortcuts ──
document.addEventListener('keydown', function (e) {
    const isMac = navigator.platform.toUpperCase().indexOf('MAC') >= 0;
    const modKey = isMac ? e.metaKey : e.ctrlKey;
    if (modKey && e.key === 'k') {
        e.preventDefault()
        document.getElementById('search-input').focus()
    } else if (modKey && e.key === ';') {
        e.preventDefault();
        Todo.showTodoModal();
    } else if (modKey && e.key === 'h') {
        e.preventDefault();
        Habits.showHabitModal();
    } else if (modKey && e.key === 'j') {
        e.preventDefault();
        switchPane('journals');
        setTimeout(() => {
            const editor = document.getElementById('journal-editor');
            if (editor) editor.focus();
        }, 200);
    }
});

// ── Event Listeners ──
function bindEvents() {
    // Navigation — desktop tab bar
    document.querySelectorAll('.tab-item[data-pane]').forEach(item => {
        item.addEventListener('click', () => switchPane(item.dataset.pane));
    });
    document.getElementById('tab-theme-btn').addEventListener('click', toggleTheme);
    // Settings is now triggered from the Others pane sub-tab

    // Navigation — mobile menu
    // document.getElementById('hamburger-btn').addEventListener('click', toggleMobileMenu);
    document.getElementById('mobile-menu-overlay').addEventListener('click', closeMobileMenu);
    document.getElementById('mobile-menu-close-btn').addEventListener('click', closeMobileMenu);
    document.querySelectorAll('.mobile-menu-item[data-pane]').forEach(item => {
        item.addEventListener('click', () => { switchPane(item.dataset.pane); closeMobileMenu(); });
    });

    // Mobile bottom nav
    document.querySelectorAll('.mobile-bottom-nav-item[data-pane]').forEach(item => {
        item.addEventListener('click', () => switchPane(item.dataset.pane));
    });
    document.getElementById('mobile-bottom-more-btn').addEventListener('click', toggleMobileMenu);
    document.getElementById('mobile-theme-btn').addEventListener('click', () => { toggleTheme(); closeMobileMenu(); });
    // Settings is now triggered from the Others pane sub-tab

    // Pomodoro
    document.getElementById('pomodoro-start').addEventListener('click', () => Pomodoro.toggle());
    document.getElementById('pomodoro-reset').addEventListener('click', () => Pomodoro.reset());
    document.getElementById('pomodoro-toggle-mode').addEventListener('click', () => Pomodoro.toggleMode());

    // Search
    document.getElementById('search-engine-btn').addEventListener('click', () => toggleSearchEngineDropdown());
    document.getElementById('search-input').addEventListener('keydown', e => {
        if (e.key === 'Enter') { e.preventDefault(); DefaultPane.doSearch(); }
    });

    // Home — habits & routines & sleep
    document.getElementById('new-habit-btn').addEventListener('click', () => Habits.showHabitModal());
    document.getElementById('workday_routine_button').addEventListener('click', () => showRoutine('workday'));
    document.getElementById('holiday_routine_button').addEventListener('click', () => showRoutine('holiday'));
    document.getElementById('edit-routine-btn').addEventListener('click', () => editRoutine());
    document.getElementById('add-sleep-btn').addEventListener('click', () => openSleepModal());

    // Journal pane
    document.getElementById('journal-prev-month').addEventListener('click', () => JournalPane.prevMonth());
    document.getElementById('journal-today').addEventListener('click', () => JournalPane.goToday());
    document.getElementById('journal-next-month').addEventListener('click', () => JournalPane.nextMonth());
    document.getElementById('journal-editor').addEventListener('focusout', () => updateJournal());

    // Todos pane
    document.querySelector('.todos-filters').addEventListener('click', e => {
        const btn = e.target.closest('.todo-filter[data-filter]');
        if (btn) { TodosPane.setFilter(btn.dataset.filter); return; }
        const dlBtn = e.target.closest('.todo-deadline-filter[data-deadline-filter]');
        if (dlBtn) TodosPane.setDeadlineFilter(dlBtn.dataset.deadlineFilter);
    });
    document.getElementById('todos-date-filter').addEventListener('change', e => {
        TodosPane.setDateFilter(e.target.value);
    });
    document.getElementById('todos-add-task-btn').addEventListener('click', () => Todo.showTodoModal());

    // Modal — Todo
    document.getElementById('todoSaveBtn').addEventListener('click', () => Todo.saveTodo());

    // Modal — Habit add
    document.getElementById('habit-save-btn').addEventListener('click', () => Habits.saveHabit());

    // Modal — Habit settings
    document.getElementById('habit-toggle-edit-btn').addEventListener('click', toggleEditForm);
    document.getElementById('habit-hallmark-btn').addEventListener('click', hallmarkHabit);
    document.getElementById('habit-delete-btn').addEventListener('click', deleteHabit);
    document.getElementById('habit-accountability-btn').addEventListener('click', togglePartnerSection);
    document.getElementById('assign-partner-btn').addEventListener('click', assignPartner);
    document.getElementById('habit-cancel-edit-btn').addEventListener('click', cancelEdit);
    document.getElementById('habit-save-changes-btn').addEventListener('click', saveHabitChanges);
    document.getElementById('partner-close-btn').addEventListener('click', togglePartnerSection);

    // Modal — Hallmark & Delete confirmation
    document.getElementById('hallmark-confirm-btn').addEventListener('click', confirmHallmark);
    document.getElementById('delete-confirm-btn').addEventListener('click', confirmDelete);

    // Modal — Sleep
    document.getElementById('save-sleep-btn').addEventListener('click', () => saveSleepEntry());

    // Modal — Routine editor
    document.getElementById('routine-add-row-btn').addEventListener('click', () => RoutineEditor.addRow());
    document.getElementById('routine-save-btn').addEventListener('click', () => RoutineEditor.save());

    // Modal — Reading list
    document.getElementById('rlDeleteBtn').addEventListener('click', () => ReadingList.deleteSelected());
    document.getElementById('reading-list-save-btn').addEventListener('click', () => ReadingList.save());

    // Modal — Group
    document.getElementById('group-save-btn').addEventListener('click', () => TodosPane.saveGroup());

    // Settings — general
    document.getElementById('themeSelect').addEventListener('change', () => Settings.changeTheme());
    document.getElementById('fontSelect').addEventListener('change', () => Settings.changeFont());
    document.getElementById('clockFormatSelect').addEventListener('change', () => Settings.changeClockFormat());
    document.getElementById('searchEngineSelect').addEventListener('change', () => Settings.changeSearchEngine());
    document.getElementById('sleepTimeInput').addEventListener('change', () => Settings.changeSleepTime());

    // Settings — pomodoro
    ['pomFocus', 'pomBreak', 'pomLongBreak', 'pomCycles'].forEach(id => {
        document.getElementById(id).addEventListener('change', () => Settings.savePomodoroSettings());
    });

    // Settings — sounds
    document.getElementById('soundPomodoro').addEventListener('change', () => Settings.saveSoundSettings());
    document.getElementById('soundNotifications').addEventListener('change', () => Settings.saveSoundSettings());
}


const General = {
    clockInterval: null,
    updateGreeting() {
        const now = new Date();
        const hour = now.getHours();
        let greeting, message = '';
        let greetings, messages;
        const G = AppConfig.dashboardConfig?.greetings || {};
        const M = AppConfig.dashboardConfig?.messages || {};
        if (hour < 4 || hour > 22) {
            greetings = G.night;
            messages = M.night;
        } else if (hour < 9) {
            greetings = G.morning;
            messages = M.morning;
        } else if (hour < 17) {
            greetings = G.afternoon;
            messages = M.afternoon;
        } else {
            greetings = G.evening;
            messages = M.evening;
        }

        if (!greetings?.length || !messages?.length) return;
        greeting = greetings[Math.floor(Math.random() * greetings.length)];
        message = messages[Math.floor(Math.random() * messages.length)];
        document.querySelector('.greeting-main h1').textContent = greeting;
        document.querySelector('.greeting-main p').textContent = message;
    },
    loadProductivityScore() {
        apiClient.get('board/api/productivity_score/').then(res => {
            if (res.status === 'success') {
                const data = res.data;
                const score = data.total;
                const pct = score / 10;

                document.getElementById('score-value').textContent = score;

                // Animate the SVG ring
                const circle = document.getElementById('score-circle');
                const circumference = 2 * Math.PI * 34;
                circle.style.strokeDasharray = circumference;
                circle.style.strokeDashoffset = circumference * (1 - pct);
            }
        });
    },
    startClock() {
        const update = () => {
            const now = new Date();
            const clockFormat = document.body.getAttribute('data-clock') || '12h';
            let timeStr;

            if (clockFormat === '24h') {
                timeStr = now.toLocaleTimeString('en-GB', {hour: '2-digit', minute: '2-digit', second: '2-digit'});
            } else {
                timeStr = now.toLocaleTimeString('en-US', {
                    hour: '2-digit',
                    minute: '2-digit',
                    second: '2-digit',
                    hour12: true
                });
            }

            const dateStr = now.toLocaleDateString('en-US', {
                weekday: 'short', year: 'numeric', month: 'short', day: 'numeric'
            });

            document.getElementById('home-datetime').innerHTML =
                `<span class="home-date">${dateStr}</span><span class="home-time">${timeStr}</span>`;
        };
        update();
        this.clockInterval = setInterval(update, 1000);
    }
}

// ── Onboarding ──
const Onboarding = {
    _total: 6,
    _current: 0,
    _modal: null,

    show() {
        this._modal = new bootstrap.Modal(document.getElementById('onboardingModal'));
        this._renderDots();
        this._goTo(0);
        this._modal.show();
    },

    _renderDots() {
        const el = document.getElementById('ob-dots');
        el.innerHTML = Array.from({length: this._total}, (_, i) =>
            `<span class="ob-dot" data-i="${i}" onclick="Onboarding._goTo(${i})"></span>`
        ).join('');
    },

    _goTo(i) {
        this._current = i;
        document.querySelectorAll('.ob-slide').forEach(s => s.classList.remove('active'));
        document.querySelectorAll('.ob-dot').forEach((d, idx) => d.classList.toggle('active', idx === i));
        const slide = document.querySelector(`.ob-slide[data-slide="${i}"]`);
        if (slide) slide.classList.add('active');
        document.getElementById('ob-prev').style.display = i === 0 ? 'none' : '';
        const nextBtn = document.getElementById('ob-next');
        if (i === this._total - 1) {
            nextBtn.innerHTML = 'Get Started <i class="fas fa-check ms-1"></i>';
        } else {
            nextBtn.innerHTML = 'Next <i class="fas fa-arrow-right ms-1"></i>';
        }
    },

    next() {
        if (this._current < this._total - 1) {
            this._goTo(this._current + 1);
        } else {
            this.complete();
        }
    },

    prev() {
        if (this._current > 0) this._goTo(this._current - 1);
    },

    complete() {
        apiClient.post('board/api/onboarding_complete/');
        if (AppConfig.userDetail) AppConfig.userDetail.is_onboarded = true;
        this._modal.hide();
    },
};

// ── Initialize ──
(function initDashboard() {
    bindEvents();

    const hash = window.location.hash.replace('#', '') || 'home';
    const validPanes = ['home', 'todos', 'trackers', 'journals', 'achievements', 'reading-list', 'friends', 'settings', 'help'];
    const initialPane = validPanes.includes(hash) ? hash : 'home';

    AppConfig.load().then(() => {
        currentTheme = AppConfig.userDetail?.default_theme || 'light';

        panesLoaded.home = true;
        initHomePane();

        if (initialPane !== 'home') {
            switchPane(initialPane);
        }

        document.dispatchEvent(new Event('appConfigLoaded'));
        BrowserNotify.updatePermissionUI();
        BrowserNotify.startTimelinePoller();

        if (!AppConfig.userDetail?.is_onboarded) {
            Onboarding.show();
        }
    });
}());

// Listen for hash changes
window.addEventListener('hashchange', function () {
    const hash = window.location.hash.replace('#', '') || 'home';
    const validPanes = ['home', 'todos', 'trackers', 'journals', 'achievements', 'reading-list', 'friends', 'settings', 'help'];
    if (validPanes.includes(hash)) {
        switchPane(hash);
    }
});

document.querySelectorAll('.form-input').forEach(input => {
    input.addEventListener('input', function() {
        this.style.width = this.value.length * 12 + 40 + 'px';
    });
});

document.getElementById('journal-editor').addEventListener('keyup', function(e) {
    let line_count = this.value.split('\n').length;
    let currentRows = parseInt(this.getAttribute('rows'));
    if (currentRows < line_count + 10) {
        this.setAttribute('rows', line_count + 10);
        window.scrollBy(0, 200)
    }else if (currentRows > line_count + 10) {
        this.setAttribute('rows', line_count + 10);
        window.scrollBy(0, -10)
    }
});

document.addEventListener('hide.bs.modal', function () {
    if (document.activeElement) {
        document.activeElement.blur();
    }
});

// ── Pull-to-Refresh (mobile only) ──
const PullToRefresh = {
    startY: 0,
    lastY: 0,
    pulling: false,
    refreshing: false,
    threshold: 75,
    indicator: null,

    init() {
        if (window.innerWidth > 1200) return;
        this.indicator = document.getElementById('ptr-indicator');
        document.querySelectorAll('.pane').forEach(pane => {
            pane.addEventListener('touchstart', e => this._onStart(e, pane), { passive: true });
            pane.addEventListener('touchmove', e => this._onMove(e, pane), { passive: false });
            pane.addEventListener('touchend', () => this._onEnd(), { passive: true });
        });
    },

    _onStart(e, pane) {
        if (this.refreshing) return;
        this.pulling = false;
        if (pane.scrollTop > 0) return;

        // Don't activate if the touch started inside a scrollable child element
        let el = e.target;
        while (el && el !== pane) {
            const ov = window.getComputedStyle(el).overflowY;
            if ((ov === 'auto' || ov === 'scroll') && el.scrollHeight > el.clientHeight) return;
            el = el.parentElement;
        }

        this.startY = e.touches[0].clientY;
        this.lastY = this.startY;
        this.pulling = true;
    },

    _onMove(e, pane) {
        if (!this.pulling || this.refreshing) return;
        this.lastY = e.touches[0].clientY;
        const delta = this.lastY - this.startY;
        if (delta <= 0 || pane.scrollTop > 0) { this.pulling = false; this._hide(); return; }
        e.preventDefault();
        const progress = Math.min(delta / this.threshold, 1);
        const translateY = Math.min(delta * 0.45, this.threshold * 0.6);
        const ind = this.indicator;
        if (!ind) return;
        ind.style.display = 'flex';
        ind.style.transition = 'none';
        ind.style.opacity = progress;
        ind.style.transform = `translateX(-50%) translateY(${translateY - 60}px)`;
        ind.querySelector('i').style.transform = `rotate(${progress * 180}deg)`;
    },

    _onEnd() {
        if (!this.pulling || this.refreshing) return;
        this.pulling = false;
        const delta = this.lastY - this.startY;
        if (delta >= this.threshold) {
            this._startRefresh();
        } else {
            this._hide();
        }
    },

    _startRefresh() {
        this.refreshing = true;
        const ind = this.indicator;
        if (ind) {
            const icon = ind.querySelector('i');
            icon.style.transform = '';
            icon.className = 'fas fa-circle-notch fa-spin';
            ind.style.transition = 'transform 0.25s ease, opacity 0.25s ease';
            ind.style.opacity = '1';
            ind.style.transform = 'translateX(-50%) translateY(0px)';
        }
        window.location.reload();
    },

    _hide() {
        const ind = this.indicator;
        if (!ind || ind.style.display === 'none') return;
        ind.style.transition = 'transform 0.25s ease, opacity 0.25s ease';
        ind.style.opacity = '0';
        ind.style.transform = 'translateX(-50%) translateY(-60px)';
        setTimeout(() => {
            ind.style.display = 'none';
            const icon = ind.querySelector('i');
            icon.className = 'fas fa-arrow-down';
            icon.style.transform = '';
        }, 260);
    },

    _reload() {
        switch (currentPane) {
            case 'home':
                General.loadProductivityScore();
                return Timeline.init();
            case 'todos':
                return Promise.all([TodosPane.loadTodos(), TodosPane.loadGroups()]);
            case 'trackers':
                loadHabits(); loadRoutines(); loadSleepAndJournalData();
                break;
            case 'journals':
                JournalPane.renderCalendar();
                break;
            case 'achievements':
                return MiscPane.loadAchievements();
            case 'reading-list':
                return ReadingList.loadAll();
            case 'friends':
                MiscPane.initFriends();
                break;
        }
    },
};

document.addEventListener('DOMContentLoaded', () => PullToRefresh.init());