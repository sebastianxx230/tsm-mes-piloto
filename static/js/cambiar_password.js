document.addEventListener('DOMContentLoaded', function() {

    // Lógica para mostrar/ocultar contraseña
    const toggleButtons = document.querySelectorAll('.toggle-password');

    toggleButtons.forEach(btn => {
        btn.addEventListener('click', function() {
            const input = this.previousElementSibling;
            const icon = this.querySelector('.material-symbols-rounded');

            if (input.type === 'password') {
                input.type = 'text';
                icon.textContent = 'visibility_off';
            } else {
                input.type = 'password';
                icon.textContent = 'visibility';
            }
        });
    });

    // Elementos de validación
    const passNueva = document.getElementById('password_nueva');
    const passConf = document.getElementById('password_confirmacion');

    const reqLength = document.getElementById('req-length');
    const reqLetter = document.getElementById('req-letter');
    const reqNumber = document.getElementById('req-number');
    const matchMsg = document.getElementById('match-message');

    const strengthBar = document.getElementById('strength-bar');
    const strengthText = document.getElementById('strength-text');

    function updateCheckItem(element, isValid) {
        const icon = element.querySelector('.material-symbols-rounded');

        if (isValid) {
            element.classList.remove('text-slate-400');
            element.classList.add('text-emerald-600');
            icon.textContent = 'check_circle';
        } else {
            element.classList.add('text-slate-400');
            element.classList.remove('text-emerald-600');
            icon.textContent = 'radio_button_unchecked';
        }
    }

    function updateStrengthBar(len, letValid, numValid, totalLen) {
        if (totalLen === 0) {
            strengthBar.style.width = '0%';
            strengthText.textContent = '';
            return;
        }

        let score = 0;
        if (len) score++;
        if (letValid) score++;
        if (numValid) score++;

        strengthBar.className = 'h-full transition-all duration-300';

        if (score === 1) {
            strengthBar.style.width = '33%';
            strengthBar.classList.add('bg-red-400');
            strengthText.textContent = 'DÉBIL';
            strengthText.className = 'w-12 text-right text-[9px] font-bold uppercase tracking-widest text-red-500';
        } else if (score === 2) {
            strengthBar.style.width = '66%';
            strengthBar.classList.add('bg-amber-400');
            strengthText.textContent = 'MEDIA';
            strengthText.className = 'w-12 text-right text-[9px] font-bold uppercase tracking-widest text-amber-500';
        } else if (score === 3) {
            strengthBar.style.width = '100%';
            strengthBar.classList.add('bg-emerald-500');
            strengthText.textContent = 'FUERTE';
            strengthText.className = 'w-12 text-right text-[9px] font-bold uppercase tracking-widest text-emerald-600';
        }
    }

    // Eventos de escritura
    passNueva.addEventListener('input', function() {
        const val = this.value;

        const isLengthValid = val.length >= 8;
        const isLetterValid = /[a-zA-Z]/.test(val);
        const isNumberValid = /[0-9]/.test(val);

        updateCheckItem(reqLength, isLengthValid);
        updateCheckItem(reqLetter, isLetterValid);
        updateCheckItem(reqNumber, isNumberValid);

        updateStrengthBar(isLengthValid, isLetterValid, isNumberValid, val.length);
        checkMatch();
    });

    passConf.addEventListener('input', checkMatch);

    function checkMatch() {
        const val1 = passNueva.value;
        const val2 = passConf.value;

        if (val2.length === 0) {
            matchMsg.classList.add('hidden');
            matchMsg.classList.remove('flex');
            return;
        }

        matchMsg.classList.remove('hidden');
        matchMsg.classList.add('flex');

        const icon = matchMsg.querySelector('.icon');
        const text = matchMsg.querySelector('.text');

        if (val1 === val2) {
            matchMsg.classList.remove('text-red-500');
            matchMsg.classList.add('text-emerald-600');
            icon.textContent = 'check';
            text.textContent = 'LAS CONTRASEÑAS COINCIDEN';
        } else {
            matchMsg.classList.add('text-red-500');
            matchMsg.classList.remove('text-emerald-600');
            icon.textContent = 'close';
            text.textContent = 'LAS CONTRASEÑAS NO COINCIDEN';
        }
    }
});