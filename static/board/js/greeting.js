/**
 * greeting.js — One-line, status-aware greeting.
 *
 * Reads what the app already knows (productivity breakdown for today and
 * yesterday, gamification, today's timeline, pomodoro, user settings), builds a
 * list of candidate lines and shows the single most useful one. A line can
 * carry an action (open journal, log sleep, start focus ...).
 *
 * Add a message by pushing another entry into `candidates()`:
 *   { id, priority, text, action? }  — return null when it does not apply.
 * Higher priority wins. Wording varies by day but is stable within a day, so
 * the line does not flicker between refreshes.
 */

const Greeting = {
    yesterday: null,       // { date, data } cached score for yesterday
    _timer: null,
    _debounce: null,
    _bound: false,

    // ── lifecycle ──
    init() {
        const main = document.querySelector('.greeting-main');
        if (main && !this._bound) {
            this._bound = true;
            main.addEventListener('click', (e) => {
                const a = e.target.closest('[data-greeting-action]');
                if (!a) return;
                e.preventDefault();
                this.run(a.dataset.greetingAction);
            });
        }
        if (!this._timer) {
            this._timer = setInterval(() => this.refresh(), 60000);
            document.addEventListener('visibilitychange', () => { if (!document.hidden) this.schedule(); });
            // Anything that changes status: habit/todo actions, achievements, config load
            ['gamification', 'appConfigLoaded'].forEach(ev => document.addEventListener(ev, () => this.schedule()));
        }
        this.refresh();
    },

    /** Ask for a refresh soon; many callers can trigger it, it runs once. */
    schedule() {
        clearTimeout(this._debounce);
        this._debounce = setTimeout(() => this.refresh(), 250);
    },

    async refresh() {
        const el = document.getElementById('greeting-text');
        if (!el) return;
        try {
            const ctx = await this.gather();
            this.render(this.pick(ctx));
        } catch (e) {
            // Never break the page over a greeting; fall back to a plain hello
            this.render({ text: this.base(new Date(), this.name()) });
        }
    },

    // ── data ──
    name() {
        return (AppConfig?.userDetail?.first_name || '').trim();
    },

    async gather() {
        const now = new Date();
        const todayStr = getDate(now);
        const yStr = getDate(new Date(now.getTime() - 86400000));

        let score = null;
        const sr = await apiClient.get('board/api/productivity_score/', { silent: true });
        if (sr.status === 'success') score = sr.data;
        if (!this.yesterday || this.yesterday.date !== yStr) {
            const r = await apiClient.get(`board/api/productivity_score/?date=${yStr}`, { silent: true });
            this.yesterday = { date: yStr, data: r.status === 'success' ? r.data : null };
        }

        const tl = (typeof Timeline !== 'undefined' && Timeline.currentDate === todayStr) ? Timeline.events : [];
        return {
            now,
            h: now.getHours(),
            name: this.name(),
            score,
            yday: this.yesterday.data,
            gami: (typeof Gamification !== 'undefined') ? Gamification.data : null,
            events: (tl || []).filter(e => !(e.action_response && e.action_response.snooze)),
            pomo: (typeof Pomodoro !== 'undefined') ? Pomodoro : null,
            user: AppConfig?.userDetail || {},
        };
    },

    // ── wording helpers ──
    base(now, name) {
        const h = now.getHours();
        const part = h < 5 ? 'night' : h < 12 ? 'morning' : h < 17 ? 'afternoon' : h < 22 ? 'evening' : 'night';
        return `Good ${part}${name ? ', ' + name : ''}`;
    },

    /** Pick one of several wordings; stable for the day and the situation. */
    vary(key, options, now) {
        const s = `${getDate(now)}|${key}`;
        let hash = 0;
        for (let i = 0; i < s.length; i++) hash = (hash * 31 + s.charCodeAt(i)) >>> 0;
        return options[hash % options.length];
    },

    plural(n, one, many) { return `${n} ${n === 1 ? one : many}`; },

    clean(text) {
        return String(text || '')
            .replace(/^(overdue by [^:]+|due today):\s*/i, '')
            .trim();
    },

    // ── the engine ──
    candidates(c) {
        const { now, h, name, score, yday, gami, events, pomo, user } = c;
        const n = name ? `, ${name}` : '';
        const b = score?.breakdown || {};
        const out = [];
        const add = (id, priority, text, action) => out.push({ id, priority, text, action });

        const isOverdue = (e) => e.event_type === 'todo' && !e.action_response && /^overdue/i.test(e.event || '');
        const overdue = events.filter(isOverdue);
        const upcoming = events
            .filter(e => !e.action_response && !isOverdue(e) && new Date(e.timestamp) > now
                && !['sleep_tracker', 'journal', 'text'].includes(e.event_type))
            .sort((a, z) => new Date(a.timestamp) - new Date(z.timestamp));
        const next = upcoming[0];
        const nextInMin = next ? Math.round((new Date(next.timestamp) - now) / 60000) : null;

        const habitsLeft = (b.habits_due || 0) - (b.habits_done || 0);
        const tasksLeft = Math.max(0, (b.todos_due || 0) - (b.todos_done || 0));
        const focusToday = pomo?.todayFocusMinutes || 0;
        const pst = pomo?.state;

        // Perfect day
        if (score && score.total >= 10) {
            add('perfect', 100, this.vary('perfect', [
                `Perfect 10/10 today${n}. That's how it's done.`,
                `A perfect day${n}: 10/10. Take the win.`,
            ], now), 'pane:achievements');
        }

        // Late night: go to sleep (journal first if it is still blank)
        if (h >= 23 || h < 4) {
            add('sleep', 95, (!b.journaled && h >= 21)
                ? `It's late${n}. Write your journal, then sleep.`
                : this.vary('sleep', [
                    `Go to sleep${n}. Tomorrow's reps start fresh.`,
                    `It's late${n}. Rest is part of the plan.`,
                ], now), (!b.journaled && h >= 21) ? 'pane:journals' : null);
        } else if (user.sleep_time) {
            // Bedtime is close
            const [sh, sm] = String(user.sleep_time).split(':').map(Number);
            const bed = new Date(now); bed.setHours(sh, sm || 0, 0, 0);
            const mins = Math.round((bed - now) / 60000);
            if (mins > 0 && mins <= 45) {
                add('bedtime', 90, `Bedtime in ${mins} min${n}. Start winding down.`, null);
            }
        }

        // Focus session running
        if (pst?.running && pst.mode === 'focus') {
            add('focus-on', 92, `Focus mode on${n}. Stay with it.`, null);
        } else if (pst?.running) {
            add('break-on', 60, `Break time${n}. Back to it when the timer ends.`, null);
        }

        // Achievements unlocked today
        if (gami?.achievements) {
            const today = getDate(now);
            const earned = gami.achievements
                .filter(a => a.unlocked && a.unlocked_at && getDate(new Date(a.unlocked_at)) === today)
                .sort((a, z) => new Date(z.unlocked_at) - new Date(a.unlocked_at));
            if (earned.length) {
                const latest = earned[0];
                const ageH = (now - new Date(latest.unlocked_at)) / 3600000;
                if (ageH < 4) add('badge-new', 90, `Badge unlocked: ${latest.name}${n}!`, 'pane:achievements');
                else add('badge-today', 35, `You earned "${latest.name}" today${n}.`, 'pane:achievements');
            }
        }

        // Morning: start of the day / log sleep
        if (!b.sleep_logged && h >= 5 && h < 14) {
            add('sleep-log', h < 8 ? 85 : 78, h < 8
                ? `Good morning${n}. How did you sleep? Log it.`
                : `Log last night's sleep${n}.`, 'sleep');
        }
        if (h >= 4 && h < 8) {
            add('morning-start', 80, next
                ? `Good morning${n}. First up: ${this.clean(next.event)}.`
                : `Good morning${n}. Make today count.`, null);
        }

        // Habits
        if (score && (b.habits_due || 0) > 0 && (b.habits_done || 0) === 0) {
            if (yday && yday.breakdown && yday.breakdown.habits_due > 0 && yday.breakdown.habits_done === 0 && h < 14) {
                add('habit-yday', 74, `No habits logged yesterday${n}. Start today with one.`, 'pane:trackers');
            }
            if (h >= 9) {
                add('habit-none', 70, this.vary('habit-none', [
                    `No habits logged yet today${n}. Pick the easiest one.`,
                    `Your habits are waiting${n}. Start with one.`,
                ], now), 'pane:trackers');
            }
        } else if (habitsLeft > 0 && h >= 17) {
            add('habit-left', 62, `${this.plural(habitsLeft, 'habit', 'habits')} left today${n}.`, 'pane:trackers');
        }

        // Journal
        if (score && !b.journaled && h >= 19 && h < 23) {
            add('journal', 66, this.vary('journal', [
                `Your journal is still blank${n}. Two lines is enough.`,
                `Next is your journal${n}. How was the day?`,
            ], now), 'pane:journals');
        }

        // Tasks
        if (overdue.length) {
            add('overdue', 58, `${this.plural(overdue.length, 'task is', 'tasks are')} overdue${n}. Clear one, or push them to tomorrow.`, 'overdue');
        }
        if (tasksLeft > 0 && h >= 9) {
            add('tasks', 52, `${this.plural(tasksLeft, 'task', 'tasks')} due today${n}.`, 'pane:todos');
        }

        // Focus time suggestion
        if (!pst?.running && focusToday === 0 && h >= 9 && h < 18 && (tasksLeft > 0 || habitsLeft > 0 || overdue.length)) {
            const mins = user.pomodoro_focus || 25;
            add('focus-next', 46, `Next comes focus time${n}. Start a ${mins}-minute session.`, 'focus');
        }

        // What is coming up
        if (next && nextInMin !== null && nextInMin <= 90) {
            const when = nextInMin < 60 ? `${Math.max(nextInMin, 1)} min` : `${Math.floor(nextInMin / 60)}h ${nextInMin % 60}m`;
            add('next-event', 42, `Next: ${this.clean(next.event)} in ${when}.`, null);
        }

        // Streak
        if (gami && gami.current_streak >= 3) {
            add('streak', 30, `${gami.current_streak}-day streak${n}. Keep it alive.`, null);
        }

        // Nothing left to do
        if (score && tasksLeft === 0 && habitsLeft <= 0 && b.journaled && overdue.length === 0) {
            add('clear', 25, `All clear for today${n}. Nicely done.`, null);
        }

        add('default', 10, `${this.base(now, name)}.`, null);
        return out;
    },

    pick(ctx) {
        const list = this.candidates(ctx);
        list.sort((a, z) => z.priority - a.priority);
        return list[0];
    },

    // ── output ──
    render(pick) {
        const el = document.getElementById('greeting-text');
        if (!el || !pick) return;
        el.textContent = '';
        el.dataset.greetingId = pick.id || '';
        if (pick.action) {
            const a = document.createElement('a');
            a.href = '#';
            a.className = 'greeting-link';
            a.dataset.greetingAction = pick.action;
            a.append(document.createTextNode(pick.text + ' '));
            const arrow = document.createElement('i');
            arrow.className = 'fas fa-arrow-right';
            arrow.setAttribute('aria-hidden', 'true');
            a.appendChild(arrow);
            el.appendChild(a);
        } else {
            el.textContent = pick.text;
        }
    },

    run(action) {
        if (action.startsWith('pane:')) { switchPane(action.slice(5)); return; }
        if (action === 'sleep' && typeof openSleepModal === 'function') { openSleepModal(); return; }
        if (action === 'focus' && typeof Pomodoro !== 'undefined') { Pomodoro.toggle(); this.schedule(); return; }
        if (action === 'overdue') {
            const card = document.querySelector('.tl-overdue');
            if (card) card.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
    },
};
