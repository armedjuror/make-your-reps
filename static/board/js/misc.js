/**
 * misc.js — Misc pane: Friends management
 */

const MiscPane = {
    init(initialTab = 'friends') {
        this.bindEvents();
        this.switchTab(initialTab || 'friends');
    },

    bindEvents() {
        document.getElementById('send-friend-request-btn').addEventListener('click', () => this.sendRequest());
        document.getElementById('friend-request-email').addEventListener('keydown', (e) => {
            if (e.key === 'Enter') this.sendRequest();
        });
        document.querySelectorAll('.misc-sub-tab[data-misc-tab]').forEach(btn => {
            btn.addEventListener('click', () => this.switchTab(btn.dataset.miscTab));
        });
    },

    switchTab(tab) {
        document.querySelectorAll('.misc-sub-tab').forEach(b => b.classList.remove('active'));
        const activeBtn = document.querySelector(`.misc-sub-tab[data-misc-tab="${tab}"]`);
        if (activeBtn) activeBtn.classList.add('active');
        document.querySelectorAll('.misc-tab-content').forEach(el => el.style.display = 'none');
        const content = document.getElementById(`misc-tab-${tab}`);
        if (content) content.style.display = 'block';
        // Update URL hash to reflect the active sub-tab
        history.replaceState(null, '', `#${tab}`);
        if (tab === 'friends') this.load();
        else if (tab === 'achievements') this.loadAchievements();
        else if (tab === 'reading-list') ReadingList.loadAll();
    },

    load() {
        this.loadFriends();
        this.loadRequests();
    },

    async loadAchievements() {
        await Gamification.load();
        Gamification.renderAchievementsTab();
        Gamification.loadHallmarkedHabits();
        Gamification.loadProductivityHistory();
    },

    async loadFriends() {
        const el = document.getElementById('friends-list');
        el.innerHTML = '<div class="notebook-spinner"></div>';
        const res = await apiClient.get('board/api/friends/');
        if (res.status !== 'success') { el.innerHTML = '<p class="text-brown small">Could not load friends.</p>'; return; }
        this.renderFriends(res.data);
    },

    renderFriends(friends) {
        const el = document.getElementById('friends-list');
        if (friends.length === 0) {
            el.innerHTML = '<p class="text-brown small">No friends yet. Send a request to get started.</p>';
            return;
        }
        el.innerHTML = friends.map(f => `
            <div class="misc-friend-item">
                <div class="misc-friend-avatar">${(f.friend_name || f.friend_username || '?')[0].toUpperCase()}</div>
                <div class="misc-friend-info">
                    <div class="misc-friend-name">${f.friend_name}</div>
                    <div class="misc-friend-email">${f.friend_email}</div>
                </div>
                <button class="btn btn-paper btn-sm btn-danger ms-auto" onclick="MiscPane.removeFriend(${f.id})" title="Remove friend">
                    <i class="fas fa-user-minus"></i>
                </button>
            </div>
        `).join('');
    },

    async loadRequests() {
        const receivedEl = document.getElementById('friend-received-list');
        const sentEl = document.getElementById('friend-sent-list');
        receivedEl.innerHTML = '<div class="notebook-spinner"></div>';
        sentEl.innerHTML = '<div class="notebook-spinner"></div>';

        const res = await apiClient.get('board/api/friends/requests/');
        if (res.status !== 'success') {
            receivedEl.innerHTML = '<p class="text-brown small">Could not load requests.</p>';
            sentEl.innerHTML = '';
            return;
        }
        this.renderReceived(res.data.received);
        this.renderSent(res.data.sent);
    },

    renderReceived(requests) {
        const el = document.getElementById('friend-received-list');
        if (requests.length === 0) {
            el.innerHTML = '<p class="text-brown small">No pending requests.</p>';
            return;
        }
        el.innerHTML = requests.map(r => `
            <div class="misc-request-item">
                <div class="misc-request-info">
                    <div class="misc-friend-name">${r.from_user_name}</div>
                    <small class="text-brown">wants to be friends</small>
                </div>
                <div class="misc-request-actions">
                    <button class="btn btn-paper btn-sm btn-primary me-1" onclick="MiscPane.acceptRequest(${r.id})">
                        <i class="fas fa-check"></i>
                    </button>
                    <button class="btn btn-paper btn-sm" onclick="MiscPane.declineRequest(${r.id})">
                        <i class="fas fa-times"></i>
                    </button>
                </div>
            </div>
        `).join('');
    },

    renderSent(requests) {
        const el = document.getElementById('friend-sent-list');
        if (requests.length === 0) {
            el.innerHTML = '<p class="text-brown small">No sent requests.</p>';
            return;
        }
        el.innerHTML = requests.map(r => `
            <div class="misc-request-item">
                <div class="misc-request-info">
                    <div class="misc-friend-name">${r.to_user_name}</div>
                    <small class="text-brown misc-status-${r.status}">${r.status}</small>
                </div>
            </div>
        `).join('');
    },

    async sendRequest() {
        const input = document.getElementById('friend-request-email');
        const msgEl = document.getElementById('friend-request-msg');
        const email = input.value.trim();

        if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
            msgEl.innerHTML = '<small class="text-danger">Enter a valid email.</small>';
            return;
        }

        const res = await apiClient.post('board/api/friends/send_request/', { email });
        if (res.status === 'success') {
            input.value = '';
            msgEl.innerHTML = `<small class="text-success"><i class="fas fa-check me-1"></i>${res.message}</small>`;
            this.loadRequests();
            this.loadFriends();
            setTimeout(() => { msgEl.innerHTML = ''; }, 4000);
        } else {
            msgEl.innerHTML = `<small class="text-danger">${res.error || 'Failed to send request.'}</small>`;
        }
    },

    async removeFriend(friendId) {
        const res = await apiClient.delete(`board/api/friends/${friendId}/`);
        if (res.status === 'success') {
            this.loadFriends();
        } else {
            showError(res.error || 'Failed to remove friend.');
        }
    },

    async acceptRequest(requestId) {
        const res = await apiClient.post(`board/api/friend_requests/${requestId}/accept/`);
        if (res.status === 'success') {
            this.load();
        } else {
            showError(res.error || 'Failed to accept request.');
        }
    },

    async declineRequest(requestId) {
        const res = await apiClient.post(`board/api/friend_requests/${requestId}/decline/`);
        if (res.status === 'success') {
            this.loadRequests();
        } else {
            showError(res.error || 'Failed to decline request.');
        }
    },
};
