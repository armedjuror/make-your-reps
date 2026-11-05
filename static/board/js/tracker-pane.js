/**
 * trackers-pane.js — Todo, Habit, Routine, Sleep tracker logic
 */

let todos = [];
let todoErrorMessage = 'Clean Slate, Nothing to do :)';
let currentRoutineType = 'workday';
let sleepData = {};
let currentHabitData = {};
let sleepChart = null;

function initTrackersPane() {
    loadHabits();
    loadRoutines();
    Trackers.init();
    loadSleepAndJournalData();

    // Auto-select the routine from today's day template (weekend days are configurable)
    const tpl = (typeof Resilient !== 'undefined' && Resilient.day && Resilient.day.template) || 'workday';
    document.getElementById(tpl === 'holiday' ? 'holiday_routine_button' : 'workday_routine_button').click();
}


function showRoutine(type) {
    currentRoutineType = type;
    document.querySelectorAll('.routine-tab').forEach(t => t.classList.remove('active'));
    event.target.classList.add('active');
    loadRoutines();
}

function loadRoutines() {
    apiClient.get(`board/api/routine_entries/?type=${currentRoutineType}`).then(res => {
        const container = document.getElementById('routine-list');
        if (!container) return;
        if (res.status === 'success' && res.data.length > 0) {
            const clockFormat = document.body.getAttribute('data-clock') || '12h';
            container.innerHTML = res.data.map(entry => {
                let timeStr;
                if (clockFormat === '24h') {
                    timeStr = entry.time.substring(0, 5);
                } else {
                    const [h, m] = entry.time.split(':');
                    const hour = parseInt(h);
                    const ampm = hour >= 12 ? 'PM' : 'AM';
                    const h12 = hour % 12 || 12;
                    timeStr = `${h12}:${m} ${ampm}`;
                }
                const tier = entry.tier && entry.tier !== 'flexible' ? ` <small class="rs-tier">${esc(entry.tier)}</small>` : '';
                return `<div class="routine-item"><strong>${timeStr}</strong> — ${esc(entry.title)}${tier}</div>`;
            }).join('');
        } else {
            container.innerHTML = '<h6 class="text-center mt-4 mb-4">No routine set. Click Edit to add one.</h6>';
        }
    });
}

// ── Routine Editor ──

const RoutineEditor = {
    /** One editor row; `entry` carries id, time, title, tier, fixed_time, duration_min when editing. */
    addRow(entry = {}) {
        const container = document.getElementById('routineEntries');
        const row = document.createElement('div');
        if (entry.id) row.dataset.id = entry.id;
        const tier = entry.tier || 'flexible';
        const opt = (v, l, cur) => `<option value="${v}" ${cur === v ? 'selected' : ''}>${l}</option>`;
        row.className = 'routine-entry-row convo-line';
        row.innerHTML = `
            At <input type="time" class="form-input routine-time" value="${esc((entry.time || '').substring(0, 5))}">
            I <input type="text" class="form-input routine-title" placeholder="do DSA" value="${esc(entry.title || '')}">,
            it&rsquo;s <select class="form-input routine-tier">${opt('essential', 'essential', tier)}${opt('anchor', 'an anchor', tier)}${opt('flexible', 'flexible', tier)}</select>
            and <select class="form-input routine-fixed">${opt('', 'moves when I&rsquo;m late', entry.fixed_time ? 'fixed' : '')}${opt('fixed', 'stays fixed', entry.fixed_time ? 'fixed' : '')}</select>,
            for <input type="number" min="1" max="720" class="form-input rs-num routine-duration" placeholder="until next" value="${esc(entry.duration_min || '')}"> min
            <button type="button" class="tl-link routine-remove ms-2">remove</button>
        `;
        row.querySelector('.routine-remove').addEventListener('click', () => row.remove());
        container.appendChild(row);
    },

    save() {
        const rows = document.querySelectorAll('#routineEntries .routine-entry-row');
        const entries = [];
        rows.forEach(row => {
            const time = row.querySelector('.routine-time').value;
            const title = row.querySelector('.routine-title').value.trim();
            if (time && title) {
                const item = {
                    time, title,
                    tier: row.querySelector('.routine-tier').value,
                    fixed_time: row.querySelector('.routine-fixed').value === 'fixed',
                    duration_min: row.querySelector('.routine-duration').value
                        ? Number(row.querySelector('.routine-duration').value) : null,
                };
                if (row.dataset.id) item.id = Number(row.dataset.id);
                entries.push(item);
            }
        });

        apiClient.post('board/api/routine_entries/bulk_create/', {
            routine_type: currentRoutineType,
            entries
        }).then(res => {
            if (res.status === 'success') {
                bootstrap.Modal.getInstance(document.getElementById('routineModal')).hide();
                loadRoutines();
                showSuccess(res.message || 'Routine saved!');
            } else {
                showError(res.error);
            }
        });
    }
};

function editRoutine() {
    // Load current entries into modal
    apiClient.get(`board/api/routine_entries/?type=${currentRoutineType}`).then(res => {
        const container = document.getElementById('routineEntries');
        container.innerHTML = '';

        if (res.status === 'success' && res.data.length > 0) {
            res.data.forEach(entry => RoutineEditor.addRow(entry));
        } else {
            // Add a blank row
            RoutineEditor.addRow();
        }

        new bootstrap.Modal(document.getElementById('routineModal')).show();
    });
}

// ── Sleep Tracker ──

function initSleepChart() {
    const canvas = document.getElementById('sleepChart');
    if (!canvas) return;

    const inkBrown = getComputedStyle(document.body).getPropertyValue('--ink-brown').trim() || 'rgb(142,110,58)';
    const inkBrownLight = getComputedStyle(document.body).getPropertyValue('--ink-brown-light').trim() || 'rgba(184,156,125,0.25)';

    sleepChart = new Chart(canvas, {
        type: 'line',
        data: {
            datasets: [{
                data: sleepData,
                borderColor: inkBrown,
                backgroundColor: inkBrownLight,
                borderWidth: 2,
                pointRadius: 5,
                pointHoverRadius: 10,
                pointBackgroundColor: inkBrown,
                pointBorderColor: 'transparent',
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: {duration:400},
            plugins: {
                legend: { display: false },
                tooltip: {
                    xAlign: 'center',
                    yAlign: 'bottom',
                    callbacks: {
                        title: ctx => {
                            const raw = ctx[0]?.label || '';
                            const dt = new Date(raw + 'T00:00:00');
                            return dt.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
                        },
                        label: ctx => `Sleep: ${ctx.parsed.y} hrs`
                    }
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    max: 12,
                    ticks: { stepSize: 2, color: inkBrown, font: { size: 9 } },
                    grid: { color: inkBrownLight },
                    border: { display: false },
                },
                x: {
                    ticks: { display: false },
                    grid: { display: false },
                    border: { display: false },
                }
            }
        }
    });
}

function loadSleepAndJournalData() {
    const today = new Date();
    const twoWeeksAgo = new Date(today);
    twoWeeksAgo.setDate(twoWeeksAgo.getDate() - 14);

    apiClient.get(`board/api/daily_data/?start_date=${getDate(twoWeeksAgo)}&end_date=${getDate(today)}`).then(res => {
        if (res.status === 'success') {
            sleepData = {};
            for (const entry of res.data) {
                sleepData[entry.date] = entry.sleep_hours ? parseFloat(entry.sleep_hours) : 0;
                if (entry.date === getDate(today)) {
                    const journalEditor = document.getElementById('journal-editor');
                    if (journalEditor) journalEditor.value = entry.journal || '';
                }
            }
            if (sleepChart) {
                sleepChart.data.datasets[0].data = sleepData;
                sleepChart.update();
            }
        }
    });
}

function openSleepModal() {
    document.getElementById('sleepDate').value = getDate(new Date());
    document.getElementById('sleepHours').value = '';
    new bootstrap.Modal(document.getElementById('sleepModal')).show();
}

function saveSleepEntry() {
    const dateStr = document.getElementById('sleepDate').value;
    const hours = parseFloat(document.getElementById('sleepHours').value);

    if (!dateStr || isNaN(hours) || hours < 0 || hours > 24) {
        showError('Please enter a valid date and hours (0-24)');
        return;
    }

    apiClient.put(`board/api/daily_data/${dateStr}/`, { sleep_hours: hours }).then(res => {
        if (res.status === 'success') {
            bootstrap.Modal.getInstance(document.getElementById('sleepModal')).hide();
            showSuccess('Sleep entry saved!');
            sleepData[dateStr] = hours;
            if (sleepChart) {
                sleepChart.data.datasets[0].data = { ...sleepData };
                sleepChart.update();
            }
            General.loadProductivityScore();
            if (typeof Resilient !== 'undefined') Resilient.loadMetrics();
        } else {
            showError(res.error || 'Failed to save sleep entry');
        }
    });
}