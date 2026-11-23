// Notifications, dialogs and the step sidebar.

export function toast(message, kind = 'info', ms) {
    const box = document.getElementById('toasts');
    const el = document.createElement('div');
    el.className = `toast ${kind}`;
    const text = document.createElement('div');
    text.className = 'flex-1';
    text.textContent = message;
    const close = document.createElement('button');
    close.textContent = '×';
    close.className = 'text-gray-400 hover:text-white';
    close.onclick = () => el.remove();
    el.append(text, close);
    box.appendChild(el);
    const life = ms ?? (kind === 'error' ? 10000 : 4000);
    if (life > 0) setTimeout(() => el.remove(), life);
    return el;
}

export function errorToast(error) {
    console.error(error);
    toast(error.message || String(error), 'error');
}

export const jobDialog = {
    show(title) {
        document.getElementById('job-title').textContent = title;
        this.update(0, '');
        const d = document.getElementById('job-dialog');
        d.classList.remove('hidden');
        d.classList.add('flex');
    },
    update(fraction, message) {
        document.getElementById('job-bar').style.width = `${Math.round(fraction * 100)}%`;
        document.getElementById('job-message').textContent = message;
    },
    hide() {
        const d = document.getElementById('job-dialog');
        d.classList.add('hidden');
        d.classList.remove('flex');
    },
};

// Run an async action with a busy button.
export async function busy(button, action) {
    const label = button.textContent;
    button.disabled = true;
    button.textContent = label + '…';
    try { return await action(); } finally {
        button.disabled = false;
        button.textContent = label;
    }
}

export const steps = {
    init() {
        document.querySelectorAll('.step-title').forEach(title => {
            title.addEventListener('click', () => title.parentElement.classList.toggle('collapsed'));
        });
    },
    // done: steps completed; current: the step to open
    set(current, done = []) {
        document.querySelectorAll('.step').forEach(step => {
            const n = Number(step.dataset.step);
            step.classList.toggle('done', done.includes(n));
            step.classList.toggle('current', n === current);
            step.classList.toggle('locked', n > 1 && !document.body.dataset.project);
            if (n === current) step.classList.remove('collapsed');
        });
    },
};

export function showDialog(id, show = true) {
    const d = document.getElementById(id);
    d.classList.toggle('hidden', !show);
    d.classList.toggle('flex', show);
}
