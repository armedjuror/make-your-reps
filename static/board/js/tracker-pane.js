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
    initSleepChart();
    loadSleepAndJournalData();

    // Auto-select routine based on day
    const today = new Date().getDay();
    if (today === 0 || today === 6) {
        document.getElementById('holiday_routine_button').click();
    } else {
        document.getElementById('workday_routine_button').click();
    }
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
                return `<div class="routine-item"><strong>${timeStr}</strong> — ${entry.title}</div>`;
            }).join('');
        } else {
            container.innerHTML = '<h6 class="text-center mt-4 mb-4">No routine set. Click Edit to add one.</h6>';
        }
    });
}

// ── Routine Editor ──

const RoutineEditor = {
    addRow() {
        const container = document.getElementById('routineEntries');
        const row = document.createElement('div');
        row.className = 'routine-entry-row d-flex gap-2 mb-2 align-items-center';
        row.innerHTML = `
            <input type="time" class="form-control routine-time" style="width:130px;">
            <input type="text" class="form-control routine-title" placeholder="Activity name">
            <button class="btn btn-paper btn-danger btn-sm" onclick="this.parentElement.remove()"><i class="fas fa-times"></i></button>
        `;
        container.appendChild(row);
    },

    save() {
        const rows = document.querySelectorAll('#routineEntries .routine-entry-row');
        const entries = [];
        rows.forEach(row => {
            const time = row.querySelector('.routine-time').value;
            const title = row.querySelector('.routine-title').value.trim();
            if (time && title) {
                entries.push({ time, title });
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
            res.data.forEach(entry => {
                const row = document.createElement('div');
                row.className = 'routine-entry-row d-flex gap-2 mb-2 align-items-center';
                row.innerHTML = `
                    <input type="time" class="form-control routine-time" style="width:130px;" value="${entry.time.substring(0, 5)}">
                    <input type="text" class="form-control routine-title" placeholder="Activity name" value="${entry.title}">
                    <button class="btn btn-paper btn-danger btn-sm" onclick="this.parentElement.remove()"><i class="fas fa-times"></i></button>
                `;
                container.appendChild(row);
            });
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
        } else {
            showError(res.error || 'Failed to save sleep entry');
        }
    });
}