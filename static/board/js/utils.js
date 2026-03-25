

class ApiClient {
    constructor(baseURL = '', refreshEndpoint = '/auth/refresh') {
        this.baseURL = baseURL;
        this.refreshEndpoint = refreshEndpoint;
        this.isRefreshing = false;
        this.failedQueue = [];
    }

    // Get access token from localStorage
    getAccessToken() {
        return localStorage.getItem('access_token');
    }

    // Set access token in localStorage
    setAccessToken(token) {
        localStorage.setItem('access_token', token);
    }

    // Remove access token from localStorage
    removeAccessToken() {
        localStorage.removeItem('access_token');
    }

    // Process queued requests after token refresh
    processQueue(error, token = null) {
        this.failedQueue.forEach(({ resolve, reject }) => {
            if (error) {
                reject(error);
            } else {
                resolve(token);
            }
        });

        this.failedQueue = [];
    }

    getCSRFToken() {
        const name = 'csrftoken';
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }

    // Refresh access token using refresh token from cookies
    async refreshToken() {
        try {
            const response = await fetch(`${this.baseURL}${this.refreshEndpoint}`, {
                method: 'POST',
                credentials: 'include', // Include cookies (refresh token)
                headers: {
                    'Content-Type': 'application/json',
                }
            });

            const data = await response.json();

            if (response.ok && data.status === 'success') {
                const newAccessToken = data.data.access_token || data.data.accessToken;
                this.setAccessToken(newAccessToken);
                return newAccessToken;
            } else {
                throw new Error(data.error || 'Token refresh failed');
            }
        } catch (error) {
            this.removeAccessToken();
            throw error;
        }
    }

    // Main API call method
    async makeRequest(url, options = {}) {
        $('#loader').fadeIn()
        const accessToken = this.getAccessToken();
        const csrfToken = this.getCSRFToken();
        // Prepare request options
        const requestOptions = {
            ...options,
            headers: {
                'Content-Type': 'application/json',
                ...options.headers,
                ...(accessToken && { 'Authorization': `Bearer ${accessToken}` }),
                ...(csrfToken && options.method !== 'GET' && { 'X-CSRFToken': csrfToken })
            }
        };

        try {
            const response = await fetch(`${this.baseURL}${url}`, requestOptions);
            const data = await response.json();

            // If request is successful, return the data
            if (response.ok) {
                $('#loader').fadeOut()
                return data;
            }

            // If we get a 401 (Unauthorized), try to refresh the token
            if (response.status === 401) {
                return await this.handleTokenRefresh(url, options);
            }
            $('#loader').fadeOut()
            // For other errors, return the error response
            return data;

        } catch (error) {
            $('#loader').fadeOut()
            return {
                status: 'failed',
                error: error.message || 'Network error occurred'
            };
        }
    }

    // Handle token refresh and retry logic
    async handleTokenRefresh(url, options) {
        // If already refreshing, queue this request
        if (this.isRefreshing) {
            return new Promise((resolve, reject) => {
                this.failedQueue.push({ resolve, reject });
            }).then(() => {
                // Retry the original request with new token
                return this.makeRequest(url, options);
            });
        }

        this.isRefreshing = true;

        try {
            const newAccessToken = await this.refreshToken();
            this.processQueue(null, newAccessToken);

            // Retry the original request with new token
            const accessToken = this.getAccessToken();
            const retryOptions = {
                ...options,
                headers: {
                    'Content-Type': 'application/json',
                    ...options.headers,
                    'Authorization': `Bearer ${accessToken}`
                }
            };

            const response = await fetch(`${this.baseURL}${url}`, retryOptions);
            const data = await response.json();

            return data;

        } catch (refreshError) {
            this.processQueue(refreshError, null);

            // If refresh fails, redirect to login or return error
            return {
                status: 'failed',
                error: 'Authentication failed. Please login again.'
            };
        } finally {
            this.isRefreshing = false;
        }
    }

    // Convenience methods for different HTTP methods
    async get(url, options = {}) {
        return this.makeRequest(url, { ...options, method: 'GET' });
    }

    async post(url, data, options = {}) {
        return this.makeRequest(url, {
            ...options,
            method: 'POST',
            body: JSON.stringify(data)
        });
    }

    async put(url, data, options = {}) {
        return this.makeRequest(url, {
            ...options,
            method: 'PUT',
            body: JSON.stringify(data)
        });
    }

    async patch(url, data, options = {}) {
        return this.makeRequest(url, {
            ...options,
            method: 'PATCH',
            body: JSON.stringify(data)
        });
    }

    async delete(url, options = {}) {
        return this.makeRequest(url, { ...options, method: 'DELETE' });
    }
}

const apiClient = new ApiClient(HOST, 'refresh/');


// Modal functions
function showSuccess(message, title="Woohoo!") {
    document.getElementById('successModalLabel').textContent = title;
    document.getElementById('successMessage').textContent = message;
    const successModal = new bootstrap.Modal(document.getElementById('successModal'));
    successModal.show();
}

function showError(message, title="Oops, Something went wrong!") {
    document.getElementById('errorModalLabel').textContent = title;
    document.getElementById('errorMessage').textContent = message;
    const errorModal = new bootstrap.Modal(document.getElementById('errorModal'));
    errorModal.show();
}

function showInfo(message, title="Did you know?") {
    document.getElementById('infoModalLabel').textContent = title;
    document.getElementById('infoMessage').textContent = message;
    const infoModal = new bootstrap.Modal(document.getElementById('infoModal'));
    infoModal.show();
}

function getDate(date){
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

function createHabitElement(habitEl){
    const habitRow = document.createElement('div');
    habitRow.className = 'habit-row';

    // Create habit name div
    const habitName = document.createElement('div');
    habitName.className = 'habit-name';
    habitName.innerHTML = `I will<h5>${habitEl.habit}</h5><h6>${habitEl.detail}</h6>so that I can become<h6>${habitEl.identity}</h6>`;

    // Create habit days container
    const habitDays = document.createElement('div');
    habitDays.className = 'habit-days';

    // Create individual day elements
    for (const [key, value] of Object.entries(habitEl.stats.logs)){
        const dayElement = document.createElement('div');
        dayElement.className = 'habit-day';
        dayElement.setAttribute('data-day', key);
        dayElement.setAttribute('data-habit', habitEl.id);
        dayElement.textContent = value.date;

        // Add 'checked' class if this day is completed
        if (value.is_done) {
            dayElement.classList.add('checked');
        }

        dayElement.onclick = () => toggleHabit(habitEl.id, key)

        habitDays.appendChild(dayElement);
    }

    // Create habit remark div
    const habitRemark = document.createElement('div');
    habitRemark.className = 'habit-remark';
    habitRemark.setAttribute('data-habit', habitEl.id);
    habitRemark.textContent = habitEl.remark;

    // Create the button
    const button = document.createElement('button');
    button.className = 'btn btn-paper btn-primary btn-sm';
    button.innerHTML = '<i class="fa fa-cog"></i>';
    button.onclick = () => showHabitSettings(`${habitEl.id}`, `${habitEl.habit}`, `${habitEl.detail}`, `${habitEl.identity}`, habitEl.notify_at || null);

    // Append all elements to habit row
    habitRow.appendChild(habitName);
    habitRow.appendChild(habitDays);
    habitRow.appendChild(habitRemark);
    habitRow.appendChild(button);

    // Append habit row to container
    return habitRow
}