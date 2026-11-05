/**
 * setup.js — First-run setup and the guided tour.
 *
 * Setup asks a few questions the way the rest of the app talks (sentences you
 * fill in), then creates habits, trackers and a starter routine in one call.
 * The tour then points at the real parts of the page, one at a time.
 * No inline handlers (works under the extension's MV3 CSP).
 */
const Setup = {
    HABITS: [
        { habit: 'Drink a glass of water', detail: 'right after I wake up', identity: 'someone who looks after their body', when: 'wake' },
        { habit: 'Meditate for 2 minutes', detail: 'after I wake up', identity: 'a calm person', when: 'wake' },
        { habit: 'Stretch for 5 minutes', detail: 'every morning', identity: 'someone who moves well', when: 'wake' },
        { habit: 'Walk for 10 minutes', detail: 'after lunch', identity: 'an active person', at: '13:30' },
        { habit: 'Read a page', detail: 'before bed', identity: 'a reader', when: 'bed', offset: -45 },
        { habit: 'Plan tomorrow', detail: 'in the evening', identity: 'someone who is ready for the day', when: 'bed', offset: -90 },
        { habit: 'Write in my journal', detail: 'before I sleep', identity: 'a reflective person', when: 'bed', offset: -30 },
        { habit: 'Learn something new', detail: 'for 10 minutes a day', identity: 'a lifelong learner', at: '19:00' },
    ],
    TRACKERS: [
        { name: 'Water', unit: 'l', kind: 'additive', direction: 'at_least', target: 3, quick_steps: [0.25, 0.5] },
        { name: 'Coffee', unit: 'cups', kind: 'counter', direction: 'at_most', target: 3, quick_steps: [1] },
        { name: 'Screen time', unit: 'min', kind: 'additive', direction: 'at_most', target: 120, quick_steps: [15, 30] },
        { name: 'Steps', unit: 'steps', kind: 'single', direction: 'at_least', target: 8000, quick_steps: [] },
        { name: 'Pages read', unit: 'pages', kind: 'additive', direction: 'at_least', target: 10, quick_steps: [1, 5, 10] },
        { name: 'Workouts', unit: '', kind: 'counter', direction: 'at_least', target: 1, quick_steps: [1] },
        { name: 'Mood', unit: '/5', kind: 'single', direction: 'at_least', target: 3, quick_steps: [] },
    ],

    // ── Setup questions ──────────────────────────────────────
    start() {
        const R = Resilient;
        const name = (typeof AppConfig !== 'undefined' && AppConfig.userDetail && AppConfig.userDetail.first_name) || '';
        const chip = (group, label, on) => `<button type="button" class="freq-day-btn rs-pick-chip ${on ? 'active' : ''}" data-group="${group}" data-label="${esc(label)}">${esc(label)}</button>`;
        const days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
        const pages = [
            R.lead(`Hi${name ? ' ' + esc(name) : ''}! I&rsquo;ll help you build a routine that holds up on good days and bad. A few quick questions first.`) +
            R.say({ msg: 'Trying it out keeps things relaxed. Steady counts any day you show up. All in only counts days you finish your essentials and anchors.',
                    html: `I&rsquo;m ${R.pick('data-s="seriousness"', 'steady', [['trying', 'just trying it out'], ['steady', 'building steady habits'], ['all_in', 'all in']])}.` }),

            R.lead('Which habits do you want to start? Pick a few small ones. Two minutes a day is plenty to begin with.') +
            `<div class="rs-pick" data-pickgroup="habits">${this.HABITS.map((h, i) => chip('habits', h.habit, i === 0 || i === 4)).join('')}</div>` +
            R.say(`Or my own: I will <input type="text" class="form-input" data-own="habits" maxlength="80" placeholder="do one push-up"> <button type="button" class="btn btn-paper btn-sm" data-add="habits">Add</button>`),

            R.lead('Is there anything you lose track of? Tracking it for a while makes the pattern obvious. Sleep and Slips are already there.') +
            `<div class="rs-pick" data-pickgroup="trackers">${this.TRACKERS.map((t, i) => chip('trackers', t.name, i === 0)).join('')}</div>` +
            R.say(`I&rsquo;d also like to track <input type="text" class="form-input" data-own="trackers" maxlength="40" placeholder="push-ups"> <button type="button" class="btn btn-paper btn-sm" data-add="trackers">Add</button>`),

            R.lead('Last one: the shape of a usual day. I&rsquo;ll set up a starter routine you can change any time.') +
            R.say({ need: true, msg: 'Roughly when do you get up?', html: 'I usually wake up at <input type="time" class="form-input" data-s="wake" value="06:00">' },
                  { need: true, msg: 'And when do you go to bed? Your evening reminders work back from this.', html: 'and go to sleep at <input type="time" class="form-input" data-s="sleep" value="22:30">.' },
                  { msg: 'Leave these as they are if you don&rsquo;t have fixed hours.', html: 'On workdays I work from <input type="time" class="form-input" data-s="work_from" value="09:00"> to <input type="time" class="form-input" data-s="work_to" value="17:30">.' },
                  { msg: 'These days use your Holiday routine.', html: `My weekend is <span class="freq-days">${days.map((d, i) => `<button type="button" class="freq-day-btn ${i >= 5 ? 'active' : ''}" data-weekend="${i}">${d}</button>`).join('')}</span>.` }),
        ];
        const el = document.createElement('div');
        el.className = 'modal fade rs-modal';
        el.tabIndex = -1;
        el.dataset.bsBackdrop = 'static';
        el.innerHTML = `<div class="modal-dialog modal-dialog-centered modal-lg"><div class="modal-content">
            <div class="modal-header"><h5 class="modal-title"><div class="modal-icon info"><i class="fas fa-seedling"></i></div> Let&rsquo;s set you up</h5></div>
            <div class="modal-body">${pages.map((p, i) => `<div class="rs-setup-page" data-page="${i}" ${i ? 'hidden' : ''}>${p}</div>`).join('')}<div class="rs-err" role="alert"></div></div>
            <div class="modal-footer justify-content-between">
                <button type="button" class="tl-link" data-step="skip">Skip setup</button>
                <span class="d-flex align-items-center gap-2">
                    <span class="rs-setup-dots">${pages.map((_, i) => `<span class="ob-dot ${i ? '' : 'active'}"></span>`).join('')}</span>
                    <button type="button" class="btn btn-paper" data-step="back" hidden>Back</button>
                    <button type="button" class="btn btn-paper btn-primary" data-step="next">Next</button>
                </span>
            </div></div></div>`;
        document.body.appendChild(el);
        el.querySelectorAll('[data-rs-convo]').forEach(f => R.convo(f));
        const modal = new bootstrap.Modal(el);
        el.addEventListener('hidden.bs.modal', () => { modal.dispose(); el.remove(); });
        let page = 0;
        const show = (i) => {
            page = i;
            el.querySelectorAll('.rs-setup-page').forEach(p => { p.hidden = Number(p.dataset.page) !== i; });
            el.querySelectorAll('.rs-setup-dots .ob-dot').forEach((d, j) => d.classList.toggle('active', j === i));
            el.querySelector('[data-step="back"]').hidden = i === 0;
            el.querySelector('[data-step="next"]').textContent = i === pages.length - 1 ? 'Finish' : 'Next';
            resizeInputs(el);
        };
        const addOwn = (group) => {
            const input = el.querySelector(`[data-own="${group}"]`);
            const label = input.value.trim();
            if (!label) return;
            el.querySelector(`[data-pickgroup="${group}"]`).insertAdjacentHTML('beforeend', chip(group, label, true));
            input.value = '';
            resizeInputs(el);
        };
        el.addEventListener('keydown', (e) => {
            const own = e.target.closest('[data-own]');
            if (own && e.key === 'Enter') { e.preventDefault(); addOwn(own.dataset.own); }
        });
        el.addEventListener('click', async (e) => {
            const c = e.target.closest('.rs-pick-chip, [data-weekend]');
            if (c) { c.classList.toggle('active'); return; }
            const add = e.target.closest('[data-add]');
            if (add) return addOwn(add.dataset.add);
            const step = e.target.closest('[data-step]');
            if (!step) return;
            if (step.dataset.step === 'skip') {
                await apiClient.post('board/api/onboarding_complete/', {});
                if (AppConfig.userDetail) AppConfig.userDetail.is_onboarded = true;
                return modal.hide();
            }
            if (step.dataset.step === 'back') return show(Math.max(0, page - 1));
            if (page < pages.length - 1) return show(page + 1);
            step.disabled = true;
            const res = await apiClient.post('board/api/onboarding/setup/', this._collect(el));
            step.disabled = false;
            if (res.status !== 'success') { el.querySelector('.rs-err').textContent = res.error || 'Something went wrong'; return; }
            if (AppConfig.userDetail) AppConfig.userDetail.is_onboarded = true;
            modal.hide();
            await AppConfig.load();
            if (typeof Resilient !== 'undefined') { Resilient.loadMetrics(); Resilient._refresh(); }
            this.offerTour();
        });
        modal.show();
    },

    _addMinutes(hhmm, minutes) {
        const [h, m] = hhmm.split(':').map(Number);
        const total = (h * 60 + m + minutes + 1440) % 1440;
        return `${String(Math.floor(total / 60)).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`;
    },

    _collect(el) {
        const v = (k) => el.querySelector(`[data-s="${k}"]`).value;
        const wake = v('wake') || '06:00', sleep = v('sleep') || '22:30';
        const chosen = (g) => [...el.querySelectorAll(`.rs-pick-chip[data-group="${g}"].active`)].map(b => b.dataset.label);
        const habits = chosen('habits').map(label => {
            const h = this.HABITS.find(x => x.habit === label) || { habit: label, detail: 'every day', identity: 'someone who shows up', at: '' };
            const notify = h.at || (h.when === 'wake' ? this._addMinutes(wake, 10) : h.when === 'bed' ? this._addMinutes(sleep, h.offset || -30) : '');
            return { habit: h.habit, detail: h.detail, identity: h.identity, notify_at: notify || null };
        });
        const trackers = chosen('trackers').map(label => this.TRACKERS.find(x => x.name === label)
            || { name: label, unit: '', kind: 'counter', direction: 'at_least', quick_steps: [1] });
        return {
            seriousness: v('seriousness'), habits, trackers,
            routine: {
                wake, sleep, work_from: v('work_from'), work_to: v('work_to'),
                weekend_days: [...el.querySelectorAll('[data-weekend].active')].map(b => Number(b.dataset.weekend)),
            },
        };
    },

    offerTour() {
        Resilient.dialog('You&rsquo;re all set', Resilient.lead('Your habits, trackers and a starter routine are ready. Want a one-minute tour of what&rsquo;s where?'), [
            { label: 'Maybe later' },
            { label: 'Show me around', primary: true, run: async () => { setTimeout(() => Tour.start(), 350); return true; } },
        ], 'fa-route');
    },
};

/** Points at the real parts of the page, one step at a time. */
const Tour = {
    STEPS: [
        { pane: 'home', sel: '#day-bar', title: 'What kind of day is it?', text: 'Change the day here. On a tough day pick Light or Disrupted, and only the blocks that matter stay on your timeline.' },
        { pane: 'home', sel: '#timeline-list', title: 'Your day, in order', text: 'Mark each routine block Done or Skip. The one you&rsquo;re in now is highlighted, and the next one is in bold.' },
        { pane: 'home', sel: '[data-rs="slip"]', title: 'Slipped up?', text: 'Tap this when you give in to something you&rsquo;re cutting down on. It stays private and brings up a short reset, so the day still counts.' },
        { pane: 'home', sel: '[data-rs="travel"]', title: 'Off days', text: 'Night shift, travel, feeling unwell? Mark it as an off day. Your streak stays safe and the reason goes in your journal.' },
        { pane: 'trackers', sel: '#habitTracker', title: 'Your habits', text: 'Tap a day to tick it off. The cog opens steps, reminders, hard-day rules and accountability partners.' },
        { pane: 'trackers', sel: '#trackerGrid', title: 'Trackers', text: 'Keep count of things like water or coffee and see the trend. Sleep and Slips are built in; the book button shows each tracker&rsquo;s notes.' },
        { pane: 'journals', sel: '.journal-editor-section', title: 'Journal', text: 'Write a few lines each day. Notes from your trackers and off days show up here too.' },
        { pane: 'home', sel: '#search-input', title: 'Private items', text: 'Type /private here (or press Ctrl+Shift+L) to show or hide private habits, trackers and journals.' },
        { pane: 'home', sel: null, title: 'That&rsquo;s it', text: 'Settings are under More. You can replay this tour from Help any time.' },
    ],

    start() {
        this.i = 0;
        if (!this.box) {
            this.ring = document.createElement('div');
            this.ring.className = 'rs-tour-ring';
            this.box = document.createElement('div');
            this.box.className = 'rs-tour search-engine-dropdown show';
            this.box.setAttribute('role', 'dialog');
            this.box.addEventListener('click', (e) => {
                const b = e.target.closest('[data-tour]');
                if (!b) return;
                if (b.dataset.tour === 'end') return this.end();
                this.go(this.i + (b.dataset.tour === 'next' ? 1 : -1));
            });
            this._onResize = () => this.place();
        }
        document.body.append(this.ring, this.box);
        window.addEventListener('resize', this._onResize);
        window.addEventListener('scroll', this._onResize, true);
        this.go(0);
    },

    async go(i) {
        if (i < 0) return;
        if (i >= this.STEPS.length) return this.end();
        this.i = i;
        const s = this.STEPS[i];
        if (s.pane && typeof switchPane === 'function') switchPane(s.pane);
        await new Promise(r => setTimeout(r, 250));
        const target = s.sel ? document.querySelector(s.sel) : null;
        if (s.sel && (!target || !target.offsetParent)) return this.go(i + 1);   // not on this page: skip it
        this.target = target;
        if (target) target.scrollIntoView({ block: 'center', behavior: 'smooth' });
        const last = i === this.STEPS.length - 1;
        this.box.innerHTML = `<div class="rs-tour-head">${s.title}</div><div class="rs-tour-text">${s.text}</div>
            <div class="rs-tour-foot"><span class="rs-tour-count">${i + 1} of ${this.STEPS.length}</span>
                <span>${last ? '' : '<button type="button" class="tl-link me-2" data-tour="end">Skip</button>'}
                ${i ? '<button type="button" class="btn btn-paper btn-sm me-1" data-tour="back">Back</button>' : ''}
                <button type="button" class="btn btn-paper btn-sm btn-primary" data-tour="${last ? 'end' : 'next'}">${last ? 'Done' : 'Next'}</button></span></div>`;
        setTimeout(() => this.place(), 320);
        this.place();
    },

    place() {
        if (!this.box || !this.box.isConnected) return;
        const t = this.target;
        const vw = document.documentElement.clientWidth, vh = window.innerHeight;
        const bw = Math.min(340, vw - 24);
        this.box.style.width = `${bw}px`;
        if (!t) {
            this.ring.style.display = 'none';
            this.box.style.left = `${(vw - bw) / 2}px`;
            this.box.style.top = `${Math.max(24, vh / 2 - this.box.offsetHeight / 2)}px`;
            return;
        }
        const r = t.getBoundingClientRect();
        Object.assign(this.ring.style, { display: 'block', left: `${r.left - 6}px`, top: `${r.top - 6}px`, width: `${r.width + 12}px`, height: `${Math.min(r.height, vh * .7) + 12}px` });
        const below = r.top + Math.min(r.height, vh * .7) + 14;
        const top = below + this.box.offsetHeight < vh ? below : Math.max(12, r.top - this.box.offsetHeight - 14);
        this.box.style.top = `${top}px`;
        this.box.style.left = `${Math.min(Math.max(12, r.left), vw - bw - 12)}px`;
    },

    end() {
        this.ring.remove();
        this.box.remove();
        window.removeEventListener('resize', this._onResize);
        window.removeEventListener('scroll', this._onResize, true);
        if (typeof switchPane === 'function') switchPane('home');
    },
};

// Replay from Help
document.addEventListener('DOMContentLoaded', () => {
    const help = document.getElementById('pane-help');
    if (!help || document.getElementById('rs-tour-replay')) return;
    const box = document.createElement('div');
    box.className = 'settings-card mb-4';
    box.innerHTML = `<h6 class="settings-card-title"><i class="fas fa-route me-2"></i>Getting around</h6>
        <p class="mb-2">A one-minute tour of the main features.</p>
        <button type="button" class="btn btn-paper btn-sm btn-primary" id="rs-tour-replay">Take the tour</button>`;
    const host = help.querySelector('.misc-pane-layout') || help.querySelector('.container-fluid') || help;
    const title = host.querySelector(':scope > h4, :scope > .section-title');
    if (title) title.insertAdjacentElement('afterend', box); else host.prepend(box);
    box.querySelector('#rs-tour-replay').addEventListener('click', () => Tour.start());
});
