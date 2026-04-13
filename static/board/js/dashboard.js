/**
 * dashboard.js — Main orchestrator
 * Handles pane switching, keyboard shortcuts, initialization
 */

let currentPane = 'home';
let panesLoaded = { home: false, todos: false, trackers: false, journals: false };
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

    currentPane = pane;
    window.location.hash = pane === 'home' ? '' : pane;

    // Lazy load pane data on first visit
    if (!panesLoaded[pane]) {
        panesLoaded[pane] = true;
        if (pane === 'home') initHomePane();
        else if (pane === 'trackers') initTrackersPane();
        else if (pane === 'journals') initJournalsPane();
        else if (pane === 'todos') initTodosPane();
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
    // Load search engines into settings dropdown
    Settings.loadSearchEngines();
    const modal = new bootstrap.Modal(document.getElementById('settingsModal'));
    modal.show();
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
    document.getElementById('tab-settings-btn').addEventListener('click', showSettings);

    // Navigation — mobile menu
    document.getElementById('hamburger-btn').addEventListener('click', toggleMobileMenu);
    document.getElementById('mobile-menu-overlay').addEventListener('click', closeMobileMenu);
    document.getElementById('mobile-menu-close-btn').addEventListener('click', closeMobileMenu);
    document.querySelectorAll('.mobile-menu-item[data-pane]').forEach(item => {
        item.addEventListener('click', () => { switchPane(item.dataset.pane); closeMobileMenu(); });
    });
    document.getElementById('mobile-theme-btn').addEventListener('click', () => { toggleTheme(); closeMobileMenu(); });
    document.getElementById('mobile-settings-btn').addEventListener('click', () => { showSettings(); closeMobileMenu(); });

    // Pomodoro
    document.getElementById('pomodoro-start').addEventListener('click', () => Pomodoro.toggle());
    document.getElementById('pomodoro-reset').addEventListener('click', () => Pomodoro.reset());
    document.getElementById('pomodoro-toggle-mode').addEventListener('click', () => Pomodoro.toggleMode());

    // Search
    document.getElementById('search-engine-btn').addEventListener('click', toggleSearchEngineDropdown);
    document.getElementById('search-input').addEventListener('keydown', e => {
        if (e.key === 'Enter') { e.preventDefault(); DefaultPane.doSearch(); }
    });

    // Home — habits & routines & sleep
    document.getElementById('new-habit-btn').addEventListener('click', () => Habits.showHabitModal());
    document.getElementById('workday_routine_button').addEventListener('click', () => showRoutine('workday'));
    document.getElementById('holiday_routine_button').addEventListener('click', () => showRoutine('holiday'));
    document.getElementById('edit-routine-btn').addEventListener('click', editRoutine);
    document.getElementById('add-sleep-btn').addEventListener('click', openSleepModal);

    // Journal pane
    document.getElementById('journal-prev-month').addEventListener('click', () => JournalPane.prevMonth());
    document.getElementById('journal-today').addEventListener('click', () => JournalPane.goToday());
    document.getElementById('journal-next-month').addEventListener('click', () => JournalPane.nextMonth());
    document.getElementById('journal-editor').addEventListener('focusout', updateJournal);

    // Todos pane
    document.querySelector('.todos-filters').addEventListener('click', e => {
        const btn = e.target.closest('.todo-filter[data-filter]');
        if (btn) TodosPane.setFilter(btn.dataset.filter);
    });
    document.getElementById('todos-add-task-btn').addEventListener('click', () => TodosPane.addTask());

    // Modal — Todo
    document.getElementById('todoSaveBtn').addEventListener('click', () => Todo.saveTodo());

    // Modal — Habit add
    document.getElementById('habit-save-btn').addEventListener('click', () => Habits.saveHabit());

    // Modal — Habit settings
    document.getElementById('habit-toggle-edit-btn').addEventListener('click', toggleEditForm);
    document.getElementById('habit-hallmark-btn').addEventListener('click', hallmarkHabit);
    document.getElementById('habit-delete-btn').addEventListener('click', deleteHabit);
    document.getElementById('assign-partner-btn').addEventListener('click', assignPartner);
    document.getElementById('habit-cancel-edit-btn').addEventListener('click', cancelEdit);
    document.getElementById('habit-save-changes-btn').addEventListener('click', saveHabitChanges);
    document.getElementById('partner-cancel-btn').addEventListener('click', cancelPartnerEdit);
    document.getElementById('partner-save-btn').addEventListener('click', savePartnerSettings);

    // Modal — Hallmark & Delete confirmation
    document.getElementById('hallmark-confirm-btn').addEventListener('click', confirmHallmark);
    document.getElementById('delete-confirm-btn').addEventListener('click', confirmDelete);

    // Modal — Sleep
    document.getElementById('save-sleep-btn').addEventListener('click', saveSleepEntry);

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

// ── Initialize ──
document.addEventListener('DOMContentLoaded', function () {
    bindEvents();

    // Set year
    document.getElementById('year').innerText = new Date().getFullYear();

    const hash = window.location.hash.replace('#', '') || 'home';
    const validPanes = ['home', 'todos', 'trackers', 'journals'];
    const initialPane = validPanes.includes(hash) ? hash : 'home';

    AppConfig.load().then(() => {
        currentTheme = AppConfig.userDetail?.default_theme || 'light';

        panesLoaded.home = true;
        initHomePane();

        if (initialPane !== 'home') {
            switchPane(initialPane);
        }
    });
});

// Listen for hash changes
window.addEventListener('hashchange', function () {
    const hash = window.location.hash.replace('#', '') || 'home';
    const validPanes = ['home', 'todos', 'trackers', 'journals'];
    if (validPanes.includes(hash) && hash !== currentPane) {
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