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

    async loadAll() {
        const el = document.getElementById('rl-all-list');
        if (!el) return;
        el.innerHTML = '<div class="notebook-spinner"></div>';
        const res = await apiClient.get('board/api/reading_list/');
        if (res.status !== 'success') { el.innerHTML = '<p class="text-brown small">Could not load reading list.</p>'; return; }
        this.renderAll(res.data, el);
    },

    renderAll(items, el) {
        this.items = items;
        if (items.length === 0) {
            el.innerHTML = '<p class="text-brown small">No bookmarks yet. Add one from the home page.</p>';
            return;
        }
        el.innerHTML = items.map(item => {
            const iconHtml = item.icon
                ? `<img src="${item.icon}" alt="" class="rl-icon rl-icon-sm" onerror="this.style.display='none'; this.nextElementSibling.style.display='flex'"><div class="rl-icon-fallback rl-icon-sm" style="display:none">${this.generateFallbackIcon(item.name, item.url)}</div>`
                : `<div class="rl-icon-fallback rl-icon-sm">${this.generateFallbackIcon(item.name, item.url)}</div>`;
            const featuredBadge = item.is_featured ? '<span class="rl-featured-badge"><i class="fas fa-star"></i></span>' : '';
            return `
                <div class="rl-all-item">
                    ${iconHtml}
                    <div class="rl-all-info">
                        <a href="${item.url}" target="_blank" class="rl-all-name">${item.name}${featuredBadge}</a>
                        <div class="rl-all-url">${item.url}</div>
                    </div>
                    <button class="rl-edit-btn ms-auto" onclick="ReadingList.showEditModal(${item.id})" title="Edit"><i class="fas fa-pen"></i></button>
                </div>`;
        }).join('');
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
            if (document.getElementById('rl-all-list')) this.loadAll();
        } else {
            showError(res.error);
        }
    },

    async remove(id) {
        const res = await apiClient.delete(`board/api/reading_list/${id}/`);
        if (res.status === 'success') {
            this.loadFeatured();
            if (document.getElementById('rl-all-list')) this.loadAll();
        } else {
            showError(res.error);
        }
    }
};