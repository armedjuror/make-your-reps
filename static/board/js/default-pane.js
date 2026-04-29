/**
 * default-pane.js — Home pane logic
 * Greeting, datetime with seconds, productivity score, search
 */

const DefaultPane = {
    searchEngines: [],
    currentEngine: 'google',
    init() {
        this.currentEngine = AppConfig.userDetail?.default_search_engine || 'google';
        General.updateGreeting();
        General.startClock();
        General.loadProductivityScore();
        this.loadSearchEngines();
        setInterval(() => General.updateGreeting(), 600000);
    },
    async loadSearchEngines() {
        const res = await apiClient.get('board/api/search_engines/');
        if (res.status === 'success') {
            this.searchEngines = res.data;
            this.updateSearchIcon();
            this.buildSearchDropdown();
        }
    },
    updateSearchIcon() {
        const engine = this.searchEngines.find(e => e.key === this.currentEngine);
        const iconEl = document.getElementById('search-engine-icon');
        if (engine && iconEl) {
            iconEl.className = engine.icon;
        }
    },
    buildSearchDropdown() {
        const dropdown = document.getElementById('search-engine-dropdown');
        if (!dropdown) return;
        dropdown.innerHTML = this.searchEngines.map(e => `
            <div class="search-engine-option ${e.key === this.currentEngine ? 'active' : ''}"
                 onclick="DefaultPane.selectEngine('${e.key}')">
                <i class="${e.icon}"></i>
                <span>${e.name}</span>
            </div>
        `).join('');
    },

    selectEngine(key) {
        this.currentEngine = key;
        this.updateSearchIcon();
        this.buildSearchDropdown();
        document.getElementById('search-engine-dropdown').classList.remove('show');
        document.getElementById('search-input').focus();
    },

    doSearch() {
        const query = document.getElementById('search-input').value.trim();
        if (!query) return;

        const engine = this.searchEngines.find(e => e.key === this.currentEngine);
        if (engine) {
            document.getElementById('search-input').value = ''
            const url = engine.url_template.replace('{query}', encodeURIComponent(query));
            window.open(url, '_blank');
        }
    }
};

function toggleSearchEngineDropdown() {
    document.getElementById('search-engine-dropdown').classList.toggle('show');
}

// Close dropdown when clicking outside
document.addEventListener('click', function (e) {
    if (!e.target.closest('.search-bar')) {
        const dd = document.getElementById('search-engine-dropdown');
        if (dd) dd.classList.remove('show');
    }
});

function initHomePane() {
    DefaultPane.init();
    Timeline.init();
    ReadingList.loadFeatured();
    Pomodoro.init();
    Habits.init();
    Gamification.loadProductivityHistory(); // prefetch + cache for achievements pane
}