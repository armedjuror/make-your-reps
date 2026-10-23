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
    all: ['ink', 'paper', 'terminal', 'plain'],
    // Legacy values stored before the four-theme system existed.
    legacy: { dark: 'ink', light: 'paper' },

    normalize(theme) {
        const t = this.legacy[theme] || theme;
        return this.all.includes(t) ? t : this.fallback;
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
        if (typeof AppConfig !== 'undefined' && AppConfig.userDetail) {
            AppConfig.userDetail.default_theme = t;
        }
        apiClient.put('board/api/user_details/', { default_theme: t });
        return t;
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
