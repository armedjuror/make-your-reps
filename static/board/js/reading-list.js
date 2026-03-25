/**
 * reading-list.js — Reading list (bookmarks) CRUD
 */

const ReadingList = {
    items: [],

    async loadFeatured() {
        const res = await apiClient.get('board/api/reading_list/?featured=1');
        if (res.status === 'success') {
            this.items = res.data;
            this.renderFeatured();
        }
    },

    renderFeatured() {
        const grid = document.getElementById('reading-list-grid');
        if (!grid) return;

        const itemsHtml = this.items.map(item => {
            const iconHtml = item.icon
                ? `<img src="${item.icon}" alt="" class="rl-icon" onerror="this.style.display='none'; this.nextElementSibling.style.display='flex'"><div class="rl-icon-fallback" style="display:none">${this.generateFallbackIcon(item.name, item.url)}</div>`
                : `<div class="rl-icon-fallback">${this.generateFallbackIcon(item.name, item.url)}</div>`;

            return `
                <div class="reading-list-item" title="${item.name}">
                    <a href="${item.url}" target="_blank" class="rl-link">${iconHtml}</a>
                    <button class="rl-edit-btn" onclick="ReadingList.showEditModal(${item.id})" title="Edit/Delete"><i class="fas fa-pen"></i></button>
                </div>
            `;
        }).join('');

        const addBtn = `<button class="reading-list-add-btn" onclick="ReadingList.showAddModal()" title="Add bookmark"><i class="fas fa-plus"></i></button>`;

        grid.innerHTML = itemsHtml + addBtn;
    },

    showEditModal(id) {
        const item = this.items.find(i => i.id === id);
        if (item) this.showAddModal(item);
    },

    generateFallbackIcon(name, url) {
        // Deterministic color from name+url hash
        const str = name + url;
        let hash = 0;
        for (let i = 0; i < str.length; i++) {
            hash = str.charCodeAt(i) + ((hash << 5) - hash);
        }

        const colors = [
            '#e74c3c', '#3498db', '#2ecc71', '#f39c12',
            '#9b59b6', '#1abc9c', '#e67e22', '#34495e',
            '#16a085', '#c0392b', '#2980b9', '#8e44ad'
        ];
        const color = colors[Math.abs(hash) % colors.length];
        const letter = name.charAt(0).toUpperCase();

        return `<div class="rl-letter" style="background:${color}">${letter}</div>`;
    },

    showAddModal(editItem = null) {
        document.getElementById('rlName').value = editItem ? editItem.name : '';
        document.getElementById('rlUrl').value = editItem ? editItem.url : '';
        document.getElementById('rlIcon').value = editItem ? (editItem.icon || '') : '';
        document.getElementById('rlFeatured').checked = editItem ? editItem.is_featured : true;
        document.getElementById('rlEditId').value = editItem ? editItem.id : '';
        document.getElementById('readingListModalTitle').textContent = editItem ? 'Edit Bookmark' : 'Add to Reading List';

        const deleteBtn = document.getElementById('rlDeleteBtn');
        if (deleteBtn) {
            if (editItem) {
                deleteBtn.style.display = 'inline-block';
                deleteBtn.setAttribute('data-id', editItem.id);
            } else {
                deleteBtn.style.display = 'none';
            }
        }

        new bootstrap.Modal(document.getElementById('readingListModal')).show();
    },

    async deleteSelected() {
        const id = document.getElementById('rlDeleteBtn').getAttribute('data-id');
        if (!id) return;
        bootstrap.Modal.getInstance(document.getElementById('readingListModal')).hide();
        await this.remove(id);
    },

    async save() {
        const name = document.getElementById('rlName').value.trim();
        const url = document.getElementById('rlUrl').value.trim();
        const icon = document.getElementById('rlIcon').value.trim() || null;
        const is_featured = document.getElementById('rlFeatured').checked;
        const editId = document.getElementById('rlEditId').value;

        if (!name || !url) {
            showError('Name and URL are required');
            return;
        }

        let res;
        if (editId) {
            res = await apiClient.put(`board/api/reading_list/${editId}/`, { name, url, icon, is_featured });
        } else {
            res = await apiClient.post('board/api/reading_list/', { name, url, icon, is_featured });
        }

        if (res.status === 'success') {
            bootstrap.Modal.getInstance(document.getElementById('readingListModal')).hide();
            this.loadFeatured();
        } else {
            showError(res.error);
        }
    },

    async remove(id) {
        const res = await apiClient.delete(`board/api/reading_list/${id}/`);
        if (res.status === 'success') {
            this.loadFeatured();
        } else {
            showError(res.error);
        }
    }
};