/**
 * pomodoro.js — Pomodoro timer with persistence and audio
 */

const Pomodoro = {
    state: null, // { mode: 'focus'|'break'|'long_break', remaining: seconds, running: bool, cycle: number }
    interval: null,
    audioCtx: null,

    defaults() {
        const d = AppConfig.userDetail || {};
        return {
            focusMin: d.pomodoro_focus || 25,
            breakMin: d.pomodoro_break || 5,
            longBreakMin: d.pomodoro_long_break || 15,
            cycles: d.pomodoro_cycles || 4,
        };
    },

    init() {
        // Restore state from localStorage
        const saved = localStorage.getItem('pomodoro_state');
        if (saved) {
            try {
                this.state = JSON.parse(saved);
                // If it was running, calculate elapsed time
                if (this.state.running && this.state.lastTick) {
                    const elapsed = Math.floor((Date.now() - this.state.lastTick) / 1000);
                    this.state.remaining = Math.max(0, this.state.remaining - elapsed);
                    if (this.state.remaining <= 0) {
                        this.onTimerEnd();
                        return;
                    }
                    this.startInterval();
                }
            } catch (e) {
                this.state = null;
            }
        }

        if (!this.state) {
            this.state = {
                mode: 'focus',
                remaining: this.defaults().focusMin * 60,
                running: false,
                cycle: 1,
                lastTick: null,
            };
        }

        this.render();
    },

    save() {
        this.state.lastTick = this.state.running ? Date.now() : null;
        localStorage.setItem('pomodoro_state', JSON.stringify(this.state));
    },

    toggle() {
        if (this.state.running) {
            this.pause();
        } else {
            this.start();
        }
    },

    toggleMode() {
        if (this.state.running) {
            clearInterval(this.interval);
            this.interval = null;
            this.state.running = false;
        }
        const d = this.defaults();
        if (this.state.mode === 'focus') {
            this.state.mode = 'break';
            this.state.remaining = d.breakMin * 60;
        } else if (this.state.mode === 'break') {
            this.state.mode = 'long_break';
            this.state.remaining = d.longBreakMin * 60;
        } else {
            this.state.mode = 'focus';
            this.state.remaining = d.focusMin * 60;
        }
        this.save();
        this.render();
    },

    start() {
        this.state.running = true;
        this.beep(880, 1);
        this.save();
        this.startInterval();
        this.render();
    },

    pause() {
        this.state.running = false;
        this.beep(440, 0.8);
        clearInterval(this.interval);
        this.interval = null;
        this.save();
        this.render();
    },

    reset() {
        clearInterval(this.interval);
        this.interval = null;
        this.state = {
            mode: 'focus',
            remaining: this.defaults().focusMin * 60,
            running: false,
            cycle: 1,
            lastTick: null,
        };
        this.save();
        this.render();
    },

    startInterval() {
        if (this.interval) clearInterval(this.interval);
        this.interval = setInterval(() => {
            this.state.remaining--;
            this.state.lastTick = Date.now();
            this.save();
            this.render();

            if (this.state.remaining <= 0) {
                this.onTimerEnd();
            }
        }, 1000);
    },

    onTimerEnd() {
        clearInterval(this.interval);
        this.interval = null;
        this.state.running = false;
        this.chime();

        const d = this.defaults();

        if (this.state.mode === 'focus') {
            // Check if it's time for a long break
            if (this.state.cycle >= d.cycles) {
                this.state.mode = 'long_break';
                this.state.remaining = d.longBreakMin * 60;
                this.state.cycle = 1;
            } else {
                this.state.mode = 'break';
                this.state.remaining = d.breakMin * 60;
            }
        } else {
            // Break ended, start new focus
            if (this.state.mode === 'break') {
                this.state.cycle++;
            }
            this.state.mode = 'focus';
            this.state.remaining = d.focusMin * 60;
        }

        this.save();
        this.render();
    },

    render() {
        const mins = Math.floor(this.state.remaining / 60);
        const secs = this.state.remaining % 60;
        const timeStr = `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;

        document.getElementById('pomodoro-time').textContent = timeStr;

        const modeLabels = { focus: 'Focus', break: 'Break', long_break: 'Long Break' };
        document.getElementById('pomodoro-mode').textContent = modeLabels[this.state.mode] || 'Focus';

        const btn = document.getElementById('pomodoro-start');
        if (this.state.running) {
            btn.innerHTML = '<i class="fas fa-pause"></i>';
        } else {
            btn.innerHTML = '<i class="fas fa-play"></i>';
        }

        // Cycle indicators
        const d = this.defaults();
        const cyclesEl = document.getElementById('pomodoro-cycles');
        if (cyclesEl) {
            let dots = '';
            for (let i = 1; i <= d.cycles; i++) {
                dots += `<span class="cycle-dot ${i < this.state.cycle ? 'done' : ''} ${i === this.state.cycle && this.state.mode === 'focus' ? 'current' : ''}"></span>`;
            }
            cyclesEl.innerHTML = dots;
        }
    },

    beep(freq, duration) {
        if (!USER_DETAIL.sound_pomodoro) return;
        try {
            if (!this.audioCtx) {
                this.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
            }
            const ctx = this.audioCtx;
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.connect(gain);
            gain.connect(ctx.destination);
            osc.frequency.value = freq;
            osc.type = 'triangle';
            gain.gain.setValueAtTime(0, ctx.currentTime);
            gain.gain.linearRampToValueAtTime(0.35, ctx.currentTime + 0.015);
            gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + duration);
            osc.start(ctx.currentTime);
            osc.stop(ctx.currentTime + duration);
        } catch (e) {
            // Audio not available
        }
    },

    chime() {
        // Pleasant ascending 3-note chime for timer end
        const notes = [523.25, 659.25, 783.99]; // C5, E5, G5
        notes.forEach((freq, i) => {
            setTimeout(() => this.beep(freq, 0.6), i * 220);
        });
    },

    updateSettings(settings) {
        // Called from settings when pomodoro config changes
        USER_DETAIL.pomodoro_focus = settings.focusMin;
        USER_DETAIL.pomodoro_break = settings.breakMin;
        USER_DETAIL.pomodoro_long_break = settings.longBreakMin;
        USER_DETAIL.pomodoro_cycles = settings.cycles;
        // If not running, reset timer to new duration
        if (!this.state.running) {
            this.reset();
        }
    }
};