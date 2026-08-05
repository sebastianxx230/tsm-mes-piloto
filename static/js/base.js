window.addEventListener('load', function () {
    document.documentElement.classList.remove('preload');
    document.documentElement.classList.add('app-ready');
});

setTimeout(function () {
    document.documentElement.classList.remove('preload');
    document.documentElement.classList.add('app-ready');
}, 1800);

function toggleUserMenu() {
    const menu = document.getElementById('user-dropdown');
    const button = document.getElementById('user-menu-button');
    const arrow = document.getElementById('user-menu-arrow');

    if (!menu) return;

    const isOpen = !menu.classList.contains('invisible');

    if (isOpen) {
        menu.classList.add('invisible', 'opacity-0', 'translate-y-1', 'scale-95');
        menu.classList.remove('opacity-100', 'translate-y-0', 'scale-100');

        if (button) button.setAttribute('aria-expanded', 'false');
        if (arrow) arrow.classList.remove('rotate-180');
    } else {
        menu.classList.remove('invisible', 'opacity-0', 'translate-y-1', 'scale-95');
        menu.classList.add('opacity-100', 'translate-y-0', 'scale-100');

        if (button) button.setAttribute('aria-expanded', 'true');
        if (arrow) arrow.classList.add('rotate-180');
    }
}

function closeUserMenu() {
    const menu = document.getElementById('user-dropdown');
    const button = document.getElementById('user-menu-button');
    const arrow = document.getElementById('user-menu-arrow');

    if (!menu) return;

    menu.classList.add('invisible', 'opacity-0', 'translate-y-1', 'scale-95');
    menu.classList.remove('opacity-100', 'translate-y-0', 'scale-100');

    if (button) button.setAttribute('aria-expanded', 'false');
    if (arrow) arrow.classList.remove('rotate-180');
}

document.addEventListener('click', function (event) {
    const container = document.getElementById('user-menu-container');

    if (container && !container.contains(event.target)) {
        closeUserMenu();
    }
});

document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') {
        closeUserMenu();
    }
});

document.addEventListener('DOMContentLoaded', function () {
    const toasts = document.querySelectorAll('.toast-message');

    toasts.forEach(function (toast) {
        const closeButton = toast.querySelector('.toast-close');
        let closed = false;

        function closeToast() {
            if (closed) return;
            closed = true;

            toast.classList.remove('toast-enter');
            toast.classList.add('toast-leave');

            setTimeout(function () {
                toast.remove();

                const container = document.getElementById('toast-container');
                if (container && container.children.length === 0) {
                    container.remove();
                }
            }, 250);
        }

        setTimeout(closeToast, 3000);

        if (closeButton) {
            closeButton.addEventListener('click', closeToast);
        }
    });
});