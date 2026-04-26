/**
 * todos-pane.js — Full todos pane with groups, filters, CRUD
 */

const TodosPane = {
    groups: [],
    todos: [],
    selectedGroup: 'all',
    filter: 'pending', // 'pending' | 'done' | 'all'

    async init() {
        await this.loadGroups();
        await this.loadTodos();
        this.setupEnterKey();
        document.getElementById('todos-manage-groups-btn').addEventListener('click', () => this.showManageGroupsModal());
    },

    setupEnterKey() {
        const input = document.getElementById('todoPaneInput');
        if (input) {
            input.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') this.addTask();
            });
        }
    },

    // ── Groups ──
    async loadGroups() {
        const res = await apiClient.get('board/api/task_groups/');
        if (res.status === 'success') {
            this.groups = res.data;
            this.renderGroups();
            this.populateGroupSelects();
        }
    },

    renderGroups() {
        const list = document.getElementById('todos-group-list');
        if (!list) return;

        const allCount = this.groups.reduce((sum, g) => sum + g.pending_count, 0);

        let html = `
            <div class="todos-group-item ${this.selectedGroup === 'all' ? 'active' : ''}"
                 data-group="all" onclick="TodosPane.selectGroup('all')">
                <span class="group-name">All</span>
                <span class="group-count">${allCount}</span>
            </div>
        `;

        html += this.groups.map(g => `
            <div class="todos-group-item ${this.selectedGroup == g.id ? 'active' : ''}"
                 data-group="${g.id}" onclick="TodosPane.selectGroup(${g.id})">
                <span class="group-name">${g.name}</span>
                <span class="group-count">${g.pending_count}</span>
                <div class="group-actions">
                    <button class="btn-icon" onclick="event.stopPropagation(); TodosPane.showRenameGroupModal(${g.id}, '${g.name.replace(/'/g, "\\'")}')"><i class="fas fa-pen fa-xs"></i></button>
                    <button class="btn-icon" onclick="event.stopPropagation(); TodosPane.deleteGroup(${g.id}, '${g.name.replace(/'/g, "\\'")}')"><i class="fas fa-trash fa-xs"></i></button>
                </div>
            </div>
        `).join('');

        list.innerHTML = html;
    },

    populateGroupSelects() {
        const options = this.groups.map(g =>
            `<option value="${g.id}">${g.name}</option>`
        ).join('');

        // Todos pane group select
        const paneSelect = document.getElementById('todoPaneGroupSelect');
        if (paneSelect) paneSelect.innerHTML = options;

        // Quick-add modal group select
        const quickSelect = document.getElementById('quickTodoGroup');
        if (quickSelect) quickSelect.innerHTML = options;
    },

    selectGroup(groupId) {
        this.selectedGroup = groupId;
        const title = document.getElementById('todos-current-group-title');
        if (groupId === 'all') {
            title.textContent = 'All Tasks';
        } else {
            const g = this.groups.find(g => g.id == groupId);
            title.textContent = g ? g.name : 'Tasks';
        }
        this.renderGroups();
        this.loadTodos();
    },

    setFilter(filter) {
        this.filter = filter;
        document.querySelectorAll('.todo-filter').forEach(b => b.classList.remove('active'));
        document.querySelector(`.todo-filter[data-filter="${filter}"]`).classList.add('active');
        this.loadTodos();
    },

    showAddGroupModal() {
        document.getElementById('groupNameInput').value = '';
        document.getElementById('groupEditId').value = '';
        document.getElementById('groupModalTitle').innerHTML = '<div class="modal-icon info"><i class="fas fa-folder-plus"></i></div> New Group';
        new bootstrap.Modal(document.getElementById('groupModal')).show();
        setTimeout(() => document.getElementById('groupNameInput').focus(), 300);
    },

    showRenameGroupModal(id, name) {
        document.getElementById('groupNameInput').value = name;
        document.getElementById('groupEditId').value = id;
        document.getElementById('groupModalTitle').innerHTML = '<div class="modal-icon info"><i class="fas fa-pen"></i></div> Rename Group';
        new bootstrap.Modal(document.getElementById('groupModal')).show();
        setTimeout(() => document.getElementById('groupNameInput').focus(), 300);
    },

    async saveGroup() {
        const name = document.getElementById('groupNameInput').value.trim();
        const editId = document.getElementById('groupEditId').value;
        if (!name) return;

        let res;
        if (editId) {
            res = await apiClient.put(`board/api/task_groups/${editId}/`, { name });
        } else {
            res = await apiClient.post('board/api/task_groups/', { name });
        }

        if (res.status === 'success') {
            bootstrap.Modal.getInstance(document.getElementById('groupModal')).hide();
            await this.loadGroups();
        } else {
            showError(res.error);
        }
    },

    async deleteGroup(id, name) {
        if (!confirm(`Delete "${name}"? Tasks will be moved to General.`)) return;
        const res = await apiClient.delete(`board/api/task_groups/${id}/`);
        if (res.status === 'success') {
            if (this.selectedGroup == id) this.selectedGroup = 'all';
            await this.loadGroups();
            await this.loadTodos();
        } else {
            showError(res.error);
        }
    },

    // ── Tasks ──
    async loadTodos() {
        let url = 'board/api/tasks/?';
        if (this.selectedGroup !== 'all') url += `group=${this.selectedGroup}&`;
        if (this.filter === 'pending') url += 'done=false';
        else if (this.filter === 'done') url += 'done=true';

        const res = await apiClient.get(url);
        if (res.status === 'success') {
            this.todos = res.data;
            this.renderTodos();
        }
    },

    renderTodos() {
        const list = document.getElementById('todos-pane-list');
        if (!list) return;

        if (this.todos.length === 0) {
            const msg = this.filter === 'done' ? 'No completed tasks yet.' : 'All clear! No pending tasks.';
            list.innerHTML = `<h6 class="text-center mt-4 todo-empty-msg">${msg}</h6>`;
            return;
        }

        const clockFormat = document.body.getAttribute('data-clock') || '12h';

        list.innerHTML = this.todos.map(todo => {
            let deadlineHtml = '';
            if (todo.deadline) {
                const d = new Date(todo.deadline);
                const now = new Date();
                const isOverdue = !todo.is_done && d < now;
                const opts = clockFormat === '24h'
                    ? { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false }
                    : { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', hour12: true };
                deadlineHtml = `<span class="todo-deadline ${isOverdue ? 'overdue' : ''}">${d.toLocaleString('en-US', opts)}</span>`;
            }

            const groupLabel = todo.group_name ? `<span class="todo-group-badge">${todo.group_name}</span>` : '';

            return `
                <div class="todo-item-row ${todo.is_done ? 'completed' : ''}">
                    <div class="todo-check" onclick="TodosPane.toggleTodo(${todo.id}, ${todo.is_done})">
                        <i class="${todo.is_done ? 'fas fa-check-square' : 'far fa-square'}"></i>
                    </div>
                    <div class="todo-info">
                        <span class="todo-text-main" onclick="TodosPane.toggleTodo(${todo.id}, ${todo.is_done})">${todo.task_name}</span>
                        <div class="todo-meta">
                            ${groupLabel}
                            ${deadlineHtml}
                        </div>
                    </div>
                    <button class="btn-icon todo-edit" onclick="TodosPane.showEditTaskModal(${todo.id})">
                        <i class="fas fa-pen fa-xs"></i>
                    </button>
                    <button class="btn-icon todo-delete" onclick="TodosPane.deleteTodo(${todo.id})">
                        <i class="fas fa-trash"></i>
                    </button>
                </div>
            `;
        }).join('');
    },

    async addTask() {
        const input = document.getElementById('todoPaneInput');
        const groupSelect = document.getElementById('todoPaneGroupSelect');
        const deadlineInput = document.getElementById('todoPaneDeadline');

        const task_name = input.value.trim();
        if (!task_name) return;

        const data = { task_name };
        if (groupSelect.value) data.group = parseInt(groupSelect.value);
        if (deadlineInput.value) data.deadline = new Date(deadlineInput.value).toISOString();

        const res = await apiClient.post('board/api/tasks/', data);
        if (res.status === 'success') {
            input.value = '';
            deadlineInput.value = '';
            await this.loadTodos();
            await this.loadGroups(); // refresh counts
        } else {
            showError(res.error);
        }
    },

    async toggleTodo(id, isDone) {
        const res = await apiClient.put(`board/api/tasks/${id}/`, { is_done: !isDone });
        if (res.status === 'success') {
            if (res.gamification) {
                document.dispatchEvent(new CustomEvent('gamification', {detail: res.gamification}));
            }
            await this.loadTodos();
            await this.loadGroups();
            General.loadProductivityScore();
        }
    },

    async deleteTodo(id) {
        const res = await apiClient.delete(`board/api/tasks/${id}/`);
        if (res.status === 'success') {
            await this.loadTodos();
            await this.loadGroups();
        }
    },

    showEditTaskModal(id) {
        const todo = this.todos.find(t => t.id === id);
        if (!todo) return;

        document.getElementById('editTaskId').value = id;
        document.getElementById('editTaskName').value = todo.task_name;

        // Populate group select
        const select = document.getElementById('editTaskGroup');
        select.innerHTML = this.groups.map(g =>
            `<option value="${g.id}" ${g.id == todo.group ? 'selected' : ''}>${g.name}</option>`
        ).join('');

        // Set deadline
        const deadlineInput = document.getElementById('editTaskDeadline');
        if (todo.deadline) {
            const d = new Date(todo.deadline);
            const pad = n => String(n).padStart(2, '0');
            deadlineInput.value = `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
        } else {
            deadlineInput.value = '';
        }

        new bootstrap.Modal(document.getElementById('editTaskModal')).show();
        setTimeout(() => document.getElementById('editTaskName').focus(), 300);
    },

    async saveEditTask() {
        const id = document.getElementById('editTaskId').value;
        const task_name = document.getElementById('editTaskName').value.trim();
        if (!task_name) return;

        const data = { task_name, group: parseInt(document.getElementById('editTaskGroup').value) };
        const deadlineVal = document.getElementById('editTaskDeadline').value;
        data.deadline = deadlineVal ? new Date(deadlineVal).toISOString() : null;

        const res = await apiClient.put(`board/api/tasks/${id}/`, data);
        if (res.status === 'success') {
            bootstrap.Modal.getInstance(document.getElementById('editTaskModal')).hide();
            await this.loadTodos();
            await this.loadGroups();
        } else {
            showError(res.error);
        }
    },

    // ── Manage Groups ──
    showManageGroupsModal() {
        this.renderManageGroupsList();
        new bootstrap.Modal(document.getElementById('manageGroupsModal')).show();
    },

    renderManageGroupsList() {
        const list = document.getElementById('manageGroupsList');
        if (!list) return;
        if (this.groups.length === 0) {
            list.innerHTML = '<p class="text-center text-brown small">No groups yet.</p>';
            return;
        }
        list.innerHTML = this.groups.map(g => {
            const isGeneral = g.name.toLowerCase() === 'general';
            const deleteBtn = isGeneral
                ? `<button class="btn btn-paper btn-sm" disabled title="Cannot delete General group"><i class="fas fa-trash fa-xs"></i></button>`
                : `<button class="btn btn-paper btn-sm" style="color:var(--ink-red);" onclick="TodosPane.deleteGroupFromManager(${g.id}, '${g.name.replace(/'/g, "\\'")}')"><i class="fas fa-trash fa-xs"></i></button>`;
            return `
                <div class="d-flex align-items-center gap-2 py-2 border-bottom">
                    <span style="flex:1">${g.name}</span>
                    <span class="text-brown small">${g.pending_count} pending</span>
                    <button class="btn btn-paper btn-sm" onclick="TodosPane.renameGroupFromManager(${g.id}, '${g.name.replace(/'/g, "\\'")}')"><i class="fas fa-pen fa-xs"></i></button>
                    ${deleteBtn}
                </div>`;
        }).join('');
    },

    renameGroupFromManager(id, name) {
        bootstrap.Modal.getInstance(document.getElementById('manageGroupsModal')).hide();
        setTimeout(() => this.showRenameGroupModal(id, name), 350);
    },

    addGroupFromManager() {
        bootstrap.Modal.getInstance(document.getElementById('manageGroupsModal')).hide();
        setTimeout(() => this.showAddGroupModal(), 350);
    },

    async deleteGroupFromManager(id, name) {
        if (!confirm(`Delete "${name}"? Tasks will be moved to General.`)) return;
        const res = await apiClient.delete(`board/api/task_groups/${id}/`);
        if (res.status === 'success') {
            if (this.selectedGroup == id) this.selectedGroup = 'all';
            await this.loadGroups();
            this.renderManageGroupsList();
            await this.loadTodos();
        } else {
            showError(res.error);
        }
    }
};

function initTodosPane() {
    TodosPane.init();
}