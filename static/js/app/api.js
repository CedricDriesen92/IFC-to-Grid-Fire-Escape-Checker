// Calls to the server; errors become exceptions with the server's message.

async function request(method, url, body) {
    const options = { method, headers: {} };
    if (body instanceof FormData) {
        options.body = body;
    } else if (body !== undefined) {
        options.headers['Content-Type'] = 'application/json';
        options.body = JSON.stringify(body);
    }
    let response;
    try {
        response = await fetch(url, options);
    } catch (e) {
        throw new Error('No connection to the server. Is app.py running?');
    }
    let data = null;
    const text = await response.text();
    try { data = text ? JSON.parse(text) : null; } catch { data = null; }
    if (!response.ok) {
        throw new Error((data && data.error) || `${response.status} ${response.statusText}`);
    }
    return data;
}

export const api = {
    listProjects: () => request('GET', '/api/projects'),
    createProject: form => request('POST', '/api/projects', form),
    job: id => request('GET', `/api/jobs/${id}`),
    project: id => request('GET', `/api/projects/${id}`),
    edit: (id, body) => request('POST', `/api/projects/${id}/edit`, body),
    undo: (id, redo = false) => request('POST', `/api/projects/${id}/undo`, { redo }),
    settings: (id, changes) => request('POST', `/api/projects/${id}/settings`, changes),
    floors: (id, action, floor) => request('POST', `/api/projects/${id}/floors`, { action, floor }),
    exits: (id, exits) => request('POST', `/api/projects/${id}/exits`, { exits }),
    overrides: (id, body) => request('POST', `/api/projects/${id}/overrides`, body),
    analyse: id => request('POST', `/api/projects/${id}/analyse`),
    analyseJob: id => request('POST', `/api/projects/${id}/analyse?background=1`),
    path: (id, start, goals) => request('POST', `/api/projects/${id}/path`, { start, goals }),
    attachIfc: (id, form) => request('POST', `/api/projects/${id}/ifc`, form),
    exportUrl: (id, kind, query) => `/api/projects/${id}/export/${kind}${query ? `?${new URLSearchParams(query)}` : ''}`,
};

// Poll a background job until it ends; onProgress(fraction, message).
export async function waitForJob(jobId, onProgress, interval = 400) {
    for (let wait = Math.min(interval, 150); ; wait = interval) {
        await new Promise(r => setTimeout(r, wait));
        const job = await api.job(jobId);
        onProgress(job.progress || 0, job.message || '');
        if (job.status === 'done') return job.result;
        if (job.status === 'error') throw new Error(job.error || 'The job failed');
    }
}

// Download a file from a URL, reporting server errors (which come back as JSON).
export async function download(url) {
    const response = await fetch(url);
    if (!response.ok) {
        let message = `${response.status} ${response.statusText}`;
        try { message = (await response.json()).error || message; } catch { /* not JSON */ }
        throw new Error(message);
    }
    const blob = await response.blob();
    const name = (response.headers.get('Content-Disposition') || '').match(/filename="?([^";]+)"?/)?.[1] || 'download';
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
