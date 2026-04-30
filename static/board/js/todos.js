const Todo = {
    showTodoModal() {
        document.getElementById('todoTask').value = '';
        document.getElementById('todoDeadline').value = '';
        document.getElementById('todoDeadlineStep').style.display = 'none';

        const el = document.getElementById('todoModal');
        const taskInput = document.getElementById('todoTask');

        taskInput.onkeyup = (e) => {
            if (taskInput.value.trim()) {
                document.getElementById('todoDeadlineStep').style.display = 'block';
            }else{
                document.getElementById('todoDeadlineStep').style.display = 'none';
            }
        };

        document.getElementById('todoDeadline').onkeyup = (e) => {
            if (e.key === 'Enter') Todo.saveTodo();
        };

        el.addEventListener('shown.bs.modal', () => requestAnimationFrame(() => taskInput.focus()), {once: true});
        new bootstrap.Modal(el).show();
        // After showing modal
        apiClient.get('board/api/task_groups/').then(res => {
            if (res.status === 'success') {
                const select = document.getElementById('todoGroup');
                select.innerHTML = res.data.map(g => `<option value="${g.id}">${g.name}</option>`).join('');
            }
        });
        document.getElementById('todoTask').focus()
    },
    saveTodo() {
        const task = document.getElementById('todoTask').value.trim();
        const deadline = document.getElementById('todoDeadline').value;
        const group = document.getElementById('todoGroup').value;
        if (group) data.group = parseInt(group);
        if (!task) return;

        const data = {task_name: task};
        if (deadline) data.deadline = new Date(deadline).toISOString();

        apiClient.post('board/api/tasks/', data).then(res => {
            if (res.status === 'success') {
                bootstrap.Modal.getInstance(document.getElementById('todoModal')).hide();
                showSuccess('Task added!');
                if (panesLoaded.trackers) loadTodos();
                if (panesLoaded.todos) { TodosPane.loadTodos(); TodosPane.loadGroups(); }
                General.loadProductivityScore();
            } else {
                showError(res.error);
            }
        });
    },
}