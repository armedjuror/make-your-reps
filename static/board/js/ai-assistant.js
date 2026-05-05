/**
 * ai-assistant.js — /ai command handler and chat modal
 */

const AIAssistant = {
    history: [],  // [{role, content}] for multi-turn

    open(initialPrompt) {
        this.history = [];
        document.getElementById('ai-chat-messages').innerHTML = '';
        const modal = new bootstrap.Modal(document.getElementById('aiModal'));
        modal.show();
        document.getElementById('aiModal').addEventListener('shown.bs.modal', () => {
            document.getElementById('ai-chat-input').focus();
            if (initialPrompt) {
                document.getElementById('ai-chat-input').value = initialPrompt;
                this.send();
            }
        }, { once: true });
    },

    send() {
        const input = document.getElementById('ai-chat-input');
        const message = input.value.trim();
        if (!message) return;

        input.value = '';
        this._appendMessage('user', message);
        this._appendThinking();

        this.history.push({ role: 'user', content: message });

        apiClient.post('board/api/ai/', {
            message,
            history: this.history.slice(0, -1),
        }).then(res => {
            this._removeThinking();
            if (res.status === 'success') {
                this._appendMessage('assistant', res.reply, res.actions);
                this.history.push({ role: 'assistant', content: res.reply });
                if (res.actions && res.actions.length > 0) {
                    const types = res.actions.map(a => a.type);
                    const taskTypes = ['task_created', 'task_modified', 'task_deleted', 'task_toggled', 'group_created', 'group_modified', 'group_deleted'];
                    const habitTypes = ['habit_created', 'habit_modified', 'habit_deleted', 'habit_logged'];
                    if (types.some(t => taskTypes.includes(t))) TodosPane.loadTodos();
                    if (types.some(t => habitTypes.includes(t))) Habits.init();
                }
            } else {
                this._appendMessage('assistant', res.error || 'Something went wrong.');
            }
        }).catch(() => {
            this._removeThinking();
            this._appendMessage('assistant', 'Failed to reach AI. Check your connection.');
        });
    },

    _appendMessage(role, text, actions) {
        const container = document.getElementById('ai-chat-messages');
        const div = document.createElement('div');
        div.className = `ai-message ai-message-${role}`;

        const formatted = text
            .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
            .replace(/^- (.+)$/gm, '<li>$1</li>')
            .replace(/(<li>.*<\/li>)/s, '<ul>$1</ul>')
            .replace(/\n/g, '<br>');

        div.innerHTML = `<div class="ai-bubble">${formatted}</div>`;

        if (actions && actions.length > 0) {
            const actionsEl = document.createElement('div');
            actionsEl.className = 'ai-actions-taken';
            actionsEl.innerHTML = actions.map(a =>
                `<span class="ai-action-chip"><i class="fas fa-check-circle"></i> ${a.label || a.type}</span>`
            ).join('');
            div.appendChild(actionsEl);
        }

        container.appendChild(div);
        container.scrollTop = container.scrollHeight;
    },

    _appendThinking() {
        const container = document.getElementById('ai-chat-messages');
        const div = document.createElement('div');
        div.className = 'ai-message ai-message-assistant';
        div.id = 'ai-thinking-indicator';
        div.innerHTML = '<div class="ai-bubble ai-thinking-text">Thinking…</div>';
        container.appendChild(div);
        container.scrollTop = container.scrollHeight;
    },

    _removeThinking() {
        document.getElementById('ai-thinking-indicator')?.remove();
    },
};

document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('ai-chat-input')?.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') AIAssistant.send();
    });
});
