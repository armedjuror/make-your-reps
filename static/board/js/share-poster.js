/**
 * share-poster.js — builds a shareable "victory" poster on a canvas, shows the
 * share sheet (themes, format, share / download / copy) and the congratulation
 * modal that offers it. Identical in the web app and the Chrome extension.
 *
 * Public API:
 *   SharePoster.open(spec)               open the share sheet right away
 *   SharePoster.celebrate(spec, copy)    queue a congratulation modal that offers the poster
 *
 * spec: { kind, tag?, label, title, subtitle?, icon (FA class), stats?: string[],
 *         dateLabel?, shareText? }
 */
const SharePoster = (() => {
    const SITE = 'makeyourreps.com';
    const BRAND = 'Make Your Reps';
    const TAGLINE = 'Build habits. Make your reps.';
    const PREFS_KEY = 'mr_poster_prefs';

    const FORMATS = {
        post: { w: 1080, h: 1350, label: 'Post' },
        story: { w: 1080, h: 1920, label: 'Story' },
    };

    // One poster look per app theme. Add a theme here and it appears in the picker.
    const THEMES = {
        ink: { name: 'Ink', font: 'Montserrat', hw: 800, bg: ['#403c37', '#040404'], text: '#e8e3d3', sub: '#918c73', accent: '#ba8238', accent2: '#d4af37', onAccent: '#1a1209', pattern: 'dots', frame: 'round', badge: 'disc' },
        terminal: { name: 'Terminal', font: 'JetBrains Mono', hw: 700, bg: ['#0f1a12', '#050806'], text: '#c8e6c9', sub: '#7fa284', accent: '#4ade80', accent2: '#a3e635', onAccent: '#04130a', pattern: 'scan', frame: 'sharp', badge: 'square' },
        tech: { name: 'Tech', font: 'Space Grotesk', hw: 700, bg: ['#0c1d44', '#040712'], text: '#dbeafe', sub: '#7d93b8', accent: '#38bdf8', accent2: '#fbbf24', onAccent: '#04152b', pattern: 'grid', frame: 'round', badge: 'disc' },
        aurora: { name: 'Aurora', font: 'Plus Jakarta Sans', hw: 800, bg: ['#ffffff', '#f4f3ff'], text: '#1e1b4b', sub: '#5f6388', accent: '#6d5ef0', accent2: '#e0a100', onAccent: '#ffffff', pattern: 'aurora', frame: 'round', badge: 'disc' },
        sensei: { name: 'Sensei', font: 'Instrument Serif', hw: 400, bg: ['#f8f4ec', '#ece5d6'], text: '#1c1b19', sub: '#756f63', accent: '#c8321f', accent2: '#a8812c', onAccent: '#fbf8f1', pattern: 'paper', frame: 'double', badge: 'hanko' },
        coach: { name: 'Coach', font: 'Barlow Condensed', hw: 700, bg: ['#141414', '#050505'], text: '#f5f5f4', sub: '#a3a3a3', accent: '#facc15', accent2: '#facc15', onAccent: '#0a0a0a', pattern: 'stripes', frame: 'bars', badge: 'square' },
        garden: { name: 'Garden', font: 'Nunito', hw: 800, bg: ['#fbfdf6', '#e2edd6'], text: '#2a3826', sub: '#66775d', accent: '#4f8a4e', accent2: '#d9a21b', onAccent: '#ffffff', pattern: 'petals', frame: 'round', badge: 'disc' },
        orbit: { name: 'Orbit', font: 'Space Mono', hw: 700, bg: ['#130d2b', '#04030a'], text: '#ece8ff', sub: '#8f89b0', accent: '#b794ff', accent2: '#fcd34d', onAccent: '#12082b', pattern: 'stars', frame: 'round', badge: 'disc' },
        quest: { name: 'Quest', font: 'DotGothic16', hw: 400, bg: ['#6ec5ff', '#bfe8ff'], text: '#1a1a2e', sub: '#3d4468', accent: '#e4372c', accent2: '#fbd000', label: '#b3261b', onAccent: '#ffffff', pattern: 'pixels', frame: 'thick', badge: 'square' },
    };

    // ───────────── helpers ─────────────
    const loadPrefs = () => { try { return JSON.parse(localStorage.getItem(PREFS_KEY)) || {}; } catch (e) { return {}; } };
    const savePrefs = (p) => { try { localStorage.setItem(PREFS_KEY, JSON.stringify(p)); } catch (e) { /* storage unavailable */ } };

    const hexToRgb = (hex) => {
        const h = hex.replace('#', '');
        const n = parseInt(h.length === 3 ? h.split('').map(c => c + c).join('') : h, 16);
        return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
    };
    const rgba = (hex, a) => { const [r, g, b] = hexToRgb(hex); return `rgba(${r},${g},${b},${a})`; };

    const rng = (seed) => () => {           // mulberry32: same poster every render
        seed |= 0; seed = seed + 0x6D2B79F5 | 0;
        let t = Math.imul(seed ^ seed >>> 15, 1 | seed);
        t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
        return ((t ^ t >>> 14) >>> 0) / 4294967296;
    };

    function rr(ctx, x, y, w, h, r) {
        ctx.beginPath();
        if (r <= 0) { ctx.rect(x, y, w, h); return; }
        r = Math.min(r, w / 2, h / 2);
        ctx.moveTo(x + r, y);
        ctx.arcTo(x + w, y, x + w, y + h, r);
        ctx.arcTo(x + w, y + h, x, y + h, r);
        ctx.arcTo(x, y + h, x, y, r);
        ctx.arcTo(x, y, x + w, y, r);
        ctx.closePath();
    }

    function wrap(ctx, text, maxW) {
        const words = String(text).split(/\s+/).filter(Boolean);
        const lines = [];
        let cur = '';
        for (const w of words) {
            const t = cur ? cur + ' ' + w : w;
            if (ctx.measureText(t).width <= maxW || !cur) cur = t;
            else { lines.push(cur); cur = w; }
        }
        if (cur) lines.push(cur);
        return lines;
    }

    function ellipsize(ctx, line, maxW) {
        if (ctx.measureText(line).width <= maxW) return line;
        while (line.length > 1 && ctx.measureText(line + '…').width > maxW) line = line.slice(0, -1);
        return line.trimEnd() + '…';
    }

    function fitBlock(ctx, text, fam, weight, maxW, maxH, maxF, minF, maxLines, lh) {
        for (let f = maxF; f >= minF; f -= 4) {
            ctx.font = `${weight} ${f}px ${fam}`;
            const lines = wrap(ctx, text, maxW);
            const widest = Math.max(...lines.map(l => ctx.measureText(l).width));
            if (lines.length <= maxLines && widest <= maxW && lines.length * f * lh <= maxH) return { f, lines };
        }
        ctx.font = `${weight} ${minF}px ${fam}`;
        let lines = wrap(ctx, text, maxW);
        if (lines.length > maxLines) {
            lines = lines.slice(0, maxLines);
            lines[maxLines - 1] = ellipsize(ctx, lines[maxLines - 1] + ' …', maxW);
        }
        return { f: minF, lines: lines.map(l => ellipsize(ctx, l, maxW)) };
    }

    /** Resolve a Font Awesome class ("fas fa-trophy") to a glyph the canvas can draw. */
    function resolveIcon(cls) {
        if (!cls) return null;
        const el = document.createElement('i');
        el.className = cls;
        el.style.cssText = 'position:absolute;visibility:hidden;left:-9999px;top:0';
        document.body.appendChild(el);
        const before = getComputedStyle(el, '::before');
        const cs = getComputedStyle(el);
        const m = /^\s*(["'])([\s\S]*?)\1/.exec(before.content || '');
        const char = m ? m[2] : '';
        const family = before.fontFamily || cs.fontFamily;
        const weight = before.fontWeight || cs.fontWeight;
        el.remove();
        if (!char) return null;
        return { char, family, weight };
    }

    async function loadFonts(font, icon) {
        const jobs = [
            document.fonts.load(`400 40px "${font}"`),
            document.fonts.load(`700 40px "${font}"`),
            document.fonts.load(`800 40px "${font}"`),
        ];
        if (icon) jobs.push(document.fonts.load(`${icon.weight} 40px ${icon.family}`, icon.char));
        try {
            await Promise.race([Promise.all(jobs), new Promise(r => setTimeout(r, 2500))]);
        } catch (e) { /* fall back to system fonts */ }
    }

    // ───────────── backgrounds ─────────────
    function drawBackground(ctx, T, W, H) {
        const g = ctx.createRadialGradient(W / 2, H * 0.32, 60, W / 2, H * 0.32, Math.max(W, H) * 0.85);
        g.addColorStop(0, T.bg[0]);
        g.addColorStop(1, T.bg[1]);
        ctx.fillStyle = g;
        ctx.fillRect(0, 0, W, H);

        const rand = rng(7);
        switch (T.pattern) {
            case 'dots':
                ctx.fillStyle = rgba(T.accent, 0.13);
                for (let y = 30; y < H; y += 44) for (let x = 30; x < W; x += 44) { ctx.beginPath(); ctx.arc(x, y, 2, 0, 7); ctx.fill(); }
                break;
            case 'scan':
                ctx.fillStyle = rgba(T.accent, 0.06);
                for (let y = 0; y < H; y += 6) ctx.fillRect(0, y, W, 2);
                break;
            case 'grid':
                ctx.strokeStyle = rgba(T.accent, 0.09);
                ctx.lineWidth = 2;
                for (let x = 0; x < W; x += 72) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke(); }
                for (let y = 0; y < H; y += 72) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke(); }
                break;
            case 'aurora':
                [[0.15, 0.12, '#6d5ef0', 0.28], [0.85, 0.4, '#22d3ee', 0.22], [0.3, 0.85, '#f472b6', 0.2]].forEach(([fx, fy, c, a]) => {
                    const r = ctx.createRadialGradient(W * fx, H * fy, 0, W * fx, H * fy, W * 0.75);
                    r.addColorStop(0, rgba(c, a)); r.addColorStop(1, rgba(c, 0));
                    ctx.fillStyle = r; ctx.fillRect(0, 0, W, H);
                });
                break;
            case 'paper':
                ctx.fillStyle = rgba('#1c1b19', 0.05);
                for (let i = 0; i < 900; i++) ctx.fillRect(rand() * W, rand() * H, 2, 2);
                break;
            case 'stripes':
                ctx.save();
                ctx.rotate(-Math.PI / 4);
                ctx.fillStyle = rgba(T.accent, 0.06);
                for (let x = -H; x < W + H; x += 90) ctx.fillRect(x, -H, 36, H * 3);
                ctx.restore();
                break;
            case 'petals':
                for (let i = 0; i < 26; i++) {
                    ctx.fillStyle = rgba(i % 3 ? '#4f8a4e' : '#f4a6c0', 0.14 + rand() * 0.1);
                    ctx.beginPath(); ctx.ellipse(rand() * W, rand() * H, 20 + rand() * 40, 10 + rand() * 22, rand() * 3, 0, 7); ctx.fill();
                }
                break;
            case 'stars':
                for (let i = 0; i < 160; i++) {
                    ctx.fillStyle = rgba('#ffffff', 0.15 + rand() * 0.6);
                    const s = rand() < 0.1 ? 3.5 : 1.8;
                    ctx.beginPath(); ctx.arc(rand() * W, rand() * H, s, 0, 7); ctx.fill();
                }
                break;
            case 'pixels': {
                ctx.strokeStyle = 'rgba(255,255,255,0.22)';
                ctx.lineWidth = 3;
                for (let x = 0; x < W; x += 54) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke(); }
                for (let y = 0; y < H; y += 54) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke(); }
                const gh = 40;
                ctx.fillStyle = '#6fc24f'; ctx.fillRect(0, H - gh, W, gh);
                ctx.fillStyle = '#9be07a'; ctx.fillRect(0, H - gh, W, 18);
                ctx.fillStyle = '#1a1a2e'; ctx.fillRect(0, H - gh - 6, W, 6);
                break;
            }
        }
    }

    function drawFrame(ctx, T, W, H) {
        const i = 44;
        ctx.lineWidth = 3;
        ctx.strokeStyle = rgba(T.accent, 0.65);
        switch (T.frame) {
            case 'round': rr(ctx, i, i, W - i * 2, H - i * 2, 30); ctx.stroke(); break;
            case 'sharp': ctx.lineWidth = 2; rr(ctx, i, i, W - i * 2, H - i * 2, 4); ctx.stroke(); break;
            case 'double':
                ctx.strokeStyle = rgba(T.text, 0.55);
                rr(ctx, i, i, W - i * 2, H - i * 2, 0); ctx.stroke();
                ctx.lineWidth = 1.5; rr(ctx, i + 14, i + 14, W - (i + 14) * 2, H - (i + 14) * 2, 0); ctx.stroke();
                break;
            case 'thick': ctx.lineWidth = 10; ctx.strokeStyle = '#1a1a2e'; rr(ctx, 30, 30, W - 60, H - 60, 0); ctx.stroke(); break;
            case 'bars':
                ctx.fillStyle = T.accent;
                ctx.fillRect(0, 0, W, 30);
                ctx.fillRect(0, H - 30, W, 30);
                break;
        }
    }

    function drawBadge(ctx, T, cx, cy, r, icon, glyphSize) {
        // soft halo
        const halo = ctx.createRadialGradient(cx, cy, r * 0.6, cx, cy, r * 1.6);
        halo.addColorStop(0, rgba(T.accent, 0.28)); halo.addColorStop(1, rgba(T.accent, 0));
        ctx.fillStyle = halo; ctx.fillRect(cx - r * 2, cy - r * 2, r * 4, r * 4);

        ctx.save();
        if (T.badge === 'disc') {
            ctx.strokeStyle = rgba(T.accent, 0.4); ctx.lineWidth = 4;
            ctx.beginPath(); ctx.arc(cx, cy, r + 26, 0, 7); ctx.stroke();
            ctx.fillStyle = T.accent;
            ctx.beginPath(); ctx.arc(cx, cy, r, 0, 7); ctx.fill();
        } else {
            const rad = T.badge === 'hanko' ? 26 : (T.frame === 'thick' ? 0 : 14);
            if (T.badge === 'square' && T.frame === 'thick') { ctx.fillStyle = '#1a1a2e'; ctx.fillRect(cx - r + 12, cy - r + 12, r * 2, r * 2); }
            ctx.fillStyle = T.accent;
            rr(ctx, cx - r, cy - r, r * 2, r * 2, rad); ctx.fill();
            if (T.badge === 'hanko') { ctx.strokeStyle = rgba(T.onAccent, 0.55); ctx.lineWidth = 5; rr(ctx, cx - r + 14, cy - r + 14, r * 2 - 28, r * 2 - 28, 14); ctx.stroke(); }
        }
        ctx.restore();

        ctx.fillStyle = T.onAccent;
        ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
        if (icon) {
            ctx.font = `${icon.weight} ${glyphSize}px ${icon.family}`;
            ctx.fillText(icon.char, cx, cy + 4);
        } else {
            ctx.font = `700 ${glyphSize}px sans-serif`;
            ctx.fillText('★', cx, cy + 4);
        }
    }

    // ───────────── the poster ─────────────
    async function draw(canvas, spec, themeKey, fmtKey, showName) {
        const T = THEMES[themeKey] || THEMES.ink;
        const F = FORMATS[fmtKey] || FORMATS.post;
        const W = F.w, H = F.h;
        const oy = (H - 1350) / 2;            // story format: same layout, centred vertically
        const cx = W / 2;
        const icon = resolveIcon(spec.icon);
        await loadFonts(T.font, icon);

        canvas.width = W; canvas.height = H;
        const ctx = canvas.getContext('2d');
        const fam = `"${T.font}", "Montserrat", system-ui, sans-serif`;
        const spaced = (px) => { if ('letterSpacing' in ctx) ctx.letterSpacing = px + 'px'; };

        drawBackground(ctx, T, W, H);
        drawFrame(ctx, T, W, H);

        ctx.textAlign = 'center'; ctx.textBaseline = 'alphabetic';

        // brand
        ctx.fillStyle = T.accent; ctx.font = `700 32px ${fam}`; spaced(7);
        ctx.fillText(BRAND.toUpperCase(), cx, oy + 130);

        // badge
        drawBadge(ctx, T, cx, oy + 340, 135, icon, 130);

        // label
        ctx.fillStyle = T.label || T.accent2; ctx.font = `700 34px ${fam}`; spaced(8);
        ctx.fillText(String(spec.label || '').toUpperCase(), cx, oy + 572);
        spaced(0);

        // title + subtitle block, centred in a fixed zone
        const zoneTop = oy + 625, zoneH = 395, maxW = 880;
        const subLines = [];
        if (spec.subtitle) {
            ctx.font = `400 36px ${fam}`;
            wrap(ctx, spec.subtitle, 820).slice(0, 2).forEach((l, i, a) => subLines.push(i === a.length - 1 ? ellipsize(ctx, l, 820) : l));
        }
        const subH = subLines.length ? subLines.length * 48 + 30 : 0;
        const title = fitBlock(ctx, spec.title || '', fam, T.hw, maxW, zoneH - subH, 170, 52, 3, 1.1);
        const titleH = title.lines.length * title.f * 1.1;
        let y = zoneTop + (zoneH - (titleH + subH)) / 2;

        ctx.fillStyle = T.text; ctx.font = `${T.hw} ${title.f}px ${fam}`;
        title.lines.forEach(l => { y += title.f * 1.1; ctx.fillText(l, cx, y - title.f * 0.18); });

        if (subLines.length) {
            ctx.fillStyle = T.sub; ctx.font = `400 36px ${fam}`;
            y += 30;
            subLines.forEach(l => { y += 48; ctx.fillText(l, cx, y - 10); });
        }

        // stat chips: one row, shrink text to fit, drop the last chip as a final resort
        let chips = (spec.stats || []).filter(Boolean).slice(0, 4);
        if (chips.length) {
            const GAP = 14, MAXROW = 920;
            let font = 28, widths = [];
            const measure = () => { ctx.font = `600 ${font}px ${fam}`; widths = chips.map(c => ctx.measureText(c).width + font * 1.7); return widths.reduce((a, b) => a + b, 0) + GAP * (chips.length - 1); };
            while (measure() > MAXROW && font > 20) font -= 1;
            while (measure() > MAXROW && chips.length > 1) chips = chips.slice(0, -1);
            const total = measure();
            const ph = font * 2.1;
            let x = cx - total / 2;
            const cy = oy + 1030;
            chips.forEach((c, i) => {
                ctx.fillStyle = rgba(T.accent, 0.14); rr(ctx, x, cy, widths[i], ph, T.frame === 'thick' || T.frame === 'sharp' ? 4 : ph / 2); ctx.fill();
                ctx.strokeStyle = rgba(T.accent, 0.55); ctx.lineWidth = 2; ctx.stroke();
                ctx.fillStyle = T.text; ctx.textBaseline = 'middle'; ctx.fillText(c, x + widths[i] / 2, cy + ph / 2 + 1);
                x += widths[i] + GAP;
            });
            ctx.textBaseline = 'alphabetic';
        }

        // name · date
        const who = showName && AppName() ? AppName() + ' · ' : '';
        const when = spec.dateLabel || new Date().toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
        ctx.fillStyle = T.sub; ctx.font = `500 30px ${fam}`;
        ctx.fillText(ellipsize(ctx, who + when, 860), cx, oy + 1160);

        // footer
        ctx.strokeStyle = rgba(T.text, 0.18); ctx.lineWidth = 2;
        ctx.beginPath(); ctx.moveTo(cx - 140, oy + 1190); ctx.lineTo(cx + 140, oy + 1190); ctx.stroke();
        ctx.fillStyle = T.text; ctx.font = `${T.hw} 46px ${fam}`;
        ctx.fillText(SITE, cx, oy + 1245);
        ctx.fillStyle = T.sub; ctx.font = `500 26px ${fam}`; spaced(2);
        ctx.fillText(TAGLINE, cx, oy + 1286);
        spaced(0);
    }

    function AppName() {
        try { return (AppConfig.userDetail.first_name || '').trim(); } catch (e) { return ''; }
    }

    // ───────────── links & text ─────────────
    function buildUrl(spec, themeKey) {
        const q = new URLSearchParams({
            ref: 'share', utm_source: 'poster', utm_medium: 'share',
            utm_campaign: spec.kind || 'win', utm_content: themeKey || 'ink',
        });
        if (spec.tag) q.set('utm_term', spec.tag);
        return `https://${SITE}/?${q.toString()}`;
    }
    const shareText = (spec) => spec.shareText || `Making my reps count on ${BRAND}: ${spec.title}`;

    // ───────────── share sheet ─────────────
    let sheetOpen = false;

    function el(tag, cls, text) {
        const e = document.createElement(tag);
        if (cls) e.className = cls;
        if (text != null) e.textContent = text;
        return e;
    }

    function open(spec, onClose) {
        if (sheetOpen) return;
        sheetOpen = true;
        const prefs = loadPrefs();
        const current = (typeof Theme !== 'undefined' && Theme.current) ? Theme.current() : 'ink';
        const state = {
            theme: THEMES[prefs.theme] ? prefs.theme : (THEMES[current] ? current : 'ink'),
            fmt: FORMATS[prefs.fmt] ? prefs.fmt : 'post',
            name: prefs.name !== false,
        };

        const overlay = el('div', 'sp-overlay');
        overlay.setAttribute('role', 'dialog'); overlay.setAttribute('aria-modal', 'true'); overlay.setAttribute('aria-label', 'Share your win');
        const sheet = el('div', 'sp-sheet');
        const close = el('button', 'sp-close', '×'); close.type = 'button'; close.setAttribute('aria-label', 'Close');

        const preview = el('div', 'sp-preview');
        const canvas = el('canvas', 'sp-canvas');
        const loading = el('div', 'sp-loading', 'Making your poster…');
        preview.append(canvas, loading);

        const controls = el('div', 'sp-controls');
        controls.append(el('div', 'sp-heading', 'Share your win'));

        const themeRow = el('div', 'sp-row sp-themes'); themeRow.setAttribute('role', 'radiogroup'); themeRow.setAttribute('aria-label', 'Poster theme');
        const themeBtns = {};
        Object.entries(THEMES).forEach(([key, T]) => {
            const b = el('button', 'sp-theme'); b.type = 'button'; b.title = T.name; b.setAttribute('aria-label', T.name + ' theme');
            b.style.background = `linear-gradient(135deg, ${T.bg[0]} 0 55%, ${T.accent} 55% 100%)`;
            b.addEventListener('click', () => { state.theme = key; sync(); });
            themeBtns[key] = b; themeRow.append(b);
        });

        const optRow = el('div', 'sp-row sp-opts');
        const seg = el('div', 'sp-seg');
        const fmtBtns = {};
        Object.entries(FORMATS).forEach(([key, F]) => {
            const b = el('button', '', F.label); b.type = 'button';
            b.addEventListener('click', () => { state.fmt = key; sync(); });
            fmtBtns[key] = b; seg.append(b);
        });
        const nameLabel = el('label', 'sp-check');
        const nameBox = el('input'); nameBox.type = 'checkbox';
        nameLabel.append(nameBox, document.createTextNode(' Show my first name'));
        nameBox.addEventListener('change', () => { state.name = nameBox.checked; sync(); });
        optRow.append(seg);
        if (AppName()) optRow.append(nameLabel);

        const actions = el('div', 'sp-row sp-actions');
        const btnShare = el('button', 'btn btn-paper btn-primary sp-btn', 'Share'); btnShare.type = 'button';
        const btnDown = el('button', 'btn btn-paper sp-btn', 'Download'); btnDown.type = 'button';
        const btnCopy = el('button', 'btn btn-paper sp-btn', 'Copy image'); btnCopy.type = 'button';
        if (!navigator.share) btnShare.style.display = 'none';
        actions.append(btnShare, btnDown, btnCopy);

        const links = el('div', 'sp-row sp-links');
        links.append(el('span', 'sp-links-label', 'Post a link:'));
        const aWa = el('a', 'sp-link', 'WhatsApp'), aX = el('a', 'sp-link', 'X'), aLi = el('a', 'sp-link', 'LinkedIn');
        [aWa, aX, aLi].forEach(a => { a.target = '_blank'; a.rel = 'noopener noreferrer'; });
        const btnLink = el('button', 'sp-link', 'Copy link'); btnLink.type = 'button';
        links.append(aWa, aX, aLi, btnLink);

        const note = el('div', 'sp-note', 'Links can’t carry the picture. Download or copy the poster first, then attach it to your post.');
        const toast = el('div', 'sp-toast'); toast.setAttribute('role', 'status');

        controls.append(themeRow, optRow, actions, links, note, toast);
        sheet.append(close, preview, controls);
        overlay.append(sheet);
        document.body.append(overlay);
        document.body.classList.add('sp-lock');

        let token = 0, toastTimer = null;
        const say = (msg) => {
            toast.textContent = msg; toast.classList.add('on');
            clearTimeout(toastTimer); toastTimer = setTimeout(() => toast.classList.remove('on'), 3200);
        };
        const url = () => buildUrl(spec, state.theme);
        const fileName = () => `makeyourreps-${(spec.kind || 'win')}-${state.theme}-${state.fmt}.png`;
        const blobOf = () => new Promise(res => canvas.toBlob(res, 'image/png'));

        async function sync() {
            const my = ++token;
            Object.entries(themeBtns).forEach(([k, b]) => { b.classList.toggle('on', k === state.theme); b.setAttribute('aria-pressed', k === state.theme); });
            Object.entries(fmtBtns).forEach(([k, b]) => b.classList.toggle('on', k === state.fmt));
            nameBox.checked = state.name;
            canvas.classList.toggle('story', state.fmt === 'story');
            const text = shareText(spec);
            aWa.href = `https://wa.me/?text=${encodeURIComponent(text + ' ' + url())}`;
            aX.href = `https://twitter.com/intent/tweet?text=${encodeURIComponent(text)}&url=${encodeURIComponent(url())}`;
            aLi.href = `https://www.linkedin.com/sharing/share-offsite/?url=${encodeURIComponent(url())}`;
            savePrefs({ theme: state.theme, fmt: state.fmt, name: state.name });
            loading.style.display = 'flex';
            try { await draw(canvas, spec, state.theme, state.fmt, state.name); } catch (e) { say('Could not draw the poster.'); }
            if (my === token) loading.style.display = 'none';
        }

        btnDown.addEventListener('click', async () => {
            const blob = await blobOf();
            const a = document.createElement('a');
            a.href = URL.createObjectURL(blob); a.download = fileName();
            document.body.append(a); a.click(); a.remove();
            setTimeout(() => URL.revokeObjectURL(a.href), 4000);
            say('Poster saved.');
        });
        btnCopy.addEventListener('click', async () => {
            try {
                const blob = await blobOf();
                await navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })]);
                say('Poster copied. Paste it into your post.');
            } catch (e) { say('Copy isn’t supported here. Use Download instead.'); }
        });
        btnLink.addEventListener('click', async () => {
            try { await navigator.clipboard.writeText(url()); say('Link copied.'); } catch (e) { say(url()); }
        });
        btnShare.addEventListener('click', async () => {
            const blob = await blobOf();
            const file = new File([blob], fileName(), { type: 'image/png' });
            const data = { files: [file], title: BRAND, text: `${shareText(spec)} ${url()}` };
            try {
                if (navigator.canShare && navigator.canShare(data)) {
                    await navigator.share(data);
                } else {
                    btnDown.click();                      // can’t attach files here: save it, share the link
                    await navigator.share({ title: BRAND, text: shareText(spec), url: url() });
                }
            } catch (e) { if (e && e.name !== 'AbortError') say('Sharing didn’t work. Use Download or Copy instead.'); }
        });

        function onKey(e) { if (e.key === 'Escape') shut(); }
        function shut() {
            token++;
            document.removeEventListener('keydown', onKey);
            overlay.remove();
            document.body.classList.remove('sp-lock');
            sheetOpen = false;
            if (typeof onClose === 'function') onClose();
            setTimeout(pump, 300);               // a win queued while the sheet was open
        }
        close.addEventListener('click', shut);
        overlay.addEventListener('mousedown', (e) => { if (e.target === overlay) shut(); });
        document.addEventListener('keydown', onKey);
        sync();
        close.focus();
    }

    // ───────────── congratulation modal (queued) ─────────────
    const queue = [];
    let busy = false;

    function celebrate(spec, copy) {
        queue.push({ spec, copy: copy || {} });
        pump();
    }

    function pump() {
        if (busy || sheetOpen || !queue.length) return;
        busy = true;
        const { spec, copy } = queue.shift();
        showCongrats(spec, copy, () => { busy = false; setTimeout(pump, 300); });
    }

    function showCongrats(spec, copy, done) {
        const overlay = el('div', 'sp-overlay sp-celebrate');
        overlay.setAttribute('role', 'dialog'); overlay.setAttribute('aria-modal', 'true');
        const confetti = el('canvas', 'sp-confetti');
        const card = el('div', 'sp-cel');
        const ic = el('div', 'sp-cel-icon'); const i = el('i'); i.className = spec.icon || 'fas fa-trophy'; ic.append(i);
        const h = el('h3', 'sp-cel-title', copy.heading || 'Congratulations!');
        const p = el('p', 'sp-cel-text', copy.message || spec.title);
        const row = el('div', 'sp-cel-actions');
        const yes = el('button', 'btn btn-paper btn-primary', 'Share your victory'); yes.type = 'button';
        const no = el('button', 'btn btn-paper', 'Not now'); no.type = 'button';
        row.append(yes, no);
        card.append(ic, h, p, row);
        overlay.append(confetti, card);
        document.body.append(overlay);

        const stop = startConfetti(confetti);
        function onKey(e) { if (e.key === 'Escape') later(); }
        function teardown() { stop(); document.removeEventListener('keydown', onKey); overlay.remove(); }
        function later() { teardown(); done(); }
        yes.addEventListener('click', () => { teardown(); open(spec, done); });
        no.addEventListener('click', later);
        overlay.addEventListener('mousedown', (e) => { if (e.target === overlay) later(); });
        document.addEventListener('keydown', onKey);
        yes.focus();
    }

    function startConfetti(canvas) {
        if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return () => { };
        const root = getComputedStyle(document.documentElement);
        const colors = ['--ink-brown', '--gold', '--ink-green', '--ink-red'].map(v => root.getPropertyValue(v).trim()).filter(Boolean);
        if (!colors.length) colors.push('#ba8238', '#d4af37');
        const ctx = canvas.getContext('2d');
        const W = canvas.width = window.innerWidth, H = canvas.height = window.innerHeight;
        const parts = Array.from({ length: 110 }, () => ({
            x: W / 2 + (Math.random() - 0.5) * 120, y: H * 0.42,
            vx: (Math.random() - 0.5) * 16, vy: -Math.random() * 15 - 4,
            s: 6 + Math.random() * 8, r: Math.random() * 6, vr: (Math.random() - 0.5) * 0.4,
            c: colors[Math.floor(Math.random() * colors.length)],
        }));
        let raf = 0, alive = true; const t0 = performance.now();
        (function tick(now) {
            if (!alive) return;
            ctx.clearRect(0, 0, W, H);
            const fade = Math.max(0, 1 - (now - t0 - 1800) / 900);
            parts.forEach(p => {
                p.vy += 0.35; p.x += p.vx; p.y += p.vy; p.r += p.vr; p.vx *= 0.99;
                ctx.save(); ctx.globalAlpha = fade; ctx.translate(p.x, p.y); ctx.rotate(p.r);
                ctx.fillStyle = p.c; ctx.fillRect(-p.s / 2, -p.s / 4, p.s, p.s / 2); ctx.restore();
            });
            if (fade > 0) raf = requestAnimationFrame(tick);
        })(t0);
        return () => { alive = false; cancelAnimationFrame(raf); };
    }

    return { open, celebrate, themes: THEMES, buildUrl };
})();
