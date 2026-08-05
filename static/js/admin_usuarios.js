(function () {
    const createDialog = document.getElementById('create-user-dialog');
    const editDialog = document.getElementById('edit-user-dialog');
    const editForm = document.getElementById('edit-user-form');
    const editName = document.getElementById('edit-name');
    const editUsername = document.getElementById('edit-username');
    const editRole = document.getElementById('edit-role');
    const editActive = document.getElementById('edit-active');
    const editPassword = document.getElementById('edit-password');
    const editCaption = document.getElementById('edit-user-caption');
    const editLockNote = document.getElementById('edit-lock-note');
    const lockedRole = document.getElementById('edit-role-locked');
    const lockedActive = document.getElementById('edit-active-locked');
    const searchInput = document.getElementById('user-search');
    const emptySearch = document.getElementById('users-empty-search');

    function openDialog(dialog) {
        if (!dialog) return;
        dialog.showModal();
        document.body.classList.add('access-dialog-open');
    }

    function closeDialog(dialog) {
        if (!dialog || !dialog.open) return;
        dialog.close();
    }

    function configureLockedField(field, hiddenField, value, locked) {
        field.value = value;
        field.disabled = locked;

        if (locked) {
            hiddenField.name = field.name;
            hiddenField.value = value;
        } else {
            hiddenField.removeAttribute('name');
            hiddenField.value = '';
        }
    }

    document.querySelectorAll('[data-open-create-user]').forEach(function (button) {
        button.addEventListener('click', function () {
            openDialog(createDialog);
            window.setTimeout(function () {
                const firstField = document.getElementById('new-name');
                if (firstField) firstField.focus();
            }, 50);
        });
    });

    document.querySelectorAll('[data-edit-user]').forEach(function (button) {
        button.addEventListener('click', function () {
            const locked = button.dataset.locked === '1';

            editForm.action = button.dataset.action;
            editName.value = button.dataset.name;
            editUsername.value = button.dataset.username;
            editPassword.value = '';
            editCaption.textContent = '@' + button.dataset.username;
            configureLockedField(editRole, lockedRole, button.dataset.role, locked);
            configureLockedField(editActive, lockedActive, button.dataset.active, locked);
            editLockNote.classList.toggle('hidden', !locked);
            editLockNote.classList.toggle('flex', locked);

            openDialog(editDialog);
            window.setTimeout(function () {
                editName.focus();
            }, 50);
        });
    });

    document.querySelectorAll('[data-close-dialog]').forEach(function (button) {
        button.addEventListener('click', function () {
            closeDialog(button.closest('dialog'));
        });
    });

    document.querySelectorAll('.access-dialog').forEach(function (dialog) {
        dialog.addEventListener('click', function (event) {
            if (event.target === dialog) closeDialog(dialog);
        });

        dialog.addEventListener('close', function () {
            if (!document.querySelector('.access-dialog[open]')) {
                document.body.classList.remove('access-dialog-open');
            }
        });
    });

    if (searchInput) {
        searchInput.addEventListener('input', function () {
            const query = searchInput.value.trim().toLocaleLowerCase('es');
            const rows = Array.from(document.querySelectorAll('[data-user-row]'));
            let visibleRows = 0;

            rows.forEach(function (row) {
                const matches = !query || row.textContent.toLocaleLowerCase('es').includes(query);
                row.classList.toggle('hidden', !matches);
                if (matches) visibleRows += 1;
            });

            emptySearch.classList.toggle('hidden', visibleRows !== 0);
        });
    }
})();
