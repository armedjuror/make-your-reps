/**
 * journals-pane.js — Journal editor + calendar navigation
 */

const JournalPane = {
    currentYear: new Date().getFullYear(),
    currentMonth: new Date().getMonth(), // 0-indexed
    journalData: {}, // { 'YYYY-MM-DD': { journal: '...', sleep_hours: N } }

    init() {
        this.currentYear = new Date().getFullYear();
        this.currentMonth = new Date().getMonth();
        this.loadMonthData();
        this.loadTodayJournal();
    },

    prevMonth() {
        this.currentMonth--;
        if (this.currentMonth < 0) {
            this.currentMonth = 11;
            this.currentYear--;
        }
        this.loadMonthData();
    },

    nextMonth() {
        this.currentMonth++;
        if (this.currentMonth > 11) {
            this.currentMonth = 0;
            this.currentYear++;
        }
        this.loadMonthData();
    },

    goToday() {
        this.currentYear = new Date().getFullYear();
        this.currentMonth = new Date().getMonth();
        this.loadMonthData();
    },

    async loadMonthData() {
        const year = this.currentYear;
        const month = this.currentMonth + 1; // 1-indexed for API
        const daysInMonth = new Date(year, month, 0).getDate();

        const startDate = `${year}-${String(month).padStart(2, '0')}-01`;
        const endDate = `${year}-${String(month).padStart(2, '0')}-${String(daysInMonth).padStart(2, '0')}`;

        const res = await apiClient.get(`board/api/daily_data/?start_date=${startDate}&end_date=${endDate}`);

        this.journalData = {};
        if (res.status === 'success') {
            for (const entry of res.data) {
                this.journalData[entry.date] = {
                    journal: entry.journal || '',
                    sleep_hours: entry.sleep_hours
                };
            }
        }

        this.renderCalendar();
    },

    async loadTodayJournal() {
        const today = getDate(new Date());
        const res = await apiClient.get(`board/api/daily_data/${today}/`);
        if (res.status === 'success') {
            const editor = document.getElementById('journal-editor');
            if (editor) editor.value = res.data.journal || '';
        }
    },

    renderCalendar() {
        const year = this.currentYear;
        const month = this.currentMonth;
        const today = new Date();
        const todayStr = getDate(today);

        // Update title
        const monthNames = ['January', 'February', 'March', 'April', 'May', 'June',
            'July', 'August', 'September', 'October', 'November', 'December'];
        const titleEl = document.getElementById('journal-month-title');
        if (titleEl) titleEl.textContent = `${monthNames[month]} ${year}`;

        const grid = document.getElementById('journal-calendar-grid');
        if (!grid) return;

        // Day headers
        const dayHeaders = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
        let html = dayHeaders.map(d => `<div class="calendar-header-cell">${d}</div>`).join('');

        // First day of month
        const firstDay = new Date(year, month, 1).getDay();
        const daysInMonth = new Date(year, month + 1, 0).getDate();
        const daysInPrevMonth = new Date(year, month, 0).getDate();

        // Previous month padding
        for (let i = firstDay - 1; i >= 0; i--) {
            const day = daysInPrevMonth - i;
            html += `<div class="calendar-day other-month"><div class="calendar-day-number">${day}</div></div>`;
        }

        // Current month days
        for (let d = 1; d <= daysInMonth; d++) {
            const dateStr = `${year}-${String(month + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
            const isToday = dateStr === todayStr;
            const data = this.journalData[dateStr];
            const hasJournal = data && data.journal && data.journal.trim().length > 0;
            const preview = hasJournal ? data.journal.substring(0, 40) : '';

            let classes = 'calendar-day';
            if (isToday) classes += ' today';
            if (hasJournal) classes += ' has-journal';

            html += `
                <div class="${classes}" onclick="JournalPane.openDay('${dateStr}')">
                    <div class="calendar-day-number">${d}</div>
                    <div class="calendar-day-preview">${preview}</div>
                </div>
            `;
        }

        // Next month padding
        const totalCells = firstDay + daysInMonth;
        const remaining = totalCells % 7 === 0 ? 0 : 7 - (totalCells % 7);
        for (let i = 1; i <= remaining; i++) {
            html += `<div class="calendar-day other-month"><div class="calendar-day-number">${i}</div></div>`;
        }

        grid.innerHTML = html;
    },

    openDay(dateStr) {
        const data = this.journalData[dateStr];
        const editor = document.getElementById('journal-editor');
        if (editor) {
            editor.value = data ? (data.journal || '') : '';
            editor.setAttribute('data-date', dateStr);
            editor.focus();
        }
        const titleEl = document.getElementById('journal-editor-title');
        if (titleEl) {
            const today = getDate(new Date());
            if (dateStr === today) {
                titleEl.textContent = "Today's Journal";
            } else {
                const [year, month, day] = dateStr.split('-');
                const date = new Date(year, month - 1, day);
                const formatted = date.toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' });
                titleEl.textContent = `${formatted}'s Journal`;
            }
        }
    }
};

function updateJournal() {
    const editor = document.getElementById('journal-editor');
    if (!editor) return;

    const customDate = editor.getAttribute('data-date');
    const dateStr = customDate || getDate(new Date());
    const journal = editor.value;

    const statusEl = document.getElementById('journal-save-status');

    apiClient.put(`board/api/daily_data/${dateStr}/`, { journal }, { silent: true }).then(res => {
        if (res.status === 'success') {
            // Update in-memory cache so navigating back to this day shows updated content
            if (!JournalPane.journalData[dateStr]) JournalPane.journalData[dateStr] = {};
            JournalPane.journalData[dateStr].journal = journal;
            JournalPane.renderCalendar();
            if (statusEl) {
                statusEl.textContent = 'Saved';
                statusEl.className = 'journal-save-status saved';
                setTimeout(() => { statusEl.textContent = ''; statusEl.className = 'journal-save-status'; }, 2000);
            }
        } else if (res.error && res.error.toLowerCase().includes('network')) {
            if (statusEl) {
                statusEl.textContent = 'Not saved — check connection';
                statusEl.className = 'journal-save-status unsaved';
            }
        } else {
            showError(res.error);
        }
    });
}

function initJournalsPane() {
    JournalPane.init();
}