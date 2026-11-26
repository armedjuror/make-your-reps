/**
 * exercise3d.js — the three.js exercise viewer.
 *
 * Loads three.js (pinned, via the page's import map) only when a player or
 * exercise screen asks for it, then the shared static/fitness/mannequin.glb
 * once and one animation clip per exercise (clips/<id>.glb). Falls back to the
 * pre-rendered still when a clip, the mannequin or WebGL is missing, and shows
 * the still with a play button under prefers-reduced-motion.
 *
 * Theming: one mannequinTheme per MYR theme. applyTheme() sets the body
 * materials, resets every muscle mesh to its base colour, then colours the
 * exercise's primary muscles (accent + a small emissive glow) and secondary
 * muscles (accentLight), and recolours the shared band material. Shared
 * materials are cloned before any per-object change. NoToneMapping keeps the
 * hex values exact. Theme changes re-apply without reloading the model.
 *
 * Unilateral clips animate the right side; the left side mirrors the model
 * (root scale x = -1) and swaps left/right highlights. Alternating moves are
 * one clip and never mirrored.
 *
 * Public: Exercise3D.mount(container, exercise, {side, autoplay, compact}),
 *         Exercise3D.unmount(container), Exercise3D.applyThemeAll().
 */
const Exercise3D = (() => {
    const THREE_VERSION = '0.170.0';
    const MESH_ALIASES = { core: 'abs' };
    const SHORTS_MUSCLES = new Set(['glutes', 'hip_flexors', 'abductors']);
    const BODY_PARTS = ['skin', 'shorts', 'shoe'];
    // The Exercise schema's muscle list (mesh names match it exactly; core is drawn as abs)
    const MUSCLES = new Set(['quads', 'hamstrings', 'glutes', 'adductors', 'abductors', 'calves', 'chest', 'upper_back',
        'lats', 'front_delts', 'side_delts', 'rear_delts', 'biceps', 'triceps', 'forearms', 'core', 'abs', 'obliques',
        'lower_back', 'hip_flexors']);

    // One object per MYR theme; legacy names map onto these (dark -> ink, light/paper/plain -> aurora)
    const THEMES = {
        ink:      { skin: '#c9b8a3', shorts: '#3a332b', shoe: '#1d1a16', accent: '#ba8238', accentLight: '#d9b27a', band: '#ba8238', mat: '#2a2622', background: null },
        terminal: { skin: '#9fb8a6', shorts: '#13261a', shoe: '#0b140e', accent: '#4ade80', accentLight: '#9eeab9', band: '#4ade80', mat: '#10201a', background: null },
        tech:     { skin: '#aebdd0', shorts: '#16233f', shoe: '#0b1226', accent: '#38bdf8', accentLight: '#9cdcfb', band: '#38bdf8', mat: '#14203a', background: null },
        aurora:   { skin: '#e3cbb5', shorts: '#3b3570', shoe: '#23204a', accent: '#6d5ef0', accentLight: '#b3aaf7', band: '#6d5ef0', mat: '#d9d6f5', background: null },
        sensei:   { skin: '#e4d3bf', shorts: '#2b2926', shoe: '#1c1b19', accent: '#c8321f', accentLight: '#e2958a', band: '#c8321f', mat: '#d8cfbd', background: null },
        coach:    { skin: '#c9b9a6', shorts: '#1f1f1f', shoe: '#0a0a0a', accent: '#facc15', accentLight: '#fbe38a', band: '#facc15', mat: '#262626', background: null },
        garden:   { skin: '#e2cdb3', shorts: '#3e5a3b', shoe: '#2a3826', accent: '#4f8a4e', accentLight: '#a5c8a0', band: '#4f8a4e', mat: '#cfdfc0', background: null },
        orbit:    { skin: '#c4bcd8', shorts: '#2a2350', shoe: '#140f2e', accent: '#b794ff', accentLight: '#dac8ff', band: '#b794ff', mat: '#1b1638', background: null },
        quest:    { skin: '#f0c9a0', shorts: '#1a1a2e', shoe: '#1a1a2e', accent: '#e4372c', accentLight: '#f29a93', band: '#e4372c', mat: '#9fd6f5', background: null },
    };
    const LEGACY = { dark: 'ink', light: 'aurora', paper: 'aurora', plain: 'aurora' };

    let libP = null;           // Promise<{THREE, GLTFLoader, SkeletonUtils}>
    let mannequinP = null;     // Promise<gltf>
    const views = new Map();   // container -> view
    let observer = null;

    function themeName() {
        const t = document.documentElement.getAttribute('data-theme') || document.body.getAttribute('data-theme') || 'ink';
        return THEMES[t] ? t : (LEGACY[t] || 'ink');
    }

    function mannequinTheme(name) { return THEMES[name || themeName()]; }

    function webglOK() {
        try {
            const c = document.createElement('canvas');
            return !!(window.WebGLRenderingContext && (c.getContext('webgl2') || c.getContext('webgl')));
        } catch (e) { return false; }
    }

    function reducedMotion() { return window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches; }
    function lowEnd() { return (navigator.hardwareConcurrency || 8) <= 4 || (navigator.deviceMemory || 8) <= 4; }

    function loadLib() {
        if (!libP) {
            libP = Promise.all([
                import('three'),
                import('three/addons/loaders/GLTFLoader.js'),
                import('three/addons/utils/SkeletonUtils.js'),
            ]).then(([THREE, L, S]) => ({ THREE, GLTFLoader: L.GLTFLoader, SkeletonUtils: S }));
        }
        return libP;
    }

    function loadMannequin(url) {
        if (!mannequinP) mannequinP = loadLib().then(({ GLTFLoader }) => new GLTFLoader().loadAsync(url));
        return mannequinP;
    }

    // ── Mesh naming: quads_l, muscle_quads_r, abs ... ───────
    function parseMuscle(name) {
        let n = String(name || '').toLowerCase().replace(/^muscle_/, '');
        let side = '';
        const m = n.match(/_(l|r|left|right)$/);
        if (m) { side = m[1][0]; n = n.slice(0, -m[0].length); }
        return { base: n, side };
    }

    function isMuscleMesh(mesh, muscleNames) {
        const { base } = parseMuscle(mesh.name);
        return muscleNames.has(base);
    }

    function partOf(mesh) {
        const n = `${mesh.name} ${mesh.material && mesh.material.name}`.toLowerCase();
        return BODY_PARTS.find(p => n.includes(p)) || (n.includes('band') ? 'band' : n.includes('mat') ? 'mat' : null);
    }

    // ── Theme ───────────────────────────────────────────────
    function applyTheme(view) {
        const { THREE } = view.lib;
        const th = mannequinTheme();
        const ex = view.ex;
        const want = (list) => new Set((list || []).map(m => MESH_ALIASES[m] || m));
        const primary = want(ex.primary_muscles), secondary = want(ex.secondary_muscles);
        const allMuscles = view.muscleNames;
        view.model.traverse(o => {
            if (!o.isMesh || !o.material) return;
            const mat = o.material;
            if (isMuscleMesh(o, allMuscles)) {
                const { base, side } = parseMuscle(o.name);
                // Unilateral clips animate the right side, so the worked muscles are the _r meshes.
                // Mirroring (root scale x = -1) puts those meshes on the left, so the left side's
                // highlight follows the geometry: the swap is the mirror itself.
                const working = !ex.unilateral || side !== 'l';
                mat.color.set(SHORTS_MUSCLES.has(base) ? th.shorts : th.skin);   // reset: no stale patches
                if (mat.emissive) { mat.emissive.set('#000000'); mat.emissiveIntensity = 0; }
                if (primary.has(base) && working) {
                    mat.color.set(th.accent);
                    if (mat.emissive) { mat.emissive.set(th.accent); mat.emissiveIntensity = 0.25; }
                } else if (primary.has(base) || secondary.has(base)) {
                    mat.color.set(th.accentLight);
                }
                return;
            }
            const part = partOf(o);
            if (part === 'skin' || part === 'shorts' || part === 'shoe') mat.color.set(th[part]);
            else if (part === 'band') mat.color.set(th.band);
            else if (part === 'mat') mat.color.set(th.mat);
        });
        view.scene.background = th.background ? new THREE.Color(th.background) : null;
    }

    function applyThemeAll() { views.forEach(v => v.model && applyTheme(v)); }

    function watchTheme() {
        if (observer) return;
        observer = new MutationObserver(applyThemeAll);
        observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
        observer.observe(document.body, { attributes: true, attributeFilter: ['data-theme'] });
    }

    // ── Camera ──────────────────────────────────────────────
    const PRESETS = { front: [0, 8], side: [90, 8], back: [180, 8], three_quarter: [40, 12], top: [0, 70] };

    function placeCamera(view) {
        const { THREE } = view.lib;
        const r = view.distance;
        const yaw = THREE.MathUtils.degToRad(view.yaw), pitch = THREE.MathUtils.degToRad(view.pitch);
        view.camera.position.set(
            view.center.x + r * Math.sin(yaw) * Math.cos(pitch),
            view.center.y + r * Math.sin(pitch),
            view.center.z + r * Math.cos(yaw) * Math.cos(pitch));
        view.camera.lookAt(view.center);
    }

    // ── Mount / unmount ─────────────────────────────────────
    function stillHtml(ex, playButton) {
        return `${ex.still ? `<img class="ex3d-still" src="${ex.still.startsWith('/') && typeof HOST !== 'undefined' ? HOST.replace(/\/$/, '') + ex.still : ex.still}" alt="${ex.name}">` : ''}
            ${playButton ? '<button type="button" class="ex3d-play-still" aria-label="Play the animation"><i class="fas fa-play"></i></button>' : ''}`;
    }

    async function mount(container, ex, opts = {}) {
        if (!container || !ex) return;
        unmount(container);
        const anim = ex.animation || {};
        const canAnimate = anim.clip_url && ex.mannequin_url && webglOK();
        if (!canAnimate) return;                               // the still already in the container stays
        if (reducedMotion() && !opts.force) {
            container.innerHTML = stillHtml(ex, true);
            container.querySelector('.ex3d-play-still').addEventListener('click', () => mount(container, ex, { ...opts, force: true }), { once: true });
            return;
        }
        const token = {};
        container._ex3dToken = token;
        let lib, mannequin, clipGltf;
        try {
            lib = await loadLib();
            [mannequin, clipGltf] = await Promise.all([loadMannequin(ex.mannequin_url), new lib.GLTFLoader().loadAsync(anim.clip_url)]);
        } catch (e) {
            console.warn('[Exercise3D] falling back to the still:', e);
            return;
        }
        if (container._ex3dToken !== token || !container.isConnected) return;   // unmounted meanwhile

        const { THREE, SkeletonUtils } = lib;
        const w = container.clientWidth || 320, h = container.clientHeight || w;
        const renderer = new THREE.WebGLRenderer({ antialias: !lowEnd(), alpha: true });
        renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, lowEnd() ? 1 : 2));
        renderer.setSize(w, h);
        renderer.toneMapping = THREE.NoToneMapping;
        renderer.outputColorSpace = THREE.SRGBColorSpace;
        renderer.shadowMap.enabled = !lowEnd();

        const scene = new THREE.Scene();
        scene.add(new THREE.HemisphereLight(0xffffff, 0x444444, 1.6));
        const key = new THREE.DirectionalLight(0xffffff, 1.4);
        key.position.set(2, 4, 3);
        key.castShadow = renderer.shadowMap.enabled;
        scene.add(key);

        const model = SkeletonUtils.clone(mannequin.scene);
        const muscleNames = new Set();
        const mirrored = opts.side === 'left' && ex.unilateral && anim.side !== 'both';
        model.traverse(o => {
            if (!o.isMesh || !o.material) return;
            // Shared materials (steel, iron, pad, skin...) are cloned before any per-object change
            o.material = Array.isArray(o.material) ? o.material.map(m => m.clone()) : o.material.clone();
            if (mirrored) o.material.side = THREE.DoubleSide;
            o.castShadow = renderer.shadowMap.enabled;
            const { base } = parseMuscle(o.name);
            if (MUSCLES.has(base)) muscleNames.add(base);
        });
        if (mirrored) model.scale.x *= -1;
        scene.add(model);

        // Frame the figure
        const box = new THREE.Box3().setFromObject(model);
        const size = box.getSize(new THREE.Vector3()), center = box.getCenter(new THREE.Vector3());
        const camera = new THREE.PerspectiveCamera(35, w / h, 0.01, 100);
        const cam = anim.camera || 'side';
        const [yaw, pitch] = typeof cam === 'string' ? (PRESETS[cam] || PRESETS.side) : [cam.yaw, cam.pitch];
        const distance = (typeof cam === 'object' && cam.distance) || Math.max(size.y, size.x) * 2.1;

        const mixer = new THREE.AnimationMixer(model);
        const clip = clipGltf.animations && clipGltf.animations[0];
        let action = null;
        if (clip) {
            action = mixer.clipAction(clip);
            if (anim.loop_ms && clip.duration) action.timeScale = clip.duration / (anim.loop_ms / 1000);
            action.play();
            if (opts.autoplay === false) { action.paused = true; action.time = (anim.peak || 0.5) * clip.duration; mixer.update(0); }
        }

        const view = { lib, ex, side: mirrored ? 'left' : 'right', renderer, scene, camera, model, mixer, action,
                       muscleNames, center, yaw, pitch, distance, speed: 1, playing: opts.autoplay !== false,
                       clock: new THREE.Clock(), container };
        placeCamera(view);
        applyTheme(view);
        watchTheme();

        container.classList.add('ex3d');
        const canvas = renderer.domElement;
        canvas.className = 'ex3d-canvas';
        canvas.setAttribute('role', 'img');
        canvas.setAttribute('aria-label', `${ex.name} animation`);
        container.innerHTML = '';
        container.appendChild(canvas);
        if (!opts.compact) container.insertAdjacentHTML('beforeend', `<div class="ex3d-controls">
            <button type="button" data-x3="play" aria-label="Play or pause"><i class="fas fa-pause"></i></button>
            <button type="button" data-x3="speed" aria-label="Speed">1×</button>
            <button type="button" data-x3="front">Front</button>
            <button type="button" data-x3="side">Side</button></div>`);
        else container.insertAdjacentHTML('beforeend', '<div class="ex3d-controls"><button type="button" data-x3="play" aria-label="Play or pause"><i class="fas fa-pause"></i></button></div>');
        bindControls(view);

        // Render only while visible
        view.visible = true;
        view.io = new IntersectionObserver(es => { view.visible = es[0].isIntersecting; });
        view.io.observe(container);
        renderer.setAnimationLoop(() => {
            const dt = view.clock.getDelta();
            if (!view.visible) return;
            if (view.playing) mixer.update(dt * view.speed);
            renderer.render(scene, camera);
        });
        view.ro = new ResizeObserver(() => {
            const W = container.clientWidth, H = container.clientHeight || W;
            if (!W) return;
            renderer.setSize(W, H);
            camera.aspect = W / H;
            camera.updateProjectionMatrix();
        });
        view.ro.observe(container);
        views.set(container, view);
    }

    function bindControls(view) {
        const c = view.container;
        const btn = (k) => c.querySelector(`[data-x3="${k}"]`);
        c.addEventListener('click', (e) => {
            const b = e.target.closest('[data-x3]');
            if (!b) return;
            const k = b.dataset.x3;
            if (k === 'play') {
                view.playing = !view.playing;
                if (view.action) view.action.paused = !view.playing;
                b.innerHTML = `<i class="fas ${view.playing ? 'fa-pause' : 'fa-play'}"></i>`;
            } else if (k === 'speed') {
                view.speed = { 1: 1.5, 1.5: 0.5, 0.5: 1 }[view.speed];
                b.textContent = `${view.speed}×`;
            } else if (k === 'front' || k === 'side') {
                [view.yaw, view.pitch] = PRESETS[k];
                placeCamera(view);
            }
        });
        // Drag to rotate
        let drag = null;
        const canvas = view.renderer.domElement;
        canvas.style.touchAction = 'pan-y';
        canvas.addEventListener('pointerdown', (e) => { drag = { x: e.clientX, yaw: view.yaw }; canvas.setPointerCapture(e.pointerId); });
        canvas.addEventListener('pointermove', (e) => {
            if (!drag) return;
            view.yaw = drag.yaw - (e.clientX - drag.x) * 0.6;
            placeCamera(view);
        });
        const end = () => { drag = null; };
        canvas.addEventListener('pointerup', end);
        canvas.addEventListener('pointercancel', end);
        if (btn('play') && !view.playing) btn('play').innerHTML = '<i class="fas fa-play"></i>';
    }

    function unmount(container) {
        if (!container) return;
        container._ex3dToken = null;
        const v = views.get(container);
        if (!v) return;
        v.renderer.setAnimationLoop(null);
        v.io && v.io.disconnect();
        v.ro && v.ro.disconnect();
        v.mixer.stopAllAction();
        v.model.traverse(o => {
            if (o.isMesh) {
                (Array.isArray(o.material) ? o.material : [o.material]).forEach(m => m && m.dispose());
            }
        });
        v.renderer.dispose();
        v.renderer.forceContextLoss && v.renderer.forceContextLoss();
        views.delete(container);
    }

    return { mount, unmount, applyThemeAll, mannequinTheme, THEMES, THREE_VERSION, _views: views, _parseMuscle: parseMuscle };
})();
