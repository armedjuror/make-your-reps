/**
 * misc.js — Misc pane: Friends management
 */

const MiscPane = {
    initFriends() {
        document.getElementById('send-friend-request-btn').addEventListener('click', () => this.sendRequest());
        document.getElementById('friend-request-email').addEventListener('keydown', (e) => {
            if (e.key === 'Enter') this.sendRequest();
        });
        this.load();
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
                <button class="btn btn-paper btn-sm ms-auto" onclick="MiscPane.removeFriend(${f.id})" title="Remove friend">
                    <i class="fas fa-user-minus"></i>
                </button>
            </div>
        `).join('');
    },

    async loadRequests() {
        const receivedEl = document.getElementById('friend-received-list');
        const sentEl = document.getElementById('friend-sent-list');
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
                    <button class="btn btn-paper btn-sm me-1" onclick="MiscPane.acceptRequest(${r.id})">
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
        el.innerHTML = requests.map(r => {
            if (r.status === 'accepted'){
                return `
                    <div class="misc-request-item">
                        <div class="misc-request-info">
                            <div class="misc-friend-name">${r.to_user_name}</div>
                            <small class="text-brown misc-status-${r.status} text-capitalize">${r.status}</small>
                        </div>
                    </div>
                `;
            }

            return `
            <div class="misc-request-item">
                <div class="misc-request-info">
                    <div class="misc-friend-name">${r.to_user_name}</div>
                    <small class="text-brown misc-status-${r.status} text-capitalize">${r.status}</small>
                </div>
                <div class="misc-request-actions">
                    <button class="btn btn-paper btn-sm" onclick="MiscPane.withdrawRequest(${r.id})" title="Withdraw request">
                        <i class="fas fa-close"></i>
                    </button>
                </div>
            </div>
        `;
        }).join('');
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

    async withdrawRequest(requestId) {
        const res = await apiClient.delete(`board/api/friend_requests/${requestId}/withdraw/`);
        if (res.status === 'success') {
            this.loadRequests();
        } else {
            showError(res.error || 'Failed to withdraw request.');
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

const Help = {
    async submitFeedback() {
        const type = document.getElementById('feedbackType').value;
        const subject = document.getElementById('feedbackSubject').value.trim();
        const message = document.getElementById('feedbackMessage').value.trim();
        const msgEl = document.getElementById('feedback-msg');

        if (!subject || !message) {
            msgEl.innerHTML = '<small class="text-danger">Subject and message are required.</small>';
            return;
        }

        const res = await apiClient.post('board/api/feedback/', { type, subject, message });
        if (res.status === 'success') {
            document.getElementById('feedbackSubject').value = '';
            document.getElementById('feedbackMessage').value = '';
            msgEl.innerHTML = '<small class="text-success"><i class="fas fa-check me-1"></i>Feedback sent! Thank you.</small>';
            setTimeout(() => { msgEl.innerHTML = ''; }, 4000);
        } else {
            msgEl.innerHTML = `<small class="text-danger">${res.error || 'Failed to send feedback.'}</small>`;
        }
    }
};
