// Splitwise JavaScript Functions

// Global state management
const SplitwiseApp = {
    currentUser: null,
    categories: [],
    groups: [],
    friends: [],
    expenses: [],
    settlements: [],

    init() {
        this.currentUser = window.currentUser;
        this.bindEvents();
        this.setDefaultDates();
    },

    bindEvents() {
        // Split type change handlers
        document.querySelectorAll('input[name="splitType"]').forEach(radio => {
            radio.addEventListener('change', this.handleSplitTypeChange);
        });

        // Group selection change
        document.getElementById('expenseGroup')?.addEventListener('change', this.handleGroupChange);

        // Settlement suggestions
        document.getElementById('settlementFrom')?.addEventListener('change', this.loadSettlementSuggestions);
        document.getElementById('settlementTo')?.addEventListener('change', this.loadSettlementSuggestions);
    },

    setDefaultDates() {
        const today = new Date().toISOString().split('T')[0];
        document.getElementById('expenseDate').value = today;
        document.getElementById('settlementDate').value = today;
    }
};

// Initialize app when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    SplitwiseApp.init();
});

// Load functions
async function loadGroups() {
    try {
        const response = await apiClient.get('splitwise/api/groups/');

        if (response.status === 'success') {
            userGroups = response.data;
            updateGroupsList(response.data);
            populateGroupSelects();
        }
    } catch (error) {
        console.error('Error loading groups:', error);
    }
}

async function loadFriends() {
    try {
        const response = await apiClient.get('splitwise/api/friends/');

        if (response.status === 'success') {
            userFriends = response.data;
            updateFriendsList(response.data);
        }
    } catch (error) {
        console.error('Error loading friends:', error);
    }
}

async function loadExpenses() {
    try {
        const response = await apiClient.get('splitwise/api/expenses/recent/');

        if (response.status === 'success') {
            updateRecentExpenses(response.data);
        }
    } catch (error) {
        console.error('Error loading expenses:', error);
    }
}

async function loadBalances() {
    try {
        const response = await apiClient.get('splitwise/api/dashboard/balances/');

        if (response.status === 'success') {
            updateBalancesList(response.data);
        }
    } catch (error) {
        console.error('Error loading balances:', error);
    }
}

// Update UI functions
function updateGroupsList(groups) {
    const container = document.getElementById('groupsList');

    if (!groups || groups.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <i class="fas fa-users"></i>
                <p>No groups yet</p>
                <button class="btn btn-splitwise btn-sm" onclick="showCreateGroupModal()">
                    <i class="fas fa-plus me-1"></i>Create your first group
                </button>
            </div>
        `;
        return;
    }

    container.innerHTML = groups.map(group => `
        <div class="group-item" onclick="viewGroupDetails('${group.id}')">
            <div>
                <div class="group-name">${group.name}</div>
                <div class="group-meta">${group.member_count} members • $${group.total_expenses.toFixed(2)} total</div>
            </div>
            <div class="text-end">
                <button class="btn btn-splitwise btn-sm" onclick="event.stopPropagation(); addExpenseToGroup('${group.id}')">
                    <i class="fas fa-plus"></i>
                </button>
            </div>
        </div>
    `).join('');
}

function updateFriendsList(friends) {
    const container = document.getElementById('friendsList');

    if (!friends || friends.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <i class="fas fa-user-friends"></i>
                <p>No friends added yet</p>
                <button class="btn btn-splitwise btn-sm" onclick="showAddFriendModal()">
                    <i class="fas fa-plus me-1"></i>Add your first friend
                </button>
            </div>
        `;
        return;
    }

    container.innerHTML = friends.map(friend => `
        <div class="friend-item">
            <div>
                <div class="friend-name">${friend.friend.display_name}</div>
                <div class="friend-meta">${friend.friend.email}</div>
            </div>
            <div class="text-end">
                <button class="btn btn-splitwise btn-sm" onclick="createExpenseWithFriend(${friend.friend.id})">
                    <i class="fas fa-plus"></i>
                </button>
            </div>
        </div>
    `).join('');
}

function updateBalancesList(balances) {
    const container = document.getElementById('balancesList');

    if (!balances || balances.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <i class="fas fa-balance-scale"></i>
                <p>All settled up!</p>
            </div>
        `;
        return;
    }

    container.innerHTML = balances.map(balance => {
        const amount = Math.abs(balance.total_balance);
        const isOwed = balance.total_balance > 0;

        return `
            <div class="balance-item">
                <div>
                    <div class="balance-name">${balance.user.display_name}</div>
                    <div class="balance-meta">
                        ${isOwed ? 'owes you' : 'you owe'} 
                        <span class="${isOwed ? 'balance-positive' : 'balance-negative'}">
                            $${amount.toFixed(2)}
                        </span>
                    </div>
                </div>
                <div class="text-end">
                    <button class="btn btn-splitwise btn-sm" onclick="settleWithUser(${balance.user.id}, ${amount})">
                        <i class="fas fa-handshake"></i> Settle
                    </button>
                </div>
            </div>
        `;
    }).join('');
}

// Modal functions
function showAddExpenseModal() {
    populateGroupSelects();
    setupSplitParticipants();
    const modal = new bootstrap.Modal(document.getElementById('addExpenseModal'));
    modal.show();
}

function showCreateGroupModal() {
    document.getElementById('groupForm').reset();
    document.getElementById('groupMembers').innerHTML = `
        <div class="alert alert-info">
            <i class="fas fa-info-circle me-2"></i>
            You'll be added as the group creator automatically.
        </div>
    `;
    groupMembers = [];
    const modal = new bootstrap.Modal(document.getElementById('createGroupModal'));
    modal.show();
}

function showAddFriendModal() {
    document.getElementById('friendForm').reset();
    document.getElementById('friendSearchResults').innerHTML = '';
    const modal = new bootstrap.Modal(document.getElementById('addFriendModal'));
    modal.show();
}

function showSettleUpModal() {
    populateSettlementUsers();
    loadSettlementSuggestions();
    const modal = new bootstrap.Modal(document.getElementById('settleUpModal'));
    modal.show();
}

// Populate select options
function populateGroupSelects() {
    const expenseGroupSelect = document.getElementById('expenseGroup');
    const settlementGroupSelect = document.getElementById('settlementGroup');

    if (expenseGroupSelect) {
        expenseGroupSelect.innerHTML = '<option value="">Personal expense</option>';
        userGroups.forEach(group => {
            const option = document.createElement('option');
            option.value = group.id;
            option.textContent = group.name;
            expenseGroupSelect.appendChild(option);
        });
    }

    if (settlementGroupSelect) {
        settlementGroupSelect.innerHTML = '<option value="">Personal settlement</option>';
        userGroups.forEach(group => {
            const option = document.createElement('option');
            option.value = group.id;
            option.textContent = group.name;
            settlementGroupSelect.appendChild(option);
        });
    }
}

function populateSettlementUsers() {
    const fromSelect = document.getElementById('settlementFrom');
    const toSelect = document.getElementById('settlementTo');

    // Add current user
    fromSelect.innerHTML = `<option value="${currentUser}">${currentUserName} (You)</option>`;
    toSelect.innerHTML = '<option value="">Select person...</option>';

    // Add friends
    userFriends.forEach(friend => {
        const option1 = document.createElement('option');
        option1.value = friend.friend.id;
        option1.textContent = friend.friend.display_name;
        fromSelect.appendChild(option1);

        const option2 = document.createElement('option');
        option2.value = friend.friend.id;
        option2.textContent = friend.friend.display_name;
        toSelect.appendChild(option2);
    });
}

// Split type handling
function handleSplitTypeChange(event) {
    const splitType = event.target.value;
    setupSplitParticipants(splitType);
}

function handleGroupChange(event) {
    const groupId = event.target.value;
    setupSplitParticipants(null, groupId);
}

function setupSplitParticipants(splitType = null, groupId = null) {
    const container = document.getElementById('splitParticipants');
    const currentSplitType = splitType || document.querySelector('input[name="splitType"]:checked')?.value || 'equal';
    const selectedGroupId = groupId || document.getElementById('expenseGroup')?.value;

    let participants = [{ id: currentUser, name: currentUserName + ' (You)' }];

    // Add group members or friends
    if (selectedGroupId) {
        const group = userGroups.find(g => g.id === selectedGroupId);
        if (group && group.members) {
            participants = group.members.map(member => ({
                id: member.id,
                name: member.display_name + (member.id === currentUser ? ' (You)' : '')
            }));
        }
    } else {
        // Add friends for personal expenses
        userFriends.forEach(friend => {
            participants.push({
                id: friend.friend.id,
                name: friend.friend.display_name
            });
        });
    }

    container.innerHTML = participants.map(participant => {
        let inputField = '';

        switch (currentSplitType) {
            case 'equal':
                inputField = `<span class="text-muted">Equal split</span>`;
                break;
            case 'exact':
                inputField = `
                    <div class="input-group input-group-sm">
                        <span class="input-group-text">$</span>
                        <input type="number" class="form-control" step="0.01" 
                               data-user-id="${participant.id}" data-type="amount" placeholder="0.00">
                    </div>
                `;
                break;
            case 'percentage':
                inputField = `
                    <div class="input-group input-group-sm">
                        <input type="number" class="form-control" step="0.01" min="0" max="100"
                               data-user-id="${participant.id}" data-type="percentage" placeholder="0">
                        <span class="input-group-text">%</span>
                    </div>
                `;
                break;
            case 'shares':
                inputField = `
                    <input type="number" class="form-control form-control-sm" min="1"
                           data-user-id="${participant.id}" data-type="shares" placeholder="1" value="1">
                `;
                break;
        }

        return `
            <div class="d-flex align-items-center justify-content-between mb-2">
                <div class="form-check">
                    <input class="form-check-input" type="checkbox" 
                           value="${participant.id}" id="participant_${participant.id}" 
                           ${participant.id === currentUser ? 'checked' : ''}>
                    <label class="form-check-label" for="participant_${participant.id}">
                        ${participant.name}
                    </label>
                </div>
                <div style="width: 120px;">
                    ${inputField}
                </div>
            </div>
        `;
    }).join('');
}

// Save functions
async function saveExpense() {
    const btn = event.target;
    toggleButtonLoading(btn, true);

    try {
        const formData = gatherExpenseFormData();

        if (!validateExpenseForm(formData)) {
            toggleButtonLoading(btn, false);
            return;
        }

        const response = await apiClient.post('splitwise/api/expenses/', formData);

        if (response.status === 'success') {
            showSuccess('Expense added successfully!');
            bootstrap.Modal.getInstance(document.getElementById('addExpenseModal')).hide();
            loadDashboardSummary();
            document.getElementById('expenseForm').reset();
        } else {
            showError(response.error || 'Failed to add expense');
        }
    } catch (error) {
        console.error('Error saving expense:', error);
        showError('Failed to add expense. Please try again.');
    } finally {
        toggleButtonLoading(btn, false);
    }
}

async function saveGroup() {
    const btn = event.target;
    toggleButtonLoading(btn, true);

    try {
        const formData = {
            name: document.getElementById('groupName').value.trim(),
            description: document.getElementById('groupDescription').value.trim(),
            member_emails: groupMembers
        };

        if (!formData.name) {
            showError('Group name is required');
            toggleButtonLoading(btn, false);
            return;
        }

        const response = await apiClient.post('splitwise/api/groups/', formData);

        if (response.status === 'success') {
            showSuccess('Group created successfully!');
            bootstrap.Modal.getInstance(document.getElementById('createGroupModal')).hide();
            loadGroups();
            document.getElementById('groupForm').reset();
            groupMembers = [];
        } else {
            showError(response.error || 'Failed to create group');
        }
    } catch (error) {
        console.error('Error saving group:', error);
        showError('Failed to create group. Please try again.');
    } finally {
        toggleButtonLoading(btn, false);
    }
}

async function saveFriend() {
    const btn = event.target;
    toggleButtonLoading(btn, true);

    try {
        const email = document.getElementById('friendEmail').value.trim();

        if (!email) {
            showError('Email is required');
            toggleButtonLoading(btn, false);
            return;
        }

        const response = await apiClient.post('splitwise/api/friends/', {
            friend_email: email
        });

        if (response.status === 'success') {
            showSuccess('Friend added successfully!');
            bootstrap.Modal.getInstance(document.getElementById('addFriendModal')).hide();
            loadFriends();
            document.getElementById('friendForm').reset();
        } else {
            showError(response.error || 'Failed to add friend');
        }
    } catch (error) {
        console.error('Error saving friend:', error);
        showError('Failed to add friend. Please try again.');
    } finally {
        toggleButtonLoading(btn, false);
    }
}

async function saveSettlement() {
    const btn = event.target;
    toggleButtonLoading(btn, true);

    try {
        const formData = {
            from_user_id: parseInt(document.getElementById('settlementFrom').value),
            to_user_id: parseInt(document.getElementById('settlementTo').value),
            amount: parseFloat(document.getElementById('settlementAmount').value),
            settlement_date: document.getElementById('settlementDate').value,
            notes: document.getElementById('settlementNotes').value.trim(),
            group_id: document.getElementById('settlementGroup').value || null
        };

        if (!formData.from_user_id || !formData.to_user_id || !formData.amount) {
            showError('Please fill in all required fields');
            toggleButtonLoading(btn, false);
            return;
        }

        if (formData.from_user_id === formData.to_user_id) {
            showError('From and To users cannot be the same');
            toggleButtonLoading(btn, false);
            return;
        }

        const response = await apiClient.post('splitwise/api/settlements/', formData);

        if (response.status === 'success') {
            showSuccess('Settlement recorded successfully!');
            bootstrap.Modal.getInstance(document.getElementById('settleUpModal')).hide();
            loadDashboardSummary();
            document.getElementById('settlementForm').reset();
        } else {
            showError(response.error || 'Failed to record settlement');
        }
    } catch (error) {
        console.error('Error saving settlement:', error);
        showError('Failed to record settlement. Please try again.');
    } finally {
        toggleButtonLoading(btn, false);
    }
}

// Form data gathering
function gatherExpenseFormData() {
    const splitType = document.querySelector('input[name="splitType"]:checked').value;
    const selectedParticipants = Array.from(document.querySelectorAll('#splitParticipants input[type="checkbox"]:checked'));

    const splitData = selectedParticipants.map(checkbox => {
        const userId = parseInt(checkbox.value);
        const splitInfo = { user_id: userId };

        if (splitType === 'exact') {
            const amountInput = document.querySelector(`input[data-user-id="${userId}"][data-type="amount"]`);
            splitInfo.amount = parseFloat(amountInput.value) || 0;
        } else if (splitType === 'percentage') {
            const percentInput = document.querySelector(`input[data-user-id="${userId}"][data-type="percentage"]`);
            splitInfo.percentage = parseFloat(percentInput.value) || 0;
        } else if (splitType === 'shares') {
            const sharesInput = document.querySelector(`input[data-user-id="${userId}"][data-type="shares"]`);
            splitInfo.shares = parseInt(sharesInput.value) || 1;
        }

        return splitInfo;
    });

    return {
        description: document.getElementById('expenseDescription').value.trim(),
        amount: parseFloat(document.getElementById('expenseAmount').value),
        paid_by_id: parseInt(document.getElementById('expensePaidBy').value),
        expense_date: document.getElementById('expenseDate').value,
        category_id: document.getElementById('expenseCategory').value || null,
        group_id: document.getElementById('expenseGroup').value || null,
        split_type: splitType,
        notes: document.getElementById('expenseNotes').value.trim(),
        split_data: splitData
    };
}

// Form validation
function validateExpenseForm(formData) {
    if (!formData.description) {
        showError('Description is required');
        return false;
    }

    if (!formData.amount || formData.amount <= 0) {
        showError('Valid amount is required');
        return false;
    }

    if (!formData.split_data || formData.split_data.length === 0) {
        showError('At least one participant must be selected');
        return false;
    }

    // Validate split amounts/percentages
    if (formData.split_type === 'exact') {
        const totalSplit = formData.split_data.reduce((sum, split) => sum + split.amount, 0);
        if (Math.abs(totalSplit - formData.amount) > 0.01) {
            showError('Split amounts must equal the total expense amount');
            return false;
        }
    } else if (formData.split_type === 'percentage') {
        const totalPercent = formData.split_data.reduce((sum, split) => sum + split.percentage, 0);
        if (Math.abs(totalPercent - 100) > 0.01) {
            showError('Split percentages must total 100%');
            return false;
        }
    }

    return true;
}

// Group member management
function addGroupMember() {
    const emailInput = document.getElementById('memberEmail');
    const email = emailInput.value.trim();

    if (!email) {
        showError('Please enter an email address');
        return;
    }

    if (!isValidEmail(email)) {
        showError('Please enter a valid email address');
        return;
    }

    if (groupMembers.includes(email)) {
        showError('This email is already added');
        return;
    }

    groupMembers.push(email);
    emailInput.value = '';
    updateGroupMembersDisplay();
}

function removeGroupMember(email) {
    groupMembers = groupMembers.filter(member => member !== email);
    updateGroupMembersDisplay();
}

function updateGroupMembersDisplay() {
    const container = document.getElementById('groupMembers');

    if (groupMembers.length === 0) {
        container.innerHTML = `
            <div class="alert alert-info">
                <i class="fas fa-info-circle me-2"></i>
                You'll be added as the group creator automatically.
            </div>
        `;
        return;
    }

    container.innerHTML = `
        <div class="alert alert-info mb-2">
            <i class="fas fa-info-circle me-2"></i>
            You'll be added as the group creator automatically.
        </div>
        ${groupMembers.map(email => `
            <div class="d-flex justify-content-between align-items-center mb-2 p-2 border rounded">
                <span>${email}</span>
                <button type="button" class="btn btn-sm btn-outline-danger" onclick="removeGroupMember('${email}')">
                    <i class="fas fa-times"></i>
                </button>
            </div>
        `).join('')}
    `;
}

// Settlement suggestions
async function loadSettlementSuggestions() {
    try {
        const fromUser = document.getElementById('settlementFrom').value;
        const toUser = document.getElementById('settlementTo').value;
        const groupId = document.getElementById('settlementGroup').value;

        if (!fromUser && !toUser) {
            document.getElementById('settlementSuggestions').innerHTML = '<div class="text-muted">Select users to see suggestions</div>';
            return;
        }

        const params = new URLSearchParams();
        if (groupId) params.append('group_id', groupId);

        const response = await apiClient.get(`splitwise/api/settlements/suggestions/?${params}`);

        if (response.status === 'success') {
            updateSettlementSuggestions(response.data);
        }
    } catch (error) {
        console.error('Error loading settlement suggestions:', error);
    }
}

function updateSettlementSuggestions(suggestions) {
    const container = document.getElementById('settlementSuggestions');

    if (!suggestions || suggestions.length === 0) {
        container.innerHTML = '<div class="text-muted">No settlement suggestions available</div>';
        return;
    }

    container.innerHTML = suggestions.map(suggestion => `
        <div class="suggestion-item border rounded p-2 mb-2">
            <div class="d-flex justify-content-between align-items-center">
                <div>
                    <strong>${suggestion.from_user.display_name}</strong> should pay 
                    <strong>${suggestion.to_user.display_name}</strong>
                    <span class="text-success fw-bold">${suggestion.amount.toFixed(2)}</span>
                </div>
                <button class="btn btn-sm btn-outline-primary" onclick="useSuggestion(${suggestion.from_user.id}, ${suggestion.to_user.id}, ${suggestion.amount})">
                    Use
                </button>
            </div>
        </div>
    `).join('');
}

function useSuggestion(fromUserId, toUserId, amount) {
    document.getElementById('settlementFrom').value = fromUserId;
    document.getElementById('settlementTo').value = toUserId;
    document.getElementById('settlementAmount').value = amount.toFixed(2);
}

// WhatsApp notification
function notifyExpense() {
    currentWhatsAppData = {
        type: 'expense',
        expense_id: currentExpenseId
    };

    document.getElementById('whatsappPhone').value = '';
    document.getElementById('whatsappMessage').value = 'Loading message...';

    const modal = new bootstrap.Modal(document.getElementById('whatsappModal'));
    modal.show();

    // Generate message preview
    generateWhatsAppMessage();
}

function notifySettlement(settlementId) {
    currentWhatsAppData = {
        type: 'settlement',
        settlement_id: settlementId
    };

    document.getElementById('whatsappPhone').value = '';
    document.getElementById('whatsappMessage').value = 'Loading message...';

    const modal = new bootstrap.Modal(document.getElementById('whatsappModal'));
    modal.show();

    generateWhatsAppMessage();
}

async function generateWhatsAppMessage() {
    try {
        const response = await apiClient.post('splitwise/api/dashboard/whatsapp_notify/', {
            ...currentWhatsAppData,
            phone_number: '+1234567890' // Dummy number for preview
        });

        if (response.status === 'success') {
            document.getElementById('whatsappMessage').value = response.data.message;
        }
    } catch (error) {
        console.error('Error generating WhatsApp message:', error);
        document.getElementById('whatsappMessage').value = 'Error generating message';
    }
}

async function sendWhatsAppMessage() {
    const phoneNumber = document.getElementById('whatsappPhone').value.trim();

    if (!phoneNumber) {
        showError('Please enter a phone number');
        return;
    }

    try {
        const response = await apiClient.post('splitwise/api/dashboard/whatsapp_notify/', {
            ...currentWhatsAppData,
            phone_number: phoneNumber
        });

        if (response.status === 'success') {
            // Open WhatsApp with the generated URL
            window.open(response.data.whatsapp_url, '_blank');
            bootstrap.Modal.getInstance(document.getElementById('whatsappModal')).hide();
        } else {
            showError(response.error || 'Failed to generate WhatsApp message');
        }
    } catch (error) {
        console.error('Error sending WhatsApp message:', error);
        showError('Failed to generate WhatsApp message');
    }
}

// Expense details
async function showExpenseDetails(expenseId) {
    currentExpenseId = expenseId;

    try {
        const response = await apiClient.get(`splitwise/api/expenses/${expenseId}/`);

        if (response.status === 'success') {
            const expense = response.data;
            updateExpenseDetailsModal(expense);
            const modal = new bootstrap.Modal(document.getElementById('expenseDetailsModal'));
            modal.show();
        }
    } catch (error) {
        console.error('Error loading expense details:', error);
        showError('Failed to load expense details');
    }
}

function updateExpenseDetailsModal(expense) {
    const container = document.getElementById('expenseDetailsContent');

    container.innerHTML = `
        <div class="row">
            <div class="col-md-6">
                <h6>Expense Information</h6>
                <table class="table table-borderless">
                    <tr><td><strong>Description:</strong></td><td>${expense.description}</td></tr>
                    <tr><td><strong>Amount:</strong></td><td>${parseFloat(expense.amount).toFixed(2)}</td></tr>
                    <tr><td><strong>Paid by:</strong></td><td>${expense.paid_by.display_name}</td></tr>
                    <tr><td><strong>Date:</strong></td><td>${formatDate(expense.expense_date)}</td></tr>
                    <tr><td><strong>Split type:</strong></td><td class="split-type-badge">${expense.split_type}</td></tr>
                    ${expense.category ? `<tr><td><strong>Category:</strong></td><td>${expense.category.name}</td></tr>` : ''}
                    ${expense.is_group_expense ? `<tr><td><strong>Group:</strong></td><td>${expense.group?.name || 'Group'}</td></tr>` : ''}
                </table>
            </div>
            <div class="col-md-6">
                <h6>Split Details</h6>
                <div class="split-details">
                    ${expense.splits.map(split => `
                        <div class="d-flex justify-content-between align-items-center mb-2">
                            <span>${split.user.display_name}</span>
                            <span class="fw-bold">${parseFloat(split.amount).toFixed(2)}</span>
                        </div>
                    `).join('')}
                </div>
            </div>
        </div>
        ${expense.notes ? `
            <div class="mt-3">
                <h6>Notes</h6>
                <p class="text-muted">${expense.notes}</p>
            </div>
        ` : ''}
    `;
}

// Utility functions
function toggleButtonLoading(button, isLoading) {
    const textSpan = button.querySelector('.btn-text');
    const loadingSpan = button.querySelector('.btn-loading');

    if (isLoading) {
        textSpan.style.display = 'none';
        loadingSpan.style.display = 'inline';
        button.disabled = true;
    } else {
        textSpan.style.display = 'inline';
        loadingSpan.style.display = 'none';
        button.disabled = false;
    }
}

function formatDate(dateString) {
    const date = new Date(dateString);
    return date.toLocaleDateString('en-US', {
        year: 'numeric',
        month: 'short',
        day: 'numeric'
    });
}

function isValidEmail(email) {
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return emailRegex.test(email);
}

// Quick action functions
function addExpenseToGroup(groupId) {
    showAddExpenseModal();
    setTimeout(() => {
        document.getElementById('expenseGroup').value = groupId;
        handleGroupChange({ target: { value: groupId } });
    }, 100);
}

function createExpenseWithFriend(friendId) {
    showAddExpenseModal();
    setTimeout(() => {
        const checkbox = document.getElementById(`participant_${friendId}`);
        if (checkbox) {
            checkbox.checked = true;
        }
    }, 100);
}

function settleWithUser(userId, amount) {
    showSettleUpModal();
    setTimeout(() => {
        document.getElementById('settlementTo').value = userId;
        document.getElementById('settlementAmount').value = amount.toFixed(2);
    }, 100);
}

function viewGroupDetails(groupId) {
    // This could open a detailed group view
    console.log('View group details:', groupId);
    // For now, just show add expense for that group
    addExpenseToGroup(groupId);
}

// Error handling
function showSuccess(message) {
    document.getElementById('successMessage').textContent = message;
    const modal = new bootstrap.Modal(document.getElementById('successModal'));
    modal.show();
}

function showError(message) {
    document.getElementById('errorMessage').textContent = message;
    const modal = new bootstrap.Modal(document.getElementById('errorModal'));
    modal.show();
}