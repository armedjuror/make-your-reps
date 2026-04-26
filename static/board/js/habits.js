
const Habits = {
    showHabitModal() {
        ['habitName', 'habitDetail', 'habitIdentity', 'habitNotify'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.value = '';
        });
        ['habitDetailStep', 'habitIdentityStep', 'habitNotifyStep', 'habitFrequencyStep'].forEach(id => {
            document.getElementById(id).style.display = 'none';
        });
        document.querySelectorAll('.freq-day-btn').forEach(btn => btn.classList.add('active'));

        const el = document.getElementById('habitModal');
        const nameInput = document.getElementById('habitName');

        nameInput.onkeyup = (e) => {
            if (nameInput.value.trim()) {
                document.getElementById('habitDetailStep').style.display = 'block';
            }else{
                document.getElementById('habitDetailStep').style.display = 'none';
                document.getElementById('habitIdentityStep').style.display = 'none';
                document.getElementById('habitNotifyStep').style.display = 'none';
                document.getElementById('habitFrequencyStep').style.display = 'none';
            }
        };

        document.getElementById('habitDetail').onkeyup = (e) => {
            if (e.target.value.trim()) {
                document.getElementById('habitIdentityStep').style.display = 'block';
            }else{
                document.getElementById('habitIdentityStep').style.display = 'none';
                document.getElementById('habitNotifyStep').style.display = 'none';
                document.getElementById('habitFrequencyStep').style.display = 'none';
            }
        };

        document.getElementById('habitIdentity').onkeyup = (e) => {
            if (e.target.value.trim()) {
                document.getElementById('habitNotifyStep').style.display = 'block';
                document.getElementById('habitFrequencyStep').style.display = 'block';
            }else{
                document.getElementById('habitNotifyStep').style.display = 'none';
                document.getElementById('habitFrequencyStep').style.display = 'none';
            }
        };

        // document.getElementById('habitNotify').onkeyup = (e) => {
        //     if (e.target.value) {
        //         document.getElementById('habitFrequencyStep').style.display = 'block';
        //     }else{
        //         document.getElementById('habitFrequencyStep').style.display = 'none';
        //     }
        // };

        document.querySelectorAll('.freq-day-btn').forEach(btn => {
            btn.onclick = () => btn.classList.toggle('active');
        });

        el.addEventListener('shown.bs.modal', () => requestAnimationFrame(() => nameInput.focus()), {once: true});
        new bootstrap.Modal(el).show();
    },
    saveHabit() {
        const habit = document.getElementById('habitName').value.trim();
        const detail = document.getElementById('habitDetail').value.trim();
        const identity = document.getElementById('habitIdentity').value.trim();
        const notify_at = document.getElementById('habitNotify')?.value || null;
        const frequency = [...document.querySelectorAll('.freq-day-btn.active')].map(b => parseInt(b.dataset.day));
        if (!habit || !detail || !identity) {
            showError('Please complete the habit, when/where, and identity fields');
            return;
        }
        if (frequency.length === 0) {
            showError('Please select at least one day for this habit.');
            return;
        }
        apiClient.post('board/api/habits/', {habit, detail, identity, notify_at, frequency}).then(res => {
            if (res.status === 'success') {
                bootstrap.Modal.getInstance(document.getElementById('habitModal')).hide();
                showSuccess('Habit created!');
                if (panesLoaded.trackers) loadHabits();
            } else {
                showError(res.error);
            }
        });
    },
    init(){
        document.getElementById('habitName').addEventListener('focus', function() {
            document.getElementById('habit_message').innerHTML = "What is your habit?<br>Think small, a two minutes version of what you want to do."
        })

        document.getElementById('habitDetail').addEventListener('focus', function() {
            document.getElementById('habit_message').innerHTML = "Make it clear.<br>When will you be able to do it?<br>Where can you do this?"
        })

        document.getElementById('habitIdentity').addEventListener('focus', function() {
            document.getElementById('habit_message').innerHTML = "What kind of person you want to become after doing this.<br>Goal is not to run a marathon. But to become a runner"
        })

        document.getElementById('habitNotify').addEventListener('focus', function() {
            document.getElementById('habit_message').innerHTML = "When should we notify you about this habit.<br>A small push matters sometimes."
        })
    }
};


        function addHabitModal(){
            const modal = new bootstrap.Modal(document.getElementById('habitModal'));
            document.getElementById('habitModalLabel').textContent = "New Habit";
            modal.show();
        }

        function addHabit(){
            const habit = document.getElementById('habit');
            const whenWhere = document.getElementById('whenWhere');
            const identity = document.getElementById('identity');
            apiClient.post(`board/api/habits/`,
                {'habit': `${habit.value}`, 'detail': `${whenWhere.value}`, 'identity': `${identity.value}`}
            ).then((res) => {
                if (res.status === 'success') {
                    const container = document.getElementById('habitTracker');
                    container.appendChild(createHabitElement(res.data));
                    habit.value = "";
                    whenWhere.value = "";
                    identity.value = "";
                    document.getElementById('habit_message').innerText = '';
                    $('#habitModal').modal('hide');
                }else{
                    showError(res.error);
                }
            });
        }

        function loadHabits(){
            currentHabitData = {};
            apiClient.get(`board/api/habits/`)
            .then((response) => {
                if (response.status === 'success') {
                    const container = document.getElementById('habitTracker');
                    container.innerHTML = '';
                    for (let i = 0; i < response.data.length; i++) {
                        container.appendChild(createHabitElement(response.data[i]));
                    }
                }else {
                    showError(response.error);
                }
            });
        }


        function toggleHabit(habit_id, date){
            apiClient.put(`board/api/habits/${habit_id}/toggle/`,{
                'date': date
            })
            .then((res) => {
                if (res.status === 'success') {
                    const dayButton = document.querySelector('.habit-days .habit-day[data-day="' + date + '"][data-habit="' + habit_id + '"]');
                    if (res.data.is_done){
                        dayButton.classList.add('checked');
                    }else{
                        dayButton.classList.remove('checked');
                    }
                    if (res.message){
                        if (res.data.is_done)showSuccess(res.message)
                        const habitMessage = document.querySelector('.habit-remark[data-habit="' + habit_id + '"]');
                        habitMessage.innerText = res.message;
                    }
                    if (res.gamification) {
                        document.dispatchEvent(new CustomEvent('gamification', {detail: res.gamification}));
                    }
                    General.loadProductivityScore();
                }else{
                    showError(res.error);
                }
            })
        }

function showHabitSettings(habitId, habit, whenWhere, identity, partnerId = null, partnerEmail = null) {
    currentHabitData = {
        id: habitId,
        habit: habit,
        whenWhere: whenWhere,
        identity: identity,
        partnerId: partnerId,
        partnerEmail: partnerEmail
    };

    document.getElementById('currentHabit').textContent = habit;
    document.getElementById('currentHabit').textContent = habit;
    document.getElementById('currentWhenWhere').textContent = whenWhere;
    document.getElementById('currentIdentity').textContent = identity;

    // Update partner display
    updatePartnerDisplay();

    // Reset form state
    document.getElementById('editHabitForm').style.display = 'none';
    document.getElementById('editActions').style.display = 'none';
    document.getElementById('partnerSection').style.display = 'none';
    document.getElementById('partnerActions').style.display = 'none';
    document.getElementById('habit_settings_message').innerHTML = '';

    // Show modal
    const modal = new bootstrap.Modal(document.getElementById('habitSettingsModal'));
    modal.show();
}

// Toggle edit form
function toggleEditForm() {
    const editForm = document.getElementById('editHabitForm');
    const editActions = document.getElementById('editActions');

    if (editForm.style.display === 'none') {
        // Show edit form and populate with current values
        document.getElementById('editHabit').value = currentHabitData.habit;
        document.getElementById('editWhenWhere').value = currentHabitData.whenWhere;
        document.getElementById('editIdentity').value = currentHabitData.identity;

        editForm.style.display = 'block';
        editActions.style.display = 'block';

        // Auto-resize inputs
        resizeInputs();

        document.getElementById('habit_settings_message').innerHTML =
            '<div class="alert alert-info"><i class="fas fa-edit me-2"></i>Edit your habit details below.</div>';
    } else {
        cancelEdit();
    }
}

// Save habit changes
function saveHabitChanges() {
    const habit = document.getElementById('editHabit').value.trim();
    const whenWhere = document.getElementById('editWhenWhere').value.trim();
    const identity = document.getElementById('editIdentity').value.trim();

    if (habit && whenWhere && identity) {
        // Update current data
        currentHabitData.habit = habit;
        currentHabitData.whenWhere = whenWhere;
        currentHabitData.identity = identity;

        // Update display
        document.getElementById('currentHabit').textContent = habit;
        document.getElementById('currentWhenWhere').textContent = whenWhere;
        document.getElementById('currentIdentity').textContent = identity;

        // Hide edit form
        cancelEdit();

        // Show success message
        document.getElementById('habit_settings_message').innerHTML =
            '<div class="alert alert-success"><i class="fas fa-check me-2"></i>Habit updated successfully!</div>';

        // Here you would typically make an API call to save the changes
        apiClient.put('/board/api/habits/' + currentHabitData.id + "/",
            {
                'habit': habit,
                'detail': whenWhere,
                'identity': identity,
            }
        ).then((response) => {
                currentHabitData = {};
            if (response.status === 'success') {
                loadHabits()
            } else {
                showError(response.error);
                currentHabitData = {};
            }
        });

    } else {
        document.getElementById('habit_settings_message').innerHTML =
            '<div class="alert alert-danger"><i class="fas fa-exclamation-triangle me-2"></i>Please fill in all fields.</div>';
    }
}

// Cancel edit
function cancelEdit() {
    document.getElementById('editHabitForm').style.display = 'none';
    document.getElementById('editActions').style.display = 'none';
    document.getElementById('habit_settings_message').innerHTML = '';
}


// Hallmark habit
function hallmarkHabit() {
    bootstrap.Modal.getInstance(document.getElementById('habitSettingsModal')).hide();
    const modal = new bootstrap.Modal(document.getElementById('hallmarkConfirmModal'));
    modal.show();
}

// Confirm hallmark
function confirmHallmark() {
    bootstrap.Modal.getInstance(document.getElementById('hallmarkConfirmModal')).hide();
    apiClient.put(`board/api/habits/${currentHabitData.id}/`,
        {'status': 'completed'}
    ).then((response) => {
        if (response.status === 'success') {
            showSuccess('🎉 Habit hallmarked! Congratulations on forming this habit successfully!');
            loadHabits();
        }else{
            showError(response.error);
            currentHabitData = {};
        }
    });

}

// Delete habit
function deleteHabit() {
    bootstrap.Modal.getInstance(document.getElementById('habitSettingsModal')).hide();
    const modal = new bootstrap.Modal(document.getElementById('deleteConfirmModal'));
    modal.show();
}

// Confirm delete
function confirmDelete() {
    bootstrap.Modal.getInstance(document.getElementById('deleteConfirmModal')).hide();
    apiClient.delete(`/board/api/habits/${currentHabitData.id}/`).then((response) => {
        if (response.status === 'success') {
            showSuccess('Habit deleted successfully.');
            loadHabits();
        } else {
            showError(response.error);
            currentHabitData = {};
        }
    });

}


// Update inline partner display (shows count of active partners)
function updatePartnerDisplay() {
    const partnerDisplay = document.getElementById('partnerDisplay');
    if (!partnerDisplay) return;
    apiClient.get(`board/api/accountability_partners/?habit_id=${currentHabitData.id}`).then(res => {
        if (res.status === 'success') {
            const count = res.data.length;
            partnerDisplay.innerHTML = count > 0
                ? `<span class="partner-badge">${count} partner${count > 1 ? 's' : ''}</span>`
                : '<span style="color: var(--ink-brown)">None assigned</span>';
        }
    });
}

// Toggle partner section — load and show real partner list
function togglePartnerSection() {
    const partnerSection = document.getElementById('partnerSection');
    const partnerActions = document.getElementById('partnerActions');

    if (partnerSection.style.display === 'none') {
        partnerSection.style.display = 'block';
        partnerActions.style.display = 'block';
        loadPartnersList();
    } else {
        partnerSection.style.display = 'none';
        partnerActions.style.display = 'none';
        document.getElementById('habit_settings_message').innerHTML = '';
        document.getElementById('partnerEmail').value = '';
    }
}

function loadPartnersList() {
    const listEl = document.getElementById('partnersList');
    listEl.innerHTML = '<div class="notebook-spinner"></div>';
    apiClient.get(`board/api/accountability_partners/?habit_id=${currentHabitData.id}`).then(res => {
        if (res.status !== 'success') { listEl.innerHTML = ''; return; }
        const partners = res.data;
        if (partners.length === 0) {
            listEl.innerHTML = '<p class="text-brown small">No partners yet.</p>';
            return;
        }
        listEl.innerHTML = partners.map(ap => {
            const statusBadge = ap.status === 'active'
                ? '<span class="badge bg-success ms-2">Active</span>'
                : ap.status === 'request-sent'
                    ? '<span class="badge bg-warning ms-2">Pending</span>'
                    : '<span class="badge bg-secondary ms-2">Inactive</span>';
            return `
                <div class="d-flex align-items-center justify-content-between mb-2 p-2 border rounded">
                    <span><i class="fas fa-user me-2"></i>${ap.partner_name}${statusBadge}</span>
                    <button class="btn btn-paper btn-sm btn-danger" onclick="removePartner(${ap.id})">
                        <i class="fas fa-times"></i>
                    </button>
                </div>`;
        }).join('');
    });
}

// Assign partner — real API call
function assignPartner() {
    const email = document.getElementById('partnerEmail').value.trim();
    const msgEl = document.getElementById('habit_settings_message');

    if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
        msgEl.innerHTML = '<div class="alert alert-danger">Please enter a valid email address.</div>';
        return;
    }

    apiClient.post('board/api/accountability_partners/', {
        habit_id: currentHabitData.id,
        email,
    }).then(res => {
        if (res.status === 'success') {
            document.getElementById('partnerEmail').value = '';
            msgEl.innerHTML = '<div class="alert alert-success"><i class="fas fa-check me-2"></i>Partner added successfully!</div>';
            loadPartnersList();
            updatePartnerDisplay();
        } else {
            msgEl.innerHTML = `<div class="alert alert-danger">${res.error || 'Failed to add partner.'}</div>`;
        }
    });
}

// Remove partner — real API call
function removePartner(apId) {
    apiClient.delete(`board/api/accountability_partners/${apId}/`).then(res => {
        if (res.status === 'success') {
            loadPartnersList();
            updatePartnerDisplay();
            document.getElementById('habit_settings_message').innerHTML =
                '<div class="alert alert-info">Partner removed.</div>';
        } else {
            showError(res.error || 'Failed to remove partner.');
        }
    });
}