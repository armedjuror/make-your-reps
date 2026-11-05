/**
 * gamification.js — Points, levels, streaks, achievements UI
 */

const Gamification = {
    data: null,

    async load() {
        const res = await apiClient.get('board/api/gamification/');
        if (res.status !== 'success') return;
        this.data = res.data;
        this.renderStatusBar();
    },

    renderStatusBar() {
        if (!this.data) return;
        const d = this.data;
        const s = document.getElementById('gami-streak');
        const ln = document.getElementById('gami-level-name');
        const pts = document.getElementById('gami-points');
        const fill = document.getElementById('gami-xp-fill');
        if (s) s.textContent = d.current_streak;
        if (ln) ln.textContent = d.level_name;
        if (pts) pts.textContent = d.total_points.toLocaleString();
        if (fill) fill.style.width = d.xp_pct + '%';
    },

    async loadHallmarkedHabits() {
        const el = document.getElementById('hallmarked-habits-list');
        if (!el) return;
        const res = await apiClient.get('board/api/habits/?status=completed');
        if (res.status !== 'success') { el.innerHTML = '<p class="text-muted small">Could not load.</p>'; return; }
        const habits = res.data;
        this._hallmarks = habits;
        if (habits.length === 0) {
            el.innerHTML = '<p class="small" style="color:var(--ink-gray);opacity:0.6;">No hallmarked habits yet. Keep building!</p>';
            return;
        }
        el.innerHTML = `<div class="hallmark-chips">${habits.map(h => `
            <div class="hallmark-chip">
                <button type="button" class="sp-share-btn sp-share-corner" data-share="hallmark" data-habit-id="${h.id}" title="Share this habit" aria-label="Share this habit"><i class="fas fa-share-nodes"></i></button>
                <i class="fas fa-award hallmark-chip-icon"></i>
                <div class="hallmark-chip-body">
                    <div class="hallmark-chip-name">Your habit to <h6>${h.habit}</h6> inorder to become <h6>${h.identity}</h6> if formed!</div>
                    <div class="hallmark-chip-meta">${h.stats.total_reps} reps · Best streak: ${h.stats.max_streak}</div>
                </div>
            </div>`).join('')}
        </div>`;
    },

    async loadProductivityHistory() {
        const wrap = document.querySelector('.ach-score-chart-wrap');
        const cached = localStorage.getItem('prod_history_cache');

        // Render from cache immediately if wrap is visible
        if (wrap) {
            if (cached) {
                wrap.innerHTML = '<canvas id="productivityScoreChart"></canvas>';
                this.renderProductivityChart(JSON.parse(cached));
            } else {
                wrap.innerHTML = '<div class="notebook-spinner"></div>';
            }
        }

        // Always fetch fresh and update cache + chart
        const res = await apiClient.get('board/api/productivity_score_history/?days=30');
        if (res.status !== 'success') return;
        localStorage.setItem('prod_history_cache', JSON.stringify(res.data));

        if (wrap) {
            wrap.innerHTML = '<canvas id="productivityScoreChart"></canvas>';
            this.renderProductivityChart(res.data);
        }
    },

    renderProductivityChart(history) {
        const canvas = document.getElementById('productivityScoreChart');
        if (!canvas) return;
        this._history = history;
        const shareable = (i) => history[i] && history[i].score >= 7;

        const labels = history.map(d => {
            const dt = new Date(d.date + 'T00:00:00');
            return dt.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
        });
        const scores = history.map(d => d.score);

        const inkBrown = getComputedStyle(document.body).getPropertyValue('--ink-brown').trim() || '#9875a0';
        const inkBrownLight = getComputedStyle(document.body).getPropertyValue('--ink-brown-light').trim() || 'rgba(184,156,125,0.3)';

        if (this._scoreChart) {
            this._scoreChart.destroy();
            this._scoreChart = null;
        }

        this._scoreChart = new Chart(canvas, {
            type: 'bar',
            data: {
                labels,
                datasets: [{
                    data: scores,
                    backgroundColor: scores.map(s => s >= 7 ? inkBrown : inkBrownLight),
                    borderColor: 'transparent',
                    borderRadius: 4,
                    borderSkipped: false,
                }]
            },
            options: {
                responsive: true,
                animation: { duration: 400 },
                maintainAspectRatio: false,
                onHover: (evt, els) => {
                    const on = els.length > 0 && shareable(els[0].index);
                    if (evt.native && evt.native.target) evt.native.target.style.cursor = on ? 'pointer' : 'default';
                },
                onClick: (evt, els) => {
                    if (els.length && shareable(els[0].index)) this.shareDay(history[els[0].index]);
                },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        xAlign: 'center',
                        yAlign: 'bottom',
                        callbacks: {
                            title: ctx => ctx[0]?.label || '',
                            label: ctx => `Score: ${ctx.parsed.y} / 10`
                        }
                    }
                },
                scales: {
                    y: {
                        min: 0, max: 10,
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
    },

    renderAchievementsTab() {
        if (!this.data) return;
        const d = this.data;

        document.getElementById('ach-level-name').textContent = d.level_name;
        document.getElementById('ach-level-num').textContent = d.level;
        document.getElementById('ach-xp-fill').style.width = d.xp_pct + '%';
        document.getElementById('ach-xp-label').textContent = `${d.xp_in_level.toLocaleString()} / ${d.xp_needed.toLocaleString()} XP`;
        document.getElementById('ach-streak').textContent = d.current_streak;
        document.getElementById('ach-longest-streak').textContent = d.longest_streak;
        document.getElementById('ach-points').textContent = d.total_points.toLocaleString();
        document.getElementById('ach-unlocked').textContent = d.unlocked_count;
        document.getElementById('ach-total').textContent = d.total_count;

        // Group badges by category
        const categories = {};
        for (const a of d.achievements) {
            if (!categories[a.category]) categories[a.category] = [];
            categories[a.category].push(a);
        }

        const categoryLabels = {
            habits: 'Habits', focus: 'Focus', todos: 'Tasks',
            journal: 'Journal', sleep: 'Sleep', social: 'Social',
            streak: 'Daily Streak', meta: 'Meta',
        };

        let html = '';
        for (const [cat, items] of Object.entries(categories)) {
            html += `<div class="ach-category mb-4">
                <h5 class="ach-category-title">${categoryLabels[cat] || cat}</h5>
                <div class="ach-badge-grid">
                    ${items.map(a => this._badgeHTML(a)).join('')}
                </div>
            </div>`;
        }
        document.getElementById('achievements-grid').innerHTML = html;
    },

    _badgeHTML(a) {
        const cls = a.unlocked ? 'ach-badge unlocked' : 'ach-badge locked';
        const dateStr = a.unlocked_at ? new Date(a.unlocked_at).toLocaleDateString('en-US', {month: 'short', day: 'numeric', year: 'numeric'}) : '';
        return `
            <div class="${cls}" title="${a.description}">
                ${a.unlocked ? `<button type="button" class="sp-share-btn sp-share-corner" data-share="achievement" data-key="${a.key}" title="Share this badge" aria-label="Share this badge"><i class="fas fa-share-nodes"></i></button>` : ''}
                <div class="ach-badge-icon"><i class="${a.icon}"></i></div>
                <div class="ach-badge-name">${a.name}</div>
                <div class="ach-badge-desc">${a.description}</div>
                ${a.unlocked ? `<div class="ach-badge-date">Achieved on <br>${dateStr}</div>` : ``}
            </div>`;
    },

    // Called after any action that returns gamification data
    handleResult(result) {
        if (!result) return;
        if (result.points_awarded) {
            this.showFloatingPoints(result.points_awarded);
            if (result.points_awarded > 0 && typeof Theme !== 'undefined') Theme.celebrate(result.points_awarded);
        }
        if (result.new_achievements && result.new_achievements.length > 0) {
            this.showAchievementToasts(result.new_achievements);
        }
        // Refresh status bar
        this.load();
    },

    // ───────────── Share the victory ─────────────

    _dateLabel(iso) {
        const d = iso ? new Date(iso.length <= 10 ? iso + 'T00:00:00' : iso) : new Date();
        return d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' });
    },

    achievementSpec(a) {
        return {
            kind: 'achievement', tag: a.key,
            label: 'Achievement unlocked', title: a.name, subtitle: a.description, icon: a.icon,
            stats: this.data ? [`Level ${this.data.level}`, `${this.data.current_streak}-day streak`] : [],
            dateLabel: this._dateLabel(a.unlocked_at),
            shareText: `I just unlocked "${a.name}" on Make Your Reps.`,
        };
    },

    daySpec(date, d) {
        const b = d.breakdown || {};
        const perfect = d.total >= 10;
        const stats = [];
        if (b.habits_due || b.habits_done) stats.push(`${b.habits_done}/${Math.max(b.habits_due, b.habits_done)} habits`);
        if (b.todos_due || b.todos_done) stats.push(`${b.todos_done} task${b.todos_done === 1 ? '' : 's'} done`);
        if (b.journaled) stats.push('Journaled');
        if (b.sleep_logged) stats.push('Sleep logged');
        return {
            kind: perfect ? 'perfect_day' : 'day_score', tag: date,
            label: perfect ? 'Perfect day' : 'Productivity score',
            title: `${d.total}/10`,
            subtitle: perfect ? 'Every rep counted today.' : 'Another day of showing up.',
            icon: perfect ? 'fas fa-crown' : 'fas fa-chart-line',
            stats, dateLabel: this._dateLabel(date),
            shareText: perfect ? 'A perfect 10/10 day on Make Your Reps.' : `Scored ${d.total}/10 today on Make Your Reps.`,
        };
    },

    async dayData(date) {
        const res = await apiClient.get(`board/api/productivity_score/?date=${date}`, { silent: true });
        return res && res.status === 'success' ? res.data : null;
    },

    async shareDay(point) {
        if (typeof SharePoster === 'undefined' || !point) return;
        const d = await this.dayData(point.date);
        SharePoster.open(this.daySpec(point.date, d || { total: point.score, breakdown: {} }));
    },

    streakSpec() {
        const d = this.data;
        return {
            kind: 'streak', tag: String(d.current_streak),
            label: 'Day streak', title: String(d.current_streak),
            subtitle: d.current_streak === 1 ? 'day in a row, and counting.' : 'days in a row, and counting.',
            icon: 'fas fa-fire', stats: [`Best: ${d.longest_streak} days`, `Level ${d.level}`],
            shareText: `${d.current_streak}-day streak on Make Your Reps.`,
        };
    },

    levelSpec() {
        const d = this.data;
        return {
            kind: 'level', tag: String(d.level),
            label: `Level ${d.level}`, title: d.level_name,
            subtitle: `${d.total_points.toLocaleString()} points earned`,
            icon: 'fas fa-bolt', stats: [`${d.unlocked_count}/${d.total_count} badges`, `${d.current_streak}-day streak`],
            shareText: `I'm a "${d.level_name}" (level ${d.level}) on Make Your Reps.`,
        };
    },

    hallmarkSpec(h) {
        const st = h.stats || {};
        return {
            kind: 'hallmark', tag: String(h.id),
            label: 'Habit formed', title: h.habit,
            subtitle: h.identity ? `Becoming ${h.identity}` : '',
            icon: 'fas fa-award',
            stats: [`${st.total_reps || 0} reps`, `Best streak ${st.max_streak || 0}`],
            shareText: `I formed a habit on Make Your Reps: ${h.habit}.`,
        };
    },

    async celebrateAchievements(list) {
        await this.load();                       // refresh so descriptions and level are current
        for (const a of list) {
            const full = (this.data && this.data.achievements || []).find(x => x.key === a.key) || a;
            SharePoster.celebrate(this.achievementSpec({ ...full, unlocked_at: new Date().toISOString() }), {
                heading: 'Achievement unlocked!',
                message: `You earned "${a.name}"${a.points ? ` (+${a.points} pts)` : ''}. Show it off?`,
            });
        }
    },

    /** Called with today's score: congratulate (once per day) on a real 10/10. */
    checkPerfectDay(score) {
        if (typeof SharePoster === 'undefined' || !score || score.total < 10) return;
        const b = score.breakdown || {};
        if (!(b.habits_done > 0 || b.todos_done > 0)) return;   // a 10 earned by doing nothing isn't a win
        const today = new Date();
        const key = `mr_perfect_day_${today.getFullYear()}-${today.getMonth() + 1}-${today.getDate()}`;
        try { if (localStorage.getItem(key)) return; localStorage.setItem(key, '1'); } catch (e) { /* show anyway */ }
        const iso = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;
        SharePoster.celebrate(this.daySpec(iso, score), {
            heading: 'A perfect 10/10 day!',
            message: 'Habits, tasks, journal and sleep, all done. That deserves a poster.',
        });
    },

    bindShareClicks() {
        if (this._shareBound) return;
        this._shareBound = true;
        document.addEventListener('click', (e) => {
            const btn = e.target.closest('[data-share]');
            if (!btn || typeof SharePoster === 'undefined') return;
            e.preventDefault(); e.stopPropagation();
            const kind = btn.dataset.share;
            if (kind === 'achievement') {
                const a = (this.data && this.data.achievements || []).find(x => x.key === btn.dataset.key);
                if (a) SharePoster.open(this.achievementSpec(a));
            } else if (kind === 'streak' && this.data) {
                SharePoster.open(this.streakSpec());
            } else if (kind === 'level' && this.data) {
                SharePoster.open(this.levelSpec());
            } else if (kind === 'hallmark') {
                const h = (this._hallmarks || []).find(x => String(x.id) === btn.dataset.habitId);
                if (h) SharePoster.open(this.hallmarkSpec(h));
            }
        });
    },

    showFloatingPoints(pts) {
        const container = document.getElementById('gami-float-container');
        const el = document.createElement('div');
        el.className = 'gami-float-pts';
        el.textContent = pts > 0 ? `+${pts} pts` : `${pts} pts`;
        if (pts < 0) el.classList.add('gami-float-pts-neg');
        el.style.left = (window.innerWidth / 2 - 30) + 'px';
        el.style.top = '120px';
        container.appendChild(el);
        setTimeout(() => el.remove(), 1600);
    },

    showAchievementToasts(achievements) {
        if (typeof SharePoster !== 'undefined') { this.celebrateAchievements(achievements); return; }
        let delay = 0;
        for (const a of achievements) {
            setTimeout(() => this._showOneToast(a), delay);
            delay += 3500;
        }
    },

    _showOneToast(a) {
        const toast = document.getElementById('gami-achievement-toast');
        document.getElementById('gami-toast-name').innerHTML = `<i class="${a.icon} me-1"></i>${a.name}`;
        toast.style.display = 'flex';
        toast.classList.add('visible');
        setTimeout(() => {
            toast.classList.remove('visible');
            setTimeout(() => { toast.style.display = 'none'; }, 400);
        }, 3000);
    },
};

// Patch apiClient responses to intercept gamification data
(function patchGamification() {
    const _origToggle = window._habitToggleCallback;

    // We hook via event dispatch from existing JS files
    document.addEventListener('gamification', (e) => {
        Gamification.handleResult(e.detail);
    });
    Gamification.bindShareClicks();
})();

// Initialize on DOMContentLoaded (after AppConfig loads)
document.addEventListener('DOMContentLoaded', () => {
    // Load after AppConfig in dashboard.js
    document.addEventListener('appConfigLoaded', () => {
        Gamification.load();
    });
});
