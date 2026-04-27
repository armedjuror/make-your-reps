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
        if (habits.length === 0) {
            el.innerHTML = '<p class="small" style="color:var(--ink-gray);opacity:0.6;">No hallmarked habits yet. Keep building!</p>';
            return;
        }
        el.innerHTML = `<div class="hallmark-grid">${habits.map(h => `
            <div class="hallmark-item">
                <div class="hallmark-icon"><i class="fas fa-award"></i></div>
                <div class="hallmark-body">
                    <div class="hallmark-name">${h.habit}</div>
                    <div class="hallmark-meta">
                        <span>${h.stats.total_reps} reps</span>
                        <span class="mx-1">·</span>
                        <span>Best streak: ${h.stats.max_streak}</span>
                    </div>
                </div>
            </div>`).join('')}
        </div>`;
    },

    async loadProductivityHistory() {
        const res = await apiClient.get('board/api/productivity_score_history/?days=7');
        if (res.status !== 'success') return;
        this.renderProductivityChart(res.data);
    },

    renderProductivityChart(history) {
        const canvas = document.getElementById('productivityScoreChart');
        if (!canvas) return;

        const labels = history.map(d => {
            const dt = new Date(d.date + 'T00:00:00');
            return dt.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
        });
        const scores = history.map(d => d.score);

        // Resolve CSS variable colour
        const inkBrown = getComputedStyle(document.body).getPropertyValue('--ink-brown').trim() || 'rgba(152,117,63,1)';
        const inkBrownLight = getComputedStyle(document.body).getPropertyValue('--ink-brown-light').trim() || 'rgba(184,156,125,0.3)';

        if (this._scoreChart) {
            this._scoreChart.destroy();
        }

        this._scoreChart = new Chart(canvas, {
            type: 'line',
            data: {
                labels,
                datasets: [{
                    data: scores,
                    backgroundColor: scores.map(s => s >= 7 ? inkBrown : inkBrownLight),
                    borderColor: inkBrown,
                    borderWidth: 1,
                    borderRadius: 4,
                }]
            },
            options: {
                responsive: true,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: ctx => `Score: ${ctx.parsed.y} / 10`
                        }
                    }
                },
                scales: {
                    y: {
                        min: 0, max: 10,
                        ticks: {
                            stepSize: 2,
                            color: inkBrown,
                            font: { size: 11 },
                        },
                        grid: { color: inkBrownLight.replace('1)', '0.15)') },
                        border: { display: false },
                    },
                    x: {
                        ticks: { color: inkBrown, font: { size: 11 } },
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
                <div class="ach-badge-icon"><i class="${a.icon}"></i></div>
                <div class="ach-badge-name">${a.name}</div>
                ${a.unlocked ? `<div class="ach-badge-date">${dateStr}</div>` : `<div class="ach-badge-desc">${a.description}</div>`}
            </div>`;
    },

    // Called after any action that returns gamification data
    handleResult(result) {
        if (!result) return;
        if (result.points_awarded) {
            this.showFloatingPoints(result.points_awarded);
        }
        if (result.new_achievements && result.new_achievements.length > 0) {
            this.showAchievementToasts(result.new_achievements);
        }
        // Refresh status bar
        this.load();
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
})();

// Initialize on DOMContentLoaded (after AppConfig loads)
document.addEventListener('DOMContentLoaded', () => {
    // Load after AppConfig in dashboard.js
    document.addEventListener('appConfigLoaded', () => {
        Gamification.load();
    });
});
