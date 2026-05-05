# AI Assistant Feature Spec

## Project Context

Django app: `board` (inside `StepsWeb/`). All board views live in `board/views.py`, URLs in `board/urls.py`, frontend JS in `static/board/js/`, HTML in `templates/board/dashboard.html`, CSS in `static/board/css/dashboard.css`.

**Auth**: Session-based. All views get the current user via `user_id = request.session.get('user_id')`. No DRF token auth.

**API response convention**:
```python
Response({'status': 'success', 'data': ...})
Response({'status': 'failed', 'error': '...'})
```

**Frontend API client**: `apiClient.post(path, body)` / `apiClient.get(path)` — returns a promise with the parsed JSON. Paths are relative (no leading `/`), e.g. `'board/api/ai/'`. Global helpers: `showSuccess(msg)`, `showError(msg)`.

---

## Feature: `/ai` Command

### Trigger

In `static/board/js/default-pane.js`, the `doSearch()` method handles the search bar (element `id="search-input"`). Modify it so that if the query starts with `/ai ` (case-insensitive), strip the prefix and open the AI modal instead of searching the web.

```js
doSearch() {
    const query = document.getElementById('search-input').value.trim();
    if (!query) return;

    if (query.toLowerCase().startsWith('/ai ')) {
        const prompt = query.slice(4).trim();
        document.getElementById('search-input').value = '';
        AIAssistant.open(prompt);
        return;
    }

    // existing search logic...
}
```

Also intercept the Enter keypress on the search input (already bound in dashboard.js or default-pane.js) to call `doSearch()`.

---

## Backend

### 1. Install dependency

```
pip install anthropic
```

Add `anthropic` to `requirements.txt`.

### 2. Environment variable

Read the API key from the environment: `os.environ.get('ANTHROPIC_API_KEY')`. The developer must set this in their `.env` or shell before running.

### 3. New view: `AIAssistantView`

Add to `board/views.py`:

```python
import anthropic as anthropic_sdk

class AIAssistantView(APIView):
    def post(self, request):
        user_id = request.session.get('user_id')
        if not user_id:
            return Response({'status': 'failed', 'error': 'Not authenticated'}, status=401)

        message = request.data.get('message', '').strip()
        history = request.data.get('history', [])  # list of {role, content} dicts
        if not message:
            return Response({'status': 'failed', 'error': 'Empty message'})

        api_key = os.environ.get('ANTHROPIC_API_KEY')
        if not api_key:
            return Response({'status': 'failed', 'error': 'AI not configured'})

        today = timezone.localdate()
        yesterday = today - timedelta(days=1)
        weekday = today.weekday()

        # --- Context snapshot ---
        # Today's pending tasks
        today_tasks = list(Task.objects.filter(
            user_id=user_id, is_deleted=False, is_done=False,
            deadline__date=today
        ).values('id', 'task_name', 'deadline'))
        # All pending tasks without deadline
        no_deadline_tasks = list(Task.objects.filter(
            user_id=user_id, is_deleted=False, is_done=False, deadline__isnull=True
        ).values('id', 'task_name'))

        # Active habits
        active_habits = list(Habit.objects.filter(user_id=user_id, status=HabitStatus.ACTIVE.value))
        habit_list = [{'id': h.id, 'name': h.habit, 'frequency': h.frequency} for h in active_habits]

        # Today's habit logs
        today_logs = set(HabitLog.objects.filter(
            habit__user_id=user_id, date=today, is_done=True
        ).values_list('habit_id', flat=True))
        # Yesterday's habit logs
        yesterday_logs = set(HabitLog.objects.filter(
            habit__user_id=user_id, date=yesterday, is_done=True
        ).values_list('habit_id', flat=True))

        habits_pending_today = [h for h in active_habits if (not h.frequency or weekday in h.frequency) and h.id not in today_logs]
        habits_missed_yesterday = [h for h in active_habits if (not h.frequency or (yesterday.weekday() in h.frequency)) and h.id not in yesterday_logs]

        # Productivity score today
        score_data = _compute_productivity_score(user_id, today, now=timezone.now())

        # Sleep last 7 days
        sleep_records = list(DailyData.objects.filter(
            user_id=user_id,
            date__gte=today - timedelta(days=7),
            sleep_hours__isnull=False
        ).values('date', 'sleep_hours').order_by('date'))

        # Task groups
        groups = list(TaskGroup.objects.filter(user_id=user_id).values('id', 'name'))

        context_block = f"""
Today's date: {today.isoformat()} ({today.strftime('%A')})

PENDING TASKS WITH DEADLINE TODAY:
{today_tasks or 'None'}

PENDING TASKS (no deadline):
{no_deadline_tasks or 'None'}

ACTIVE HABITS:
{habit_list}

HABITS PENDING TODAY (not yet logged):
{[h.habit for h in habits_pending_today] or 'All done!'}

HABITS MISSED YESTERDAY:
{[h.habit for h in habits_missed_yesterday] or 'None missed'}

TODAY'S PRODUCTIVITY SCORE: {score_data['total']}/10
  Breakdown:
  - Habits: {score_data['habit']}/5  ({score_data['breakdown']['habits_done']}/{score_data['breakdown']['habits_due']} done)
  - Tasks:  {score_data['todo']}/2   ({score_data['breakdown']['todos_done']}/{score_data['breakdown']['todos_due']} done)
  - Journal: {score_data['journal']}/2  ({'written' if score_data['breakdown']['journaled'] else 'not written'})
  - Sleep:  {score_data['sleep']}/1   ({'logged' if score_data['breakdown']['sleep_logged'] else 'not logged'})

SLEEP LAST 7 DAYS:
{[{'date': str(s['date']), 'hours': float(s['sleep_hours'])} for s in sleep_records] or 'No records'}

TASK GROUPS AVAILABLE:
{groups}
"""

        system_prompt = f"""You are a personal productivity assistant embedded in a productivity app called Steps.
You have access to the user's real-time data shown below. Use it to answer questions naturally and helpfully.

When the user asks to CREATE, LOG, or RECORD something, use the appropriate tool — do not just describe it.
When the user asks a QUESTION about their data, answer directly from the context below without calling tools.
Keep answers concise. Use bullet points for lists. Don't repeat the user's question back.

USER DATA:
{context_block}"""

        # Tool definitions for write operations
        tools = [
            {
                "name": "create_task",
                "description": "Create a new task for the user. Use when user asks to add/create a task.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "task_name": {"type": "string", "description": "The task title"},
                        "group_id": {"type": "integer", "description": "Optional task group ID from the groups list"},
                        "deadline": {"type": "string", "description": "ISO datetime string e.g. 2025-05-02T18:00:00"},
                    },
                    "required": ["task_name"]
                }
            },
            {
                "name": "log_habit",
                "description": "Log a habit as done for a specific date.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "habit_id": {"type": "integer", "description": "ID of the habit from the habits list"},
                        "date": {"type": "string", "description": "Date in YYYY-MM-DD format"},
                    },
                    "required": ["habit_id", "date"]
                }
            },
            {
                "name": "record_sleep",
                "description": "Record sleep hours for a specific date.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "hours": {"type": "number", "description": "Number of hours slept"},
                        "date": {"type": "string", "description": "Date in YYYY-MM-DD format"},
                    },
                    "required": ["hours", "date"]
                }
            },
        ]

        client = anthropic_sdk.Anthropic(api_key=api_key)

        # Build message list: history + new user message
        messages = list(history) + [{"role": "user", "content": message}]

        # First Claude call
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=system_prompt,
            tools=tools,
            messages=messages,
        )

        actions_taken = []

        # Handle tool use
        while response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                tool_name = block.name
                tool_input = block.input
                result_text = ""

                if tool_name == "create_task":
                    data = {'task_name': tool_input['task_name'], 'user_id': user_id}
                    if tool_input.get('group_id'):
                        data['group_id'] = tool_input['group_id']
                    if tool_input.get('deadline'):
                        data['deadline'] = tool_input['deadline']
                    task = Task.objects.create(**data)
                    result_text = f"Task '{task.task_name}' created with ID {task.id}."
                    actions_taken.append({'type': 'task_created', 'task': task.task_name})

                elif tool_name == "log_habit":
                    try:
                        habit = Habit.objects.get(id=tool_input['habit_id'], user_id=user_id)
                        log_date = datetime.strptime(tool_input['date'], '%Y-%m-%d').date()
                        HabitLog.objects.update_or_create(
                            habit=habit, date=log_date,
                            defaults={'is_done': True}
                        )
                        result_text = f"Logged '{habit.habit}' as done on {log_date}."
                        actions_taken.append({'type': 'habit_logged', 'habit': habit.habit, 'date': str(log_date)})
                    except Habit.DoesNotExist:
                        result_text = "Habit not found."

                elif tool_name == "record_sleep":
                    sleep_date = datetime.strptime(tool_input['date'], '%Y-%m-%d').date()
                    DailyData.objects.update_or_create(
                        user_id=user_id, date=sleep_date,
                        defaults={'sleep_hours': tool_input['hours']}
                    )
                    result_text = f"Recorded {tool_input['hours']} hours of sleep on {sleep_date}."
                    actions_taken.append({'type': 'sleep_recorded', 'hours': tool_input['hours'], 'date': str(sleep_date)})

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_text,
                })

            # Feed tool results back and get final response
            messages = messages + [
                {"role": "assistant", "content": response.content},
                {"role": "user", "content": tool_results},
            ]
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                system=system_prompt,
                tools=tools,
                messages=messages,
            )

        # Extract final text
        reply = next((block.text for block in response.content if hasattr(block, 'text')), '')

        return Response({
            'status': 'success',
            'reply': reply,
            'actions': actions_taken,
        })
```

### 4. Register URL

In `board/urls.py`, import `AIAssistantView` and add:

```python
path('api/ai/', AIAssistantView.as_view(), name='ai-assistant'),
```

---

## Frontend

### 1. Modal HTML

Add before `</body>` in `templates/board/dashboard.html`:

```html
<!-- AI Assistant Modal -->
<div class="modal fade" id="aiModal" tabindex="-1">
    <div class="modal-dialog modal-dialog-centered modal-lg">
        <div class="modal-content ai-modal-content">
            <div class="modal-header">
                <h5 class="modal-title">
                    <i class="fas fa-robot me-2"></i>AI Assistant
                </h5>
                <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
            </div>
            <div class="modal-body p-0">
                <div class="ai-chat-messages" id="ai-chat-messages"></div>
            </div>
            <div class="modal-footer ai-chat-footer">
                <div class="ai-input-row w-100">
                    <input type="text" class="form-control" id="ai-chat-input"
                           placeholder="Ask anything about your tasks, habits, sleep…" autocomplete="off">
                    <button class="btn btn-paper btn-primary" id="ai-send-btn" onclick="AIAssistant.send()">
                        <i class="fas fa-paper-plane"></i>
                    </button>
                </div>
            </div>
        </div>
    </div>
</div>
```

### 2. JS: `static/board/js/ai-assistant.js`

Create this file:

```js
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
            history: this.history.slice(0, -1),  // send history without current message (view adds it)
        }).then(res => {
            this._removeThinking();
            if (res.status === 'success') {
                this._appendMessage('assistant', res.reply, res.actions);
                this.history.push({ role: 'assistant', content: res.reply });
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

        // Convert markdown-style bold and bullet points
        const formatted = text
            .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
            .replace(/^- (.+)$/gm, '<li>$1</li>')
            .replace(/(<li>.*<\/li>)/s, '<ul>$1</ul>')
            .replace(/\n/g, '<br>');

        div.innerHTML = `<div class="ai-bubble">${formatted}</div>`;

        if (actions && actions.length > 0) {
            const actionsEl = document.createElement('div');
            actionsEl.className = 'ai-actions-taken';
            actionsEl.innerHTML = actions.map(a => {
                if (a.type === 'task_created') return `<span class="ai-action-chip"><i class="fas fa-check-circle"></i> Task created: ${a.task}</span>`;
                if (a.type === 'habit_logged') return `<span class="ai-action-chip"><i class="fas fa-check-circle"></i> Logged: ${a.habit} on ${a.date}</span>`;
                if (a.type === 'sleep_recorded') return `<span class="ai-action-chip"><i class="fas fa-check-circle"></i> Sleep: ${a.hours}h on ${a.date}</span>`;
                return '';
            }).join('');
            div.appendChild(actionsEl);
        }

        container.appendChild(div);
        container.scrollTop = container.scrollHeight;
    },

    _appendThinking() {
        const container = document.getElementById('ai-chat-messages');
        const div = document.createElement('div');
        div.className = 'ai-message ai-message-assistant ai-thinking';
        div.id = 'ai-thinking-indicator';
        div.innerHTML = '<div class="ai-bubble"><span class="ai-dot"></span><span class="ai-dot"></span><span class="ai-dot"></span></div>';
        container.appendChild(div);
        container.scrollTop = container.scrollHeight;
    },

    _removeThinking() {
        document.getElementById('ai-thinking-indicator')?.remove();
    },
};

// Enter key in chat input
document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('ai-chat-input')?.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') AIAssistant.send();
    });
});
```

### 3. Load the script

In `dashboard.html`, add the script tag alongside the other JS includes:

```html
<script src="{% static 'board/js/ai-assistant.js' %}"></script>
```

### 4. Modify `doSearch()` in `default-pane.js`

```js
doSearch() {
    const query = document.getElementById('search-input').value.trim();
    if (!query) return;

    if (query.toLowerCase().startsWith('/ai ')) {
        const prompt = query.slice(4).trim();
        document.getElementById('search-input').value = '';
        AIAssistant.open(prompt);
        return;
    }

    const engine = this.searchEngines.find(e => e.key === this.currentEngine);
    if (engine) {
        document.getElementById('search-input').value = '';
        const url = engine.url_template.replace('{query}', encodeURIComponent(query));
        window.open(url, '_blank');
    }
},
```

---

## CSS

Add to `static/board/css/dashboard.css`:

```css
/* ── AI Assistant Modal ── */
.ai-modal-content {
    max-height: 80vh;
    display: flex;
    flex-direction: column;
}

.ai-chat-messages {
    flex: 1;
    overflow-y: auto;
    padding: 16px;
    display: flex;
    flex-direction: column;
    gap: 12px;
    min-height: 200px;
    max-height: 50vh;
}

.ai-message {
    display: flex;
    flex-direction: column;
}

.ai-message-user {
    align-items: flex-end;
}

.ai-message-assistant {
    align-items: flex-start;
}

.ai-bubble {
    max-width: 80%;
    padding: 10px 14px;
    border-radius: 14px;
    font-size: 0.875rem;
    line-height: 1.55;
    white-space: pre-wrap;
}

.ai-message-user .ai-bubble {
    background: var(--ink-brown);
    color: var(--paper-bg);
    border-bottom-right-radius: 4px;
}

.ai-message-assistant .ai-bubble {
    background: var(--paper-bg-end);
    border: 1px solid var(--grid-dots);
    color: var(--ink-black);
    border-bottom-left-radius: 4px;
}

.ai-bubble ul {
    margin: 4px 0 0 0;
    padding-left: 18px;
}

.ai-actions-taken {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-top: 6px;
}

.ai-action-chip {
    font-size: 0.75rem;
    background: color-mix(in srgb, var(--ink-brown) 15%, transparent);
    color: var(--ink-brown);
    border-radius: 20px;
    padding: 3px 10px;
    display: flex;
    align-items: center;
    gap: 4px;
}

.ai-chat-footer {
    padding: 12px 16px;
    border-top: 1px solid var(--grid-dots);
}

.ai-input-row {
    display: flex;
    gap: 8px;
}

/* Thinking dots */
.ai-thinking .ai-bubble {
    padding: 12px 16px;
}

.ai-dot {
    display: inline-block;
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--ink-brown-light);
    margin: 0 2px;
    animation: ai-dot-bounce 1.2s infinite ease-in-out;
}

.ai-dot:nth-child(2) { animation-delay: 0.2s; }
.ai-dot:nth-child(3) { animation-delay: 0.4s; }

@keyframes ai-dot-bounce {
    0%, 80%, 100% { transform: translateY(0); opacity: 0.4; }
    40% { transform: translateY(-6px); opacity: 1; }
}
```

---

## Example Interactions

| User types | What happens |
|---|---|
| `/ai what are my tasks today` | Claude reads context, lists pending tasks with today deadline |
| `/ai what habits did I miss yesterday` | Claude reads yesterday's logs, lists unchecked habits |
| `/ai what habits are pending today` | Claude reads today's logs, lists unchecked habits |
| `/ai why is my productivity score 9 today` | Claude explains breakdown: habits 4.5/5, todos 2/2, journal 2/2, sleep 0/1 |
| `/ai create a task review PR by Friday in Work group` | Claude calls `create_task` tool, task saved to DB, confirmation shown |
| `/ai log 3 reps for Morning Run yesterday` | Claude calls `log_habit` tool |
| `/ai record 7 hours sleep last night` | Claude calls `record_sleep` tool |

---

## Notes

- The `ANTHROPIC_API_KEY` env var must be set before running the server.
- Model used: `claude-sonnet-4-6` (latest Sonnet). Can be changed to `claude-haiku-4-5-20251001` for lower latency/cost.
- The tool loop handles chained tool calls (e.g. create task + log habit in one message).
- History is kept in `AIAssistant.history` (in-memory, cleared when modal reopens). Do not persist to localStorage — it contains user data.
- After write actions, the relevant pane data (todos, habits) should be refreshed. In the `actions_taken` response, the frontend can check `res.actions` and call `TodosPane.loadTodos()` / `Habits.init()` as needed in `AIAssistant.send()`.
