/**
 * focus-player.js — one full-screen player for workouts and Pomodoro focus.
 *
 * It plays a flat step list built by the server (fitness/steps.py). Rep sets
 * never auto-advance on time alone: the user taps Done (or the set logs its
 * target after fallback_seconds). Timed steps, rests, focus and breaks advance
 * at zero. State is saved on every step change, so a closed tab resumes at the
 * same step on any device. No inline handlers (data-fp="..."), MV3-safe.
 */
const FocusPlayer = {
    mode: null,              // 'workout' | 'focus'
    data: null,              // server payload
    steps: [],
    idx: 0,
    stepStart: 0,            // ms, wall clock when the current step started (pauses shift it)
    extra: 0,                // seconds added to the current step (+15 s)
    paused: false,
    pausedAt: 0,
    logs: {},                // `${ex}:${set}:${side}` -> set payload
    loads: {},               // exercise -> last load used this session
    struggle: {},            // exercise -> sets below reps_min
    restExt: 0,              // consecutive extended rests
    promptedThisRest: false,
    halfwayShown: false,
    beeped: {},
    _timer: null,
    _wake: null,
    _skew: 0,                // server now - client now (ms)
    BANDS: ['yellow band', 'red band', 'green band', 'blue band', 'black band'],

    esc(s) { const d = document.createElement('div'); d.textContent = s == null ? '' : String(s); return d.innerHTML; },
    now() { return Date.now() + this._skew; },
    voice() { try { return localStorage.getItem('myr_coach_voice') || 'quiet'; } catch (e) { return 'quiet'; } },
    setVoice(v) { try { localStorage.setItem('myr_coach_voice', v); } catch (e) { /* storage off */ } },
    /** Quiet calls (no page loader behind the player); errors still surface. */
    async api(method, url, body) {
        const res = method === 'get' || method === 'delete'
            ? await apiClient[method](url, { silent: true })
            : await apiClient[method](url, body, { silent: true });
        if (res.status !== 'success') this.toast(typeof res.error === 'string' ? res.error : 'Something went wrong');
        return res;
    },
    url(u) { return u && u.startsWith('/') && typeof HOST !== 'undefined' ? HOST.replace(/\/$/, '') + u : u; },

    // ── Entry points ──────────────────────────────────────────
    init() {
        document.addEventListener('click', (e) => {
            const b = e.target.closest('[data-fp]');
            if (b && (b.closest('#fp-root') || b.dataset.fpGlobal !== undefined)) this.onClick(b, e);
        });
        document.addEventListener('keydown', (e) => {
            if (!this.el || this.el.hidden) return;
            if (e.key === 'Escape') { e.preventDefault(); this.closeSheet() || this.askClose(); }
            if (e.key === ' ' && !e.target.closest('input, textarea, select, button')) { e.preventDefault(); this.togglePause(); }
        });
        document.addEventListener('visibilitychange', () => { if (!document.hidden && this.el && !this.el.hidden) this.wakeLock(); });
        // ?start=workout (from the extension's Start button)
        const q = new URLSearchParams(location.search);
        if (q.get('start') === 'workout') setTimeout(() => this.startWorkout(), 800);
        if (q.get('start') === 'focus') setTimeout(() => this.startFocus({}), 800);
    },

    async startWorkout() {
        const act = await apiClient.get('board/api/fitness/workouts/active/', { silent: true });
        if (act.status === 'success' && act.data) return this.open('workout', act.data);
        const ov = await apiClient.get('board/api/fitness/overview/', { silent: true });
        const a = ov.status === 'success' && ov.data.activity;
        if (!a || !a.session) return showError('There is no workout planned today.', 'Nothing to start');
        const why = ov.data.profile && ov.data.profile.why;
        this.mount();
        this.el.querySelector('.fp-body').innerHTML = `<div class="fp-pre">
            <div class="fp-pre-kicker">Today&rsquo;s workout</div>
            <h2>${this.esc(a.session.name)}</h2>
            <div class="fp-pre-meta">about ${a.session.minutes || this.estMinutes(a)} min &middot; ${a.session.exercise_count} exercises</div>
            ${why ? `<blockquote class="fp-why">&ldquo;${this.esc(why)}&rdquo;</blockquote>` : ''}
            <div class="fp-pre-actions">
                <button type="button" class="btn btn-paper btn-primary btn-lg" data-fp="go-workout"><i class="fas fa-play me-2"></i>Start</button>
                <button type="button" class="btn btn-paper" data-fp="log-instead">I already did it</button>
            </div></div>`;
        this.show();
    },

    estMinutes(a) { return Math.max(1, Math.round((a.steps || []).length * 1.5)); },

    async startFocus(opts) {
        opts = opts || {};
        const act = await apiClient.get('board/api/focus/sessions/active/', { silent: true });
        if (act.status === 'success' && act.data) return this.open('focus', act.data);
        const def = await apiClient.get('board/api/focus/sessions/', { silent: true });
        const p = (def.status === 'success' && def.data) || { focus_min: 25, break_min: 5, cycles: 4, long_break_min: 15 };
        this._focusOpts = opts;
        this.mount();
        this.el.querySelector('.fp-body').innerHTML = `<div class="fp-pre">
            <div class="fp-pre-kicker">Focus mode</div>
            <h2>${this.esc(opts.title || 'Deep work')}</h2>
            <div class="conversational-form fp-plan">
                <div class="convo-line">I&rsquo;ll focus for <input type="number" min="1" max="180" class="form-input" data-fp-plan="focus_min" value="${p.focus_min}"> min,
                    rest <input type="number" min="1" max="60" class="form-input" data-fp-plan="break_min" value="${p.break_min}"> min,
                    and do <input type="number" min="1" max="12" class="form-input" data-fp-plan="cycles" value="${p.cycles}"> rounds.</div>
            </div>
            <div class="fp-pre-actions"><button type="button" class="btn btn-paper btn-primary btn-lg" data-fp="go-focus"><i class="fas fa-play me-2"></i>Start</button></div>
        </div>`;
        if (typeof resizeInputs === 'function') resizeInputs(this.el);
        this.show();
    },

    // ── Lifecycle ─────────────────────────────────────────────
    mount() {
        if (!this.el) {
            this.el = document.createElement('div');
            this.el.id = 'fp-root';
            this.el.className = 'fp-root';
            this.el.setAttribute('role', 'dialog');
            this.el.setAttribute('aria-modal', 'true');
            this.el.setAttribute('aria-label', 'Session player');
            this.el.hidden = true;
            document.body.appendChild(this.el);
        }
        this.el.innerHTML = `<div class="fp-top">
                <button type="button" class="fp-icon" data-fp="close" aria-label="Close"><i class="fas fa-times"></i></button>
                <div class="fp-clock"><span data-fp-el="elapsed">0:00</span> &middot; <span data-fp-el="pct">0%</span></div>
                <button type="button" class="fp-icon" data-fp="voice" aria-label="Coach voice" title="Coach voice"><i class="fas fa-volume-down"></i></button>
            </div>
            <div class="fp-segments" data-fp-el="segments"></div>
            <div class="fp-body"></div>
            <div class="fp-sheet" data-fp-el="sheet" hidden></div>
            <div class="fp-toast" data-fp-el="toast" aria-live="polite"></div>`;
        this.renderVoice();
    },

    show() {
        this.el.hidden = false;
        document.body.classList.add('fp-open');
        this.wakeLock();
    },

    hide() {
        clearInterval(this._timer);
        this._timer = null;
        if (typeof Exercise3D !== 'undefined') Exercise3D.unmount(this.el.querySelector('.fp-visual'));
        if (this.el) this.el.hidden = true;
        document.body.classList.remove('fp-open');
        if (this._wake) { this._wake.release().catch(() => {}); this._wake = null; }
        if (typeof Fitness !== 'undefined' && Fitness.data) Fitness.load();
        if (typeof Resilient !== 'undefined') Resilient._refresh();
    },

    async wakeLock() {
        try { if ('wakeLock' in navigator && !this._wake) this._wake = await navigator.wakeLock.request('screen'); } catch (e) { /* not allowed */ }
    },

    open(mode, payload) {
        this.mode = mode;
        this.data = payload;
        this.steps = payload.steps;
        const st = payload.session.state || {};
        this._skew = payload.session.now ? Date.parse(payload.session.now) - Date.now() : 0;
        this.idx = Math.min(st.index || 0, this.steps.length - 1);
        this.stepStart = st.step_started_at ? Date.parse(st.step_started_at) : this.now();
        this.paused = !!payload.session.paused;
        this.pausedAt = payload.session.paused_at ? Date.parse(payload.session.paused_at) : this.now();
        this.extra = 0;
        this.logs = {};
        this.loads = {};
        this.struggle = {};
        this.restExt = 0;
        this.beeped = {};
        this.halfwayShown = this.progressShare() >= 0.5;
        (payload.sets || []).forEach(s => { this.logs[this.key(s.exercise, s.set_index, s.side)] = s; if (s.load) this.loads[s.exercise] = s.load; });
        this.mount();
        this.show();
        this.renderStep();
        if (payload.resumed) this.toast('Picked up where you left off');
        if (!this._timer) this._timer = setInterval(() => this.tick(), 200);
    },

    key(ex, set, side) { return `${ex}:${set}:${side || ''}`; },
    step() { return this.steps[this.idx]; },
    base() { return this.mode === 'workout' ? `board/api/fitness/workouts/${this.data.session.id}` : `board/api/focus/sessions/${this.data.session.id}`; },
    stateUrl() { return this.mode === 'workout' ? `${this.base()}/state/` : `${this.base()}/`; },
    exInfo(id) { return id && this.data.meta.exercises ? this.data.meta.exercises[id] : null; },

    // ── Timing ────────────────────────────────────────────────
    elapsedInStep() {
        const end = this.paused ? this.pausedAt : this.now();
        return Math.max(0, (end - this.stepStart) / 1000);
    },

    duration(s) { return ((s.target && s.target.seconds) || s.est_seconds || 0) + this.extra; },

    total() { return this.steps.reduce((a, s) => a + (s.est_seconds || 0), 0) || 1; },

    progressShare() {
        let done = 0;
        for (let i = 0; i < this.idx; i++) done += this.steps[i].est_seconds || 0;
        const s = this.step();
        if (s) done += Math.min(this.elapsedInStep(), s.est_seconds || 0);
        return done / this.total();
    },

    remainingSeconds() {
        let left = 0;
        for (let i = this.idx + 1; i < this.steps.length; i++) left += this.steps[i].est_seconds || 0;
        const s = this.step();
        return left + Math.max(0, (s ? s.est_seconds : 0) - this.elapsedInStep());
    },

    fmt(sec) {
        sec = Math.max(0, Math.round(sec));
        const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
        return h ? `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}` : `${m}:${String(s).padStart(2, '0')}`;
    },

    tick() {
        const s = this.step();
        if (!s || this.paused) return this.renderClock();
        const t = this.elapsedInStep();
        if (s.advance === 'auto') {
            const left = this.duration(s) - t;
            if (s.kind === 'rest' && left <= 3.05 && left > 0) {
                const n = Math.ceil(left);
                if (!this.beeped[n]) { this.beeped[n] = true; this.cue(n === 1 ? 'beep-high' : 'beep', n); }
            }
            if (left <= 0) {
                if (s.kind === 'focus' || s.kind === 'break') this.cue('chime');
                else if (s.kind === 'exercise_timed') this.cue('done');
                this.next(true);
                return;
            }
        } else if (s.kind === 'exercise_set') {
            // Last-3-reps countdown, then the fallback logs the target and moves on
            const spr = s.sec_per_rep || 3;
            const est = s.est_seconds || 30;
            const leftReps = Math.ceil((est - t) / spr);
            if (leftReps <= 3 && leftReps >= 1 && !this.beeped[`r${leftReps}`]) {
                this.beeped[`r${leftReps}`] = true;
                this.cue('beep', leftReps);
            }
            if (s.fallback_seconds && t >= s.fallback_seconds && !this.logs[this.key(s.exercise_id, s.set_index, s.side)]) {
                const hi = s.target.reps[1];
                this.logSet(s, { reps_done: hi, load: this.defaultLoad(s.exercise_id) }).then(() => {
                    this.toast(`Logged ${hi} reps. Tap Log to change it.`);
                    this.next(true);
                });
                return;
            }
        }
        if (!this.halfwayShown && this.mode === 'workout' && this.progressShare() >= 0.5) {
            this.halfwayShown = true;
            this.say('Halfway. The second half is lighter.', 'Halfway. The second half is lighter.');
        }
        this.renderClock();
    },

    // ── Audio, haptics, voice ─────────────────────────────────
    cue(kind, n) {
        const v = this.voice();
        if (v === 'off') return;
        if (navigator.vibrate) navigator.vibrate(kind === 'done' || kind === 'chime' ? [80, 60, 80] : 40);
        if (v === 'full' && n && 'speechSynthesis' in window && (kind === 'beep' || kind === 'beep-high')) return this.speak(String(n));
        try {
            this._ctx = this._ctx || new (window.AudioContext || window.webkitAudioContext)();
            const ctx = this._ctx, o = ctx.createOscillator(), g = ctx.createGain();
            const f = { beep: 660, 'beep-high': 990, done: 880, chime: 523 }[kind] || 660;
            o.frequency.value = f;
            o.connect(g); g.connect(ctx.destination);
            g.gain.setValueAtTime(0.0001, ctx.currentTime);
            g.gain.exponentialRampToValueAtTime(0.25, ctx.currentTime + 0.02);
            g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + (kind === 'chime' ? 0.9 : 0.25));
            o.start(); o.stop(ctx.currentTime + (kind === 'chime' ? 1 : 0.3));
        } catch (e) { /* no audio */ }
    },

    speak(text) {
        if (this.voice() !== 'full' || !('speechSynthesis' in window)) return;
        try { speechSynthesis.cancel(); speechSynthesis.speak(new SpeechSynthesisUtterance(text)); } catch (e) { /* no speech */ }
    },

    say(line, spoken) {
        const el = this.el.querySelector('[data-fp-el="motivation"]');
        if (el) { el.textContent = line; el.classList.remove('fp-pop'); void el.offsetWidth; el.classList.add('fp-pop'); }
        if (spoken) this.speak(spoken);
    },

    renderVoice() {
        const b = this.el && this.el.querySelector('[data-fp="voice"]');
        if (!b) return;
        const v = this.voice();
        b.innerHTML = `<i class="fas ${{ off: 'fa-volume-mute', quiet: 'fa-volume-down', full: 'fa-volume-up' }[v]}"></i>`;
        b.title = `Coach voice: ${v}`;
    },

    toast(text) {
        const t = this.el && this.el.querySelector('[data-fp-el="toast"]');
        if (!t) return;
        t.textContent = text;
        t.classList.add('show');
        clearTimeout(this._toastT);
        this._toastT = setTimeout(() => t.classList.remove('show'), 2600);
    },

    // ── Render ────────────────────────────────────────────────
    renderSegments() {
        const wrap = this.el.querySelector('[data-fp-el="segments"]');
        const segs = [];
        this.steps.forEach((s, i) => {
            const k = s.segment == null ? 0 : s.segment;
            let g = segs.find(x => x.k === k);
            if (!g) segs.push(g = { k, from: i, to: i, est: 0 });
            g.to = i;
            g.est += s.est_seconds || 0;
        });
        wrap.innerHTML = segs.map(g => `<span class="fp-seg" style="flex:${Math.max(1, g.est)}" data-from="${g.from}" data-to="${g.to}"><i></i></span>`).join('');
    },

    renderClock() {
        if (!this.el || this.el.hidden || !this.data) return;
        const s = this.step();
        if (!s) return;
        const started = Date.parse(this.data.session.started_at);
        const el = (k) => this.el.querySelector(`[data-fp-el="${k}"]`);
        el('elapsed') && (el('elapsed').textContent = this.fmt(((this.paused ? this.pausedAt : this.now()) - started) / 1000));
        el('pct') && (el('pct').textContent = `${Math.round(this.progressShare() * 100)}%`);
        const t = this.elapsedInStep();
        const timer = el('timer');
        if (timer) {
            if (s.advance === 'auto') timer.textContent = this.fmt(Math.ceil(this.duration(s) - t));
            else timer.textContent = this.fmt(t);
        }
        const ring = el('ring');
        if (ring && s.advance === 'auto') {
            const C = 2 * Math.PI * 90;
            ring.style.strokeDasharray = C;
            ring.style.strokeDashoffset = C * Math.min(1, t / Math.max(1, this.duration(s)));
        }
        this.el.querySelectorAll('.fp-seg').forEach(seg => {
            const from = +seg.dataset.from, to = +seg.dataset.to;
            let done = 0, all = 0;
            for (let i = from; i <= to; i++) {
                const e = this.steps[i].est_seconds || 0;
                all += e;
                if (i < this.idx) done += e;
                else if (i === this.idx) done += Math.min(t, e);
            }
            seg.firstElementChild.style.width = `${all ? (done / all) * 100 : 0}%`;
        });
        const pause = this.el.querySelector('[data-fp="pause"]');
        if (pause) pause.innerHTML = this.paused ? '<i class="fas fa-play"></i>' : '<i class="fas fa-pause"></i>';
    },

    renderStep() {
        const s = this.step();
        if (!s) return;
        this.renderSegments();
        this.beeped = {};
        this.promptedThisRest = false;
        const body = this.el.querySelector('.fp-body');
        const ex = this.exInfo(s.exercise_id) || (s.kind === 'rest' ? this.exInfo(s.next_exercise_id) : null);
        const isSet = s.kind === 'exercise_set';
        const isWork = isSet || s.kind === 'exercise_timed';
        const label = this.mode === 'focus' ? s.title : `${this.esc(s.title)}${s.last_set ? ' <span class="fp-last">Last set!</span>' : ''}`;
        const target = isSet ? `${s.target.reps[0]}–${s.target.reps[1]} reps` : (s.kind === 'transition' ? 'Get set on the other side' : '');
        let visual;
        if (this.mode === 'focus' || !ex) {
            visual = `<svg class="fp-ring" viewBox="0 0 200 200" aria-hidden="true"><circle class="fp-ring-bg" cx="100" cy="100" r="90"/><circle class="fp-ring-fill" data-fp-el="ring" cx="100" cy="100" r="90"/></svg>
                <div class="fp-timer fp-timer-in" data-fp-el="timer" role="timer">0:00</div>`;
        } else {
            visual = `<div class="fp-visual" data-ex="${this.esc(ex.id)}">${ex.still ? `<img src="${this.url(ex.still)}" alt="${this.esc(ex.name)}">` : ''}</div>`;
        }
        const nxt = s.next_preview ? `<div class="fp-next"><span class="fp-next-k">Up next</span>
            ${(() => { const n = this.exInfo(s.next_exercise_id); return n && n.still ? `<img src="${this.url(n.still)}" alt="">` : ''; })()}
            <span>${this.esc(s.next_preview)}</span></div>` : '';
        const focusExtras = this.mode === 'focus' ? `
            ${this.data.session.title ? `<div class="fp-task"><i class="fas fa-crosshairs"></i> ${this.esc(this.data.session.title)}</div>` : ''}
            <div class="fp-focus-actions">
                <button type="button" class="btn btn-paper btn-sm" data-fp="park"><i class="fas fa-inbox me-1"></i>Park a thought</button>
                <button type="button" class="btn btn-paper btn-sm" data-fp="distracted"><i class="fas fa-bolt me-1"></i>I got distracted <span data-fp-el="intr">${this.data.session.interruptions || 0}</span></button>
            </div>` : '';
        body.innerHTML = `
            <div class="fp-label">${label}</div>
            <div class="fp-stage ${s.kind}">${visual}</div>
            ${visual.includes('fp-timer-in') ? '' : '<div class="fp-timer" data-fp-el="timer" role="timer">0:00</div>'}
            <div class="fp-target">${this.esc(target)}</div>
            <div class="fp-motivation" data-fp-el="motivation">${this.esc(this.motivation(s))}</div>
            <div class="fp-controls">
                <button type="button" class="fp-ctl" data-fp="prev" aria-label="Previous" ${this.idx === 0 ? 'disabled' : ''}><i class="fas fa-step-backward"></i></button>
                <button type="button" class="fp-ctl fp-ctl-main" data-fp="pause" aria-label="Pause or resume"><i class="fas fa-pause"></i></button>
                ${isSet ? '<button type="button" class="fp-ctl fp-ctl-done" data-fp="done" aria-label="Done"><i class="fas fa-check"></i></button>' : ''}
                <button type="button" class="fp-ctl" data-fp="next" aria-label="Next"><i class="fas fa-step-forward"></i></button>
            </div>
            <div class="fp-sub">
                ${this.mode === 'workout' && (isWork || s.kind === 'rest') ? '<button type="button" class="btn btn-paper btn-sm" data-fp="guide"><i class="fas fa-book-open me-1"></i>Guide</button>' : ''}
                ${isWork ? '<button type="button" class="btn btn-paper btn-sm" data-fp="log"><i class="fas fa-pen me-1"></i>Log</button>' : ''}
                ${s.kind === 'rest' ? '<button type="button" class="btn btn-paper btn-sm" data-fp="more-rest">+15 s</button>' : ''}
                ${this.suggestChip(s)}
            </div>
            ${focusExtras}
            ${nxt}`;
        if (ex && typeof Exercise3D !== 'undefined' && this.mode === 'workout') {
            Exercise3D.mount(body.querySelector('.fp-visual'), ex, { side: s.side === 'left' ? 'left' : 'right', autoplay: s.kind !== 'rest', compact: true });
        }
        if (isSet && s.set_index === 1 && !s.side) this.speak(`${(ex && ex.name) || ''}. ${target}.`);
        if (s.kind === 'rest' && s.next_preview) this.speak(`Rest. Next: ${s.next_preview.split(' · ')[0]}.`);
        this.renderClock();
    },

    motivation(s) {
        if (this.mode === 'focus') return s.kind === 'focus' ? 'One thing at a time.' : 'Stand up, stretch, drink some water.';
        if (s.kind === 'exercise_set') {
            const last = (this.data.meta.last || {})[s.exercise_id];
            return last ? `Last time: ${last.reps} reps${last.load ? `, ${last.load}` : ''}. Beat it?` : '';
        }
        if (s.kind === 'rest') {
            const n = this.exInfo(s.next_exercise_id);
            const tip = n && ((n.avoid && n.avoid[0] && `Avoid: ${n.avoid[0].toLowerCase()}`) || (n.steps && n.steps[1]));
            const left = new Set(this.steps.slice(this.idx + 1).filter(x => x.exercise_id && !x.warmup).map(x => x.exercise_id)).size;
            const mins = Math.max(1, Math.round(this.remainingSeconds() / 60));
            return `${tip ? tip + ' · ' : ''}${left} exercise${left === 1 ? '' : 's'} left · about ${mins} min`;
        }
        if (s.kind === 'transition') return 'Switch sides';
        return '';
    },

    suggestChip(s) {
        if (this.mode !== 'workout' || s.kind !== 'exercise_set') return '';
        const sg = (this.data.meta.suggestions || {})[s.exercise_id];
        if (!sg || sg.type !== 'up' || !sg.load) return '';
        return `<button type="button" class="btn btn-paper btn-sm fp-chip" data-fp="heavier" data-load="${this.esc(sg.load)}"><i class="fas fa-arrow-up me-1"></i>Go heavier</button>`;
    },

    // ── Navigation ────────────────────────────────────────────
    async go(i, { auto = false } = {}) {
        if (i >= this.steps.length) return this.finish('finish');
        this.idx = Math.max(0, i);
        this.stepStart = this.now();
        this.pausedAt = this.now();
        this.extra = 0;
        this.renderStep();
        this.api('put', this.stateUrl(), {
            index: this.idx, ...(this.mode === 'workout' ? { rest_extensions: this.restExt } : {}),
        });
    },

    async next(auto = false) {
        const s = this.step();
        if (s && s.kind === 'exercise_set' && !auto && !this.logs[this.key(s.exercise_id, s.set_index, s.side)]) {
            await this.logSet(s, { skipped: true });
        }
        if (s && s.kind === 'rest' && this.extra === 0) this.restExt = 0;
        return this.go(this.idx + 1, { auto });
    },

    prev() { if (this.idx > 0) this.go(this.idx - 1); },

    togglePause() {
        if (!this.data) return;
        if (this.paused) {
            this.stepStart += this.now() - this.pausedAt;
            this.paused = false;
        } else {
            this.pausedAt = this.now();
            this.paused = true;
        }
        this.api('put', this.stateUrl(), { paused: this.paused });
        this.renderClock();
    },

    // ── Sets ──────────────────────────────────────────────────
    defaultLoad(ex) {
        return this.loads[ex] || ((this.data.meta.last || {})[ex] || {}).load || '';
    },

    async logSet(s, body) {
        const payload = { exercise: s.exercise_id, set_index: s.set_index, side: s.side || '', ...body };
        if (s.kind === 'exercise_timed' && body.seconds_done == null && !body.skipped) payload.seconds_done = s.target.seconds;
        const res = await this.api('post', `${this.base()}/sets/`, payload);
        if (res.status !== 'success') return res;
        this.logs[this.key(s.exercise_id, s.set_index, s.side)] = payload;
        if (payload.load) this.loads[s.exercise_id] = payload.load;
        if (!body.skipped) {
            if (navigator.vibrate) navigator.vibrate(60);
            this.floatXp('+2 XP');
        }
        if (res.data.pr) this.celebrate(res.data.pr);
        return res;
    },

    floatXp(text) {
        const f = document.createElement('div');
        f.className = 'fp-xp';
        f.textContent = text;
        this.el.appendChild(f);
        setTimeout(() => f.remove(), 1400);
    },

    celebrate(pr) {
        const c = document.createElement('div');
        c.className = 'fp-celebrate';
        c.innerHTML = `<div><i class="fas fa-trophy"></i><div class="fp-cel-k">New personal record</div><div class="fp-cel-t">${this.esc(pr)}</div></div>`;
        this.el.appendChild(c);
        this.cue('chime');
        this.speak('New personal record!');
        c.addEventListener('click', () => c.remove());
        setTimeout(() => c.remove(), 2600);
    },

    repPicker(s) {
        if (s.kind === 'exercise_timed') {
            return this.sheet(`<h5>${this.esc(s.title)}</h5>
                <div class="conversational-form"><div class="convo-line">I held it for <input type="number" class="form-input" data-fp-f="seconds" value="${s.target.seconds}" min="0"> seconds.</div></div>
                <div class="fp-sheet-actions"><button type="button" class="btn btn-paper btn-primary" data-fp="save-timed">Save</button></div>`);
        }
        const [lo, hi] = s.target.reps;
        const prev = this.logs[this.key(s.exercise_id, s.set_index, s.side)];
        const sel = prev && prev.reps_done != null ? prev.reps_done : hi;
        const reps = [];
        for (let r = Math.max(1, lo - 3); r <= hi + 3; r++) reps.push(r);
        const load = (prev && prev.load) || this.defaultLoad(s.exercise_id);
        const isKg = /kg$/.test(load);
        this.sheet(`<h5>How many reps?</h5>
            <div class="fp-reps" role="radiogroup" aria-label="Reps">${reps.map(r => `<button type="button" class="fp-rep ${r === sel ? 'on' : ''} ${r < lo ? 'low' : ''}" data-fp="rep" data-val="${r}" role="radio" aria-checked="${r === sel}">${r}</button>`).join('')}</div>
            <div class="fp-sheet-row"><span class="fp-sheet-k">Load</span>
                <div class="fp-loads">${this.BANDS.map(b => `<button type="button" class="fp-load ${b === load ? 'on' : ''} fp-band-${b.split(' ')[0]}" data-fp="load" data-val="${b}">${b.split(' ')[0]}</button>`).join('')}
                <input type="text" class="form-input fp-kg" data-fp-f="kg" placeholder="kg" value="${isKg ? this.esc(load.replace(/\s*kg$/, '')) : ''}" inputmode="decimal" aria-label="Weight in kg"></div></div>
            <div class="fp-sheet-row"><span class="fp-sheet-k">Reps left in the tank <small>(optional)</small></span>
                <div class="fp-rirs">${['0', '1', '2', '3+'].map(r => `<button type="button" class="fp-rir ${prev && String(prev.rir) === r.replace('+', '') ? 'on' : ''}" data-fp="rir" data-val="${r.replace('+', '')}">${r}</button>`).join('')}</div></div>
            <div class="fp-sheet-actions"><button type="button" class="btn btn-paper btn-primary btn-lg" data-fp="save-set">Done</button></div>`);
        this._pick = { step: s, reps: sel, load, rir: prev ? prev.rir : null };
    },

    async saveSet() {
        const p = this._pick;
        const kg = this.el.querySelector('[data-fp-f="kg"]');
        let load = p.load;
        if (kg && kg.value.trim()) load = `${parseFloat(kg.value)} kg`;
        const s = p.step;
        const res = await this.logSet(s, { reps_done: p.reps, load, rir: p.rir });
        if (res.status !== 'success') return;
        this.closeSheet();
        // Struggling: reps below the range on 2 sets of a move
        if (p.reps < s.target.reps[0]) {
            this.struggle[s.exercise_id] = (this.struggle[s.exercise_id] || 0) + 1;
            if (this.struggle[s.exercise_id] === 2) { this._offerEasier = s; }
        }
        if (this.idx === this.steps.indexOf(s)) await this.next(true);
        if (this._offerEasier) { const x = this._offerEasier; this._offerEasier = null; this.offerEasier(x); }
    },

    offerEasier(s) {
        if (this.promptedThisRest) return;
        this.promptedThisRest = true;
        const reg = (this.data.meta.regressions || {})[s.exercise_id];
        this.sheet(`<h5>That one&rsquo;s tough today</h5><p class="fp-muted">No problem. Pick what helps:</p>
            <div class="fp-sheet-actions fp-stack">
                ${reg ? `<button type="button" class="btn btn-paper btn-primary" data-fp="easier" data-ex="${this.esc(s.exercise_id)}">Switch to ${this.esc(reg.name)}</button>` : ''}
                <button type="button" class="btn btn-paper" data-fp="drop-round" data-ex="${this.esc(s.exercise_id)}">Drop the last round</button>
                <button type="button" class="btn btn-paper" data-fp="close-sheet">Keep going</button></div>`);
    },

    rewriteAhead(fn) {
        const ahead = this.steps.slice(this.idx + 1);
        const kept = fn(ahead);
        // no two rests in a row, none at the end
        const clean = [];
        kept.forEach(x => { if (!(x.kind === 'rest' && (!clean.length || clean[clean.length - 1].kind === 'rest'))) clean.push(x); });
        while (clean.length && clean[clean.length - 1].kind === 'rest') clean.pop();
        this.steps = this.steps.slice(0, this.idx + 1).concat(clean).map((x, i) => ({ ...x, index: i }));
        this.api('put', `${this.base()}/state/`, { steps: this.steps });
        this.renderStep();
    },

    switchEasier(exId) {
        const reg = (this.data.meta.regressions || {})[exId];
        if (!reg) return;
        this.rewriteAhead(ahead => ahead.map(x => x.exercise_id === exId
            ? { ...x, exercise_id: reg.id, title: x.title.replace(/^[^·]+/, reg.name + ' ') } : x));
        this.toast(`Switched to ${reg.name}`);
    },

    dropLastRound(exId) {
        const cur = this.steps.find(x => x.exercise_id === exId);
        if (!cur) return;
        const block = cur.segment;
        const maxRound = Math.max(...this.steps.filter(x => x.segment === block && x.round).map(x => x.round));
        this.rewriteAhead(ahead => ahead.filter(x => !(x.segment === block && x.round === maxRound)));
        this.toast('Last round dropped');
    },

    // ── Sheets ────────────────────────────────────────────────
    sheet(html) {
        const sh = this.el.querySelector('[data-fp-el="sheet"]');
        sh.innerHTML = `<div class="fp-sheet-card">${html}</div>`;
        sh.hidden = false;
        const f = sh.querySelector('button.on, input, button');
        if (f) setTimeout(() => f.focus(), 30);
        if (typeof resizeInputs === 'function') resizeInputs(sh);
    },

    closeSheet() {
        const sh = this.el && this.el.querySelector('[data-fp-el="sheet"]');
        if (!sh || sh.hidden) return false;
        sh.hidden = true;
        sh.innerHTML = '';
        return true;
    },

    guide() {
        const s = this.step();
        const ex = this.exInfo(s.exercise_id) || this.exInfo(s.next_exercise_id);
        if (!ex) return;
        this.sheet(`<h5>${this.esc(ex.name)}</h5>
            <ol>${(ex.steps || []).map(x => `<li>${this.esc(x)}</li>`).join('')}</ol>
            ${ex.avoid && ex.avoid.length ? `<h6>Avoid</h6><ul>${ex.avoid.map(x => `<li>${this.esc(x)}</li>`).join('')}</ul>` : ''}
            ${ex.breathing ? `<p class="fp-muted"><i class="fas fa-wind"></i> ${this.esc(ex.breathing)}</p>` : ''}
            <div class="fp-sheet-actions">
                ${ex.video_url ? `<a class="btn btn-paper" href="${ex.video_url}" target="_blank" rel="noopener"><i class="fas fa-play-circle me-1"></i>Video</a>` : ''}
                <button type="button" class="btn btn-paper" data-fp="hurts"><i class="fas fa-band-aid me-1"></i>Something hurts</button>
                <button type="button" class="btn btn-paper btn-primary" data-fp="close-sheet">Back</button></div>`);
    },

    hurts() {
        const joints = [['knee', 'Knee'], ['lower_back', 'Lower back'], ['shoulder', 'Shoulder'], ['wrist', 'Wrist'], ['neck', 'Neck'], ['hip', 'Hip'], ['ankle', 'Ankle']];
        this.sheet(`<h5>What hurts?</h5><p class="fp-muted">Moves that load it will switch to an easier version or drop out, today and in the rest of your plan. If the pain is sharp or doesn&rsquo;t settle, stop and see a doctor.</p>
            <div class="fp-loads">${joints.map(([k, l]) => `<button type="button" class="fp-load" data-fp="joint" data-val="${k}">${l}</button>`).join('')}</div>
            <div class="fp-sheet-actions"><button type="button" class="btn btn-paper" data-fp="close-sheet">Cancel</button></div>`);
    },

    async pain(joint) {
        const res = await this.api('post', 'board/api/fitness/pain/', { joint });
        if (res.status !== 'success') return;
        this.closeSheet();
        if (res.data.session) {
            const keepIdx = this.idx;
            this.data = res.data.session;
            this.steps = this.data.steps;
            this.idx = Math.min(keepIdx, this.steps.length - 1);
            this.renderStep();
        }
        const n = Object.keys(res.data.changes || {}).length;
        this.toast(n ? `${n} move${n > 1 ? 's' : ''} changed for your ${joint.replace('_', ' ')}` : 'Nothing in your plan loads that joint');
    },

    askClose() {
        if (!this.data) return this.hide();
        const pct = Math.round(this.progressShare() * 100);
        const mins = Math.max(1, Math.round(this.remainingSeconds() / 60));
        const what = this.mode === 'workout' ? `${pct}% done, just ${mins} min left` : `${pct}% done`;
        this.sheet(`<h5>${what}</h5>
            <div class="fp-sheet-actions fp-stack">
                <button type="button" class="btn btn-paper btn-primary" data-fp="close-sheet">Finish</button>
                ${this.mode === 'workout' ? '<button type="button" class="btn btn-paper" data-fp="lighter">Finish lighter</button>' : ''}
                <button type="button" class="btn btn-paper" data-fp="later">Save and resume later</button>
                <button type="button" class="btn btn-paper" data-fp="end">End anyway</button></div>`);
    },

    finishLighter() {
        // Skip the remaining accessory (circuits) and the cool-down
        this.rewriteAhead(ahead => ahead.filter(x => !['circuit', 'cooldown'].includes(x.block)));
        this.closeSheet();
        this.toast('Lighter finish: accessories and cool-down skipped');
    },

    // ── Finish ────────────────────────────────────────────────
    async finish(mode) {
        clearInterval(this._timer);
        this._timer = null;
        this.closeSheet();
        if (this.mode === 'focus') {
            const res = await this.api('post', `${this.base()}/finish/`, {});
            if (res.status === 'success') this.focusEnd(res.data);
            return;
        }
        const res = await this.api('post', `${this.base()}/finish/`, { mode });
        if (res.status === 'success') this.workoutEnd(res.data);
    },

    workoutEnd(s) {
        const sm = s.summary || {};
        const sug = Object.values(sm.suggestions || {});
        const partial = s.status !== 'completed';
        if (typeof Exercise3D !== 'undefined') Exercise3D.unmount(this.el.querySelector('.fp-visual'));
        this.el.querySelector('[data-fp-el="segments"]').innerHTML = '';
        this.el.querySelector('.fp-body').innerHTML = `<div class="fp-end">
            <div class="fp-end-icon"><i class="fas ${partial ? 'fa-save' : 'fa-medal'}"></i></div>
            <h2>${partial ? 'Saved' : 'Workout done'}</h2>
            ${partial ? `<p class="fp-muted">${sm.duration_ok === false ? 'That was quicker than the plan allows, so it&rsquo;s saved without XP.' : 'Less than half the sets, so it&rsquo;s saved as partial. Your sets still count toward progress.'}</p>` : ''}
            <div class="fp-stats">
                <div><b>${this.fmt(sm.duration_seconds || 0)}</b><span>time</span></div>
                <div><b>${sm.sets_done || 0}/${sm.sets_planned || 0}</b><span>sets</span></div>
                <div><b>${sm.total_reps || 0}</b><span>reps</span></div>
                <div><b>~${s.est_kcal || 0}</b><span>kcal (estimate)</span></div>
                ${s.xp ? `<div><b>+${s.xp}</b><span>XP</span></div>` : ''}
                ${!partial ? `<div><b><i class="fas fa-fire"></i> ${sm.streak || 0}</b><span>streak</span></div>` : ''}
            </div>
            ${(sm.prs || []).length ? `<div class="fp-end-sec"><h6><i class="fas fa-trophy"></i> Personal records</h6><ul>${sm.prs.map(p => `<li>${this.esc(p)}</li>`).join('')}</ul></div>` : ''}
            ${sug.length ? `<div class="fp-end-sec"><h6>Next time</h6><ul>${sug.map(x => `<li>${this.esc((this.exInfo(x.exercise) || {}).name || x.exercise)}: ${this.esc(x.text)}</li>`).join('')}</ul></div>` : ''}
            <div class="fp-pre-actions"><button type="button" class="btn btn-paper btn-primary btn-lg" data-fp="done-close">Done</button></div>
        </div>`;
        if (!partial) { this.cue('chime'); this.speak('Workout done. Great work.'); }
        this.data = null;
    },

    focusEnd(s) {
        const linked = s.task || s.habit || s.routine_entry;
        this.el.querySelector('[data-fp-el="segments"]').innerHTML = '';
        this.el.querySelector('.fp-body').innerHTML = `<div class="fp-end">
            <div class="fp-end-icon"><i class="fas fa-brain"></i></div>
            <h2>Focus session done</h2>
            <div class="fp-stats">
                <div><b>${s.focus_minutes}</b><span>focused min</span></div>
                <div><b>${s.completed_cycles}</b><span>cycles</span></div>
                <div><b>${s.interruptions}</b><span>distractions</span></div>
                ${s.parked ? `<div><b>${s.parked}</b><span>parked</span></div>` : ''}
                ${s.xp ? `<div><b>+${s.xp}</b><span>XP</span></div>` : ''}
            </div>
            ${linked ? `<div class="form-check fp-tick"><input class="form-check-input" type="checkbox" id="fp-tick" checked><label class="form-check-label" for="fp-tick">Mark &ldquo;${this.esc(s.title)}&rdquo; done</label></div>` : ''}
            <div class="fp-pre-actions"><button type="button" class="btn btn-paper btn-primary btn-lg" data-fp="done-focus" data-id="${s.id}">Done</button></div>
        </div>`;
        this._focusEnded = s;
        this.cue('chime');
        this.data = null;
    },

    // ── Clicks ────────────────────────────────────────────────
    async onClick(b) {
        const a = b.dataset.fp;
        const s = this.step();
        switch (a) {
            case 'close': return this.data ? this.askClose() : this.hide();
            case 'voice': {
                const order = ['quiet', 'full', 'off'];
                this.setVoice(order[(order.indexOf(this.voice()) + 1) % 3]);
                this.renderVoice();
                return this.toast(`Coach voice: ${this.voice()}`);
            }
            case 'focus-entry':
                return this.startFocus({ task: b.dataset.task ? +b.dataset.task : undefined,
                    routine_entry: b.dataset.entry ? +b.dataset.entry : undefined, title: b.dataset.title });
            case 'go-workout': {
                const res = await this.api('post', 'board/api/fitness/workouts/start/', {});
                if (res.status === 'success') this.open('workout', res.data);
                return;
            }
            case 'log-instead': this.hide(); return Fitness.logWorkoutDialog();
            case 'go-focus': {
                const body = { ...(this._focusOpts || {}) };
                this.el.querySelectorAll('[data-fp-plan]').forEach(i => { body[i.dataset.fpPlan] = +i.value; });
                const res = await this.api('post', 'board/api/focus/sessions/', body);
                if (res.status === 'success') this.open('focus', res.data);
                return;
            }
            case 'pause': return this.togglePause();
            case 'prev': return this.prev();
            case 'next': return this.next(false);
            case 'done': return s && this.repPicker(s);
            case 'log': {
                // The set on screen, or (during a rest) the set just done
                let t = s;
                if (s && s.kind === 'rest') for (let i = this.idx - 1; i >= 0; i--) if (this.steps[i].exercise_id) { t = this.steps[i]; break; }
                return t && t.exercise_id && this.repPicker(t);
            }
            case 'rep':
                this._pick.reps = +b.dataset.val;
                b.parentElement.querySelectorAll('.fp-rep').forEach(x => { x.classList.toggle('on', x === b); x.setAttribute('aria-checked', x === b); });
                return;
            case 'load':
                this._pick.load = b.dataset.val;
                this.el.querySelectorAll('.fp-load').forEach(x => x.classList.toggle('on', x === b));
                { const kg = this.el.querySelector('[data-fp-f="kg"]'); if (kg) kg.value = ''; }
                return;
            case 'rir':
                this._pick.rir = this._pick.rir === +b.dataset.val ? null : +b.dataset.val;
                this.el.querySelectorAll('.fp-rir').forEach(x => x.classList.toggle('on', x === b && this._pick.rir != null));
                return;
            case 'save-set': return this.saveSet();
            case 'save-timed': {
                const v = +this.el.querySelector('[data-fp-f="seconds"]').value;
                const res = await this.logSet(s, { seconds_done: v });
                if (res.status === 'success') { this.closeSheet(); if (s.advance !== 'auto') this.next(true); }
                return;
            }
            case 'heavier':
                this.loads[s.exercise_id] = b.dataset.load;
                b.classList.add('on');
                return this.toast(`Load set to ${b.dataset.load}`);
            case 'more-rest':
                this.extra += 15;
                this.restExt += 1;
                this.beeped = {};
                if (this.restExt >= 2) {
                    const prevEx = [...this.steps.slice(0, this.idx)].reverse().find(x => x.exercise_id && !x.warmup);
                    if (prevEx) this.offerEasier(prevEx);
                }
                return this.renderClock();
            case 'guide': return this.guide();
            case 'hurts': return this.hurts();
            case 'joint': return this.pain(b.dataset.val);
            case 'easier': this.closeSheet(); return this.switchEasier(b.dataset.ex);
            case 'drop-round': this.closeSheet(); return this.dropLastRound(b.dataset.ex);
            case 'close-sheet': return this.closeSheet();
            case 'lighter': return this.finishLighter();
            case 'later':
                if (!this.paused) this.togglePause();
                this.closeSheet();
                return this.hide();
            case 'end': return this.finish('end');
            case 'done-close': return this.hide();
            case 'park': return this.sheet(`<h5>Park a thought</h5><p class="fp-muted">It goes to your todos. Back to focus.</p>
                <input type="text" class="form-control" data-fp-f="thought" maxlength="200" placeholder="Call the bank about the card">
                <div class="fp-sheet-actions"><button type="button" class="btn btn-paper" data-fp="close-sheet">Cancel</button>
                <button type="button" class="btn btn-paper btn-primary" data-fp="save-thought">Park it</button></div>`);
            case 'save-thought': {
                const t = this.el.querySelector('[data-fp-f="thought"]').value.trim();
                if (!t) return;
                const res = await this.api('post', `${this.base()}/park/`, { text: t });
                if (res.status === 'success') { this.closeSheet(); this.toast('Parked in your todos'); }
                return;
            }
            case 'distracted': {
                const res = await this.api('post', `${this.base()}/distracted/`, {});
                if (res.status === 'success') {
                    this.data.session.interruptions = res.data.interruptions;
                    const c = this.el.querySelector('[data-fp-el="intr"]');
                    if (c) c.textContent = res.data.interruptions;
                    this.toast('Noted. Back to it.');
                }
                return;
            }
            case 'done-focus': {
                const tick = this.el.querySelector('#fp-tick');
                if (tick && tick.checked && this._focusEnded) {
                    await this.api('post', `board/api/focus/sessions/${this._focusEnded.id}/tick/`, {});
                }
                return this.hide();
            }
        }
    },
};

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => FocusPlayer.init());
else FocusPlayer.init();
