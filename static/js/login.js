document.addEventListener('DOMContentLoaded', function () {
    const passwordInput = document.getElementById('password');
    const toggleButton = document.getElementById('togglePassword');
    const eyeClosed = document.getElementById('eyeClosed');
    const eyeOpen = document.getElementById('eyeOpen');

    toggleButton.addEventListener('click', function () {
        const isPassword = passwordInput.type === 'password';

        passwordInput.type = isPassword ? 'text' : 'password';

        if (isPassword) {
            eyeClosed.classList.add('hidden');
            eyeOpen.classList.remove('hidden');
        } else {
            eyeClosed.classList.remove('hidden');
            eyeOpen.classList.add('hidden');
        }

        toggleButton.setAttribute(
            'aria-label',
            isPassword ? 'Ocultar contraseña' : 'Mostrar contraseña'
        );
    });
});