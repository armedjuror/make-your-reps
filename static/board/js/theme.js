/**
 * theme.js — Theme switching.
 *
 * The active theme lives on <html data-theme="...">. CSS variables for each
 * theme are defined in style.css. The last-used theme is cached in
 * localStorage so the inline script in <head> can apply it before first paint.
 * Must be loaded before config.js.
 */

const Theme = {
    storageKey: 'mr_theme',
    fallback: 'ink',
    all: ['ink', 'terminal', 'tech', 'aurora', 'sensei', 'coach', 'garden', 'orbit', 'quest'],
    // Each theme ships with a font that suits it. Picking a theme applies that
    // font; the user can still pick another one afterwards in Settings.
    fonts: {
        ink: 'Montserrat', terminal: 'JetBrains Mono', tech: 'Space Grotesk', aurora: 'Plus Jakarta Sans',
        sensei: 'Instrument Serif', coach: 'Barlow Condensed', garden: 'Nunito', orbit: 'Space Mono', quest: 'DotGothic16',
    },
    // Small bits of wording that change with the theme's personality.
    copy: {
        _: { now: 'NOW', next: (u) => `NEXT · IN ${u}`, overdue: 'Overdue' },
        terminal: { now: 'NOW', next: (u) => `NEXT · T+${u}`, overdue: 'Errors' },
        tech: { now: 'NOW', next: (u) => `QUEUED · ${u}`, overdue: 'Overdue' },
        sensei: { now: 'now', next: (u) => `next · in ${u}`.toLowerCase(), overdue: 'Left undone' },
        coach: { now: 'NOW', next: (u) => `UP NEXT · ${u}`, overdue: 'Missed reps' },
        garden: { now: 'now', next: (u) => `next · in ${u}`, overdue: 'Needs water' },
        orbit: { now: 'T-0', next: (u) => `T-MINUS ${u}`, overdue: 'Anomalies' },
        quest: { now: 'YOU ARE HERE', next: (u) => `NEXT QUEST · ${u}`, overdue: 'Unfinished quests' },
    },
    // Older theme names, mapped to the closest current one.
    legacy: { dark: 'ink', light: 'aurora', paper: 'aurora', plain: 'aurora' },

    normalize(theme) {
        const t = this.legacy[theme] || theme;
        return this.all.includes(t) ? t : this.fallback;
    },

    text(key, ...args) {
        const c = this.copy[this.current()] || {};
        const v = (key in c) ? c[key] : this.copy._[key];
        return typeof v === 'function' ? v(...args) : v;
    },

    current() {
        return document.documentElement.getAttribute('data-theme') || this.fallback;
    },

    /** Apply a theme to the page and remember it locally. Does not save to the server. */
    apply(theme) {
        const t = this.normalize(theme);
        document.documentElement.setAttribute('data-theme', t);
        try { localStorage.setItem(this.storageKey, t); } catch (e) { /* storage unavailable */ }
        this.syncPicker();
        return t;
    },

    /** Apply a theme and save it to the user's account. */
    set(theme) {
        const t = this.apply(theme);
        const font = this.fonts[t];
        if (typeof AppConfig !== 'undefined' && AppConfig.userDetail) {
            AppConfig.userDetail.default_theme = t;
            if (font) AppConfig.userDetail.font_family = font;
        }
        // The theme's own font comes with it; Settings > Font can still override it.
        if (font && typeof applyFont === 'function') {
            applyFont(font);
            const sel = document.getElementById('fontSelect');
            if (sel) sel.value = font;
        }
        apiClient.put('board/api/user_details/', font ? { default_theme: t, font_family: font } : { default_theme: t }, { silent: true });
        if (typeof Greeting !== 'undefined') Greeting.schedule();
        if (typeof Timeline !== 'undefined' && Timeline.events && Timeline.events.length) Timeline.render();
        return t;
    },

    // ── Completion effect: each theme celebrates in its own way ──
    fx: {
        terminal: { cls: 'mr-fx-term', html: () => '[ ok ]', ms: 900 },
        tech: { cls: 'mr-fx-tech', html: () => '', ms: 900 },
        aurora: { cls: 'mr-fx-aurora', html: () => '✦', ms: 1100 },
        sensei: { cls: 'mr-fx-hanko', html: () => 'done', ms: 1200 },
        coach: { cls: 'mr-fx-coach', html: () => '+1 REP', ms: 900, shake: true },
        garden: { cls: 'mr-fx-garden', html: () => '🌸', ms: 1500 },
        orbit: { cls: 'mr-fx-orbit', html: () => '<span>NOMINAL</span>', ms: 1200 },
        quest: { cls: 'mr-fx-quest', html: (pts) => `+${pts || 10} XP`, ms: 1100 },
    },

    celebrate(points) {
        const fx = this.fx[this.current()];
        if (!fx) return;
        try {
            if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
            const el = document.createElement('div');
            el.className = `mr-fx ${fx.cls}`;
            el.setAttribute('aria-hidden', 'true');
            el.innerHTML = fx.html(points);
            document.body.appendChild(el);
            if (fx.shake) {
                document.body.classList.add('mr-shake');
                setTimeout(() => document.body.classList.remove('mr-shake'), 350);
            }
            setTimeout(() => el.remove(), fx.ms + 100);
        } catch (e) { /* purely decorative */ }
    },

    /** Reflect the active theme in the settings picker. */
    syncPicker() {
        const active = this.current();
        document.querySelectorAll('.theme-swatch[data-theme-value]').forEach(btn => {
            const on = btn.dataset.themeValue === active;
            btn.setAttribute('aria-pressed', on ? 'true' : 'false');
            btn.classList.toggle('active', on);
        });
    },

    bindPicker() {
        document.querySelectorAll('.theme-swatch[data-theme-value]').forEach(btn => {
            btn.addEventListener('click', () => this.set(btn.dataset.themeValue));
        });
        this.syncPicker();
    },

    /** Open Settings and bring the theme picker into view. */
    openAppearance() {
        switchPane('settings');
        const target = document.getElementById('theme-picker');
        if (target) setTimeout(() => target.scrollIntoView({ behavior: 'smooth', block: 'center' }), 120);
    },
};
