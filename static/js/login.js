document.addEventListener('DOMContentLoaded', function () {
    const passwordInput = document.getElementById('password');
    const toggleButton = document.getElementById('togglePassword');
    const visibilityIcon = document.getElementById('passwordVisibilityIcon');

    if (!passwordInput || !toggleButton || !visibilityIcon) {
        return;
    }

    toggleButton.addEventListener('click', function () {
        const isPassword = passwordInput.type === 'password';

        passwordInput.type = isPassword ? 'text' : 'password';

        visibilityIcon.textContent = isPassword ? 'visibility_off' : 'visibility';
        toggleButton.setAttribute('aria-pressed', String(isPassword));

        toggleButton.setAttribute(
            'aria-label',
            isPassword ? 'Ocultar contraseña' : 'Mostrar contraseña'
        );
    });
});
