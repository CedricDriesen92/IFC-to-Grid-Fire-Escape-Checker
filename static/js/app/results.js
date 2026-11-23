// The results panel: summary, table of spaces, details of the selected one, compartments.
import { state, emit, routeStatus } from './state.js';
import { api } from './api.js';
import { errorToast, toast } from './ui.js';

const KIND = { outside: 'outside', stairwell: 'stairwell', 'stairwell door': 'stair door', 'evacuation route': 'evac. route' };
let sortKey = 'status', sortDir = -1;

const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

function floorName(i) {
    const f = state.project.meta.floors[i];
    return (f && f.name) || `Floor ${i + 1}`;
}

function rows() {
    const res = state.results;
    const filter = $('results-filter').value;
    const thisFloor = $('results-this-floor').checked;
    const q = $('results-search').value.trim().toLowerCase();
    const order = { day: 0, night: 1, none: 2, ok: 3 };
    const list = res.routes.map(r => ({ r, status: routeStatus(r) })).filter(({ r, status }) => {
        if (thisFloor && r.floor !== state.currentFloor) return false;
        if (q && !r.space_name.toLowerCase().includes(q)) return false;
        if (filter === 'problems') return status !== 'ok';
        if (filter === 'noroute') return r.distance == null;
        if (filter === 'ok') return status === 'ok';
        return true;
    });
    const key = {
        status: x => order[x.status], name: x => x.r.space_name.toLowerCase(), floor: x => x.r.floor,
        use: x => x.r.use || '', distance: x => x.r.distance ?? 1e9, kind: x => x.r.exit_kind || '',
        second: x => x.r.second_exit_distance ?? (x.r.second_exit_beyond ? 1e8 : -1),
    }[sortKey];
    list.sort((a, b) => {
        const ka = key(a), kb = key(b);
        return (ka < kb ? -1 : ka > kb ? 1 : 0) * (sortKey === 'status' ? 1 : sortDir);
    });
    return list;
}

export function renderResults() {
    const res = state.results;
    const panel = $('results');
    if (!res) { panel.classList.add('hidden'); return; }
    panel.classList.remove('hidden');
    $('results-stale').classList.toggle('hidden', !res.stale);

    const counts = { ok: 0, problems: 0, noroute: 0 };
    for (const r of res.routes) {
        if (r.distance == null) counts.noroute++;
        else if (routeStatus(r) === 'ok') counts.ok++;
        else counts.problems++;
    }
    $('results-summary').innerHTML = `
        <div class="card"><b>${res.routes.length}</b>spaces</div>
        <div class="card"><b class="text-green-400">${counts.ok}</b>OK</div>
        <div class="card"><b class="text-red-400">${counts.problems}</b>problems</div>
        <div class="card"><b class="text-gray-300">${counts.noroute}</b>no route</div>`;

    const tbody = $('results-table').querySelector('tbody');
    tbody.innerHTML = rows().map(({ r, status }) => {
        const second = r.second_exit_distance != null ? r.second_exit_distance.toFixed(1) : (r.second_exit_beyond ? `>${r.second_exit_beyond}` : '');
        const useTitle = r.use_source === 'name' ? 'guessed from the name' : r.use_source === 'ifc' ? 'from the IFC' : r.use_source === 'set' ? 'set here' : 'unknown, so both limits apply';
        return `<tr class="row ${r.space_id === state.selected ? 'selected' : ''}" data-id="${esc(r.space_id)}">
            <td><span class="dot ${status}"></span></td>
            <td class="name">${esc(r.space_name)}</td>
            <td>${esc(floorName(r.floor))}</td>
            <td><select data-use="${esc(r.space_id)}" title="${useTitle}">
                <option value="" ${!r.use ? 'selected' : ''}>day/night</option>
                <option value="day" ${r.use === 'day' ? 'selected' : ''}>day</option>
                <option value="night" ${r.use === 'night' ? 'selected' : ''}>night</option></select></td>
            <td class="text-right">${r.distance != null ? r.distance.toFixed(1) : '–'}</td>
            <td>${esc(KIND[r.exit_kind] || '')}</td>
            <td class="text-right">${second}</td></tr>`;
    }).join('');

    renderDetail();
    renderCompartments();
    $('not-checked').innerHTML = res.not_checked.map(t => `<li>${esc(t)}</li>`).join('');
}

export function renderDetail() {
    const box = $('results-detail');
    const r = state.results && state.results.routes.find(x => x.space_id === state.selected);
    if (!r) { box.classList.add('hidden'); return; }
    box.classList.remove('hidden');
    const comp = state.results.compartments.find(c => c.id === r.compartment);
    const v = r.violations;
    const list = (title, items) => items.length ? `<div class="font-semibold mt-1">${title}</div><ul class="list-disc pl-4">${items.map(i => `<li>${esc(i)}</li>`).join('')}</ul>` : '';
    const bottleneck = r.diagnosis && r.diagnosis.cell ? `<button class="btn mt-1" id="goto-bottleneck">Show bottleneck</button>` : '';
    box.innerHTML = `
        <div class="font-semibold text-base">${esc(r.space_name)}</div>
        <div class="text-xs text-gray-400">${esc(floorName(r.floor))} · ${r.area ? r.area.toFixed(1) + ' m²' : ''} · ${esc(comp ? comp.name : '')}, ${comp ? comp.needed : 1} exit${comp && comp.needed > 1 ? 's' : ''} required</div>
        ${r.distance != null ? `<div>To the ${esc(r.exit_kind || 'exit')}: <b>${r.distance.toFixed(1)} m</b>${r.second_exit_distance != null ? `, second exit <b>${r.second_exit_distance.toFixed(1)} m</b>` : ''} · ${r.exits_reachable} exit${r.exits_reachable === 1 ? '' : 's'} reachable</div>` : ''}
        ${list('General', v.general)}${list('Day occupancy', v.daytime)}${list('Night occupancy', v.nighttime)}
        ${!v.general.length && !v.daytime.length && !v.nighttime.length ? '<div class="text-green-400">OK</div>' : ''}
        ${bottleneck}`;
    const b = $('goto-bottleneck');
    if (b) b.onclick = () => emit('goto', { row: r.diagnosis.cell[0], col: r.diagnosis.cell[1], floor: r.diagnosis.cell[2] });
}

function renderCompartments() {
    const tbody = $('compartments-table').querySelector('tbody');
    tbody.innerHTML = `<tr class="text-gray-400"><td>Compartment</td><td class="text-right">Area</td><td>Occupancy</td><td class="text-right">Exits</td></tr>` +
        state.results.compartments.map(c => `<tr>
            <td class="pr-1">${esc(c.name)}</td>
            <td class="text-right pr-1">${c.area ? Math.round(c.area) + ' m²' : ''}</td>
            <td><input type="number" min="0" class="inp w-20" data-occ="${esc(c.id)}" value="${c.occupancy ?? ''}" placeholder="persons"
                 title="${c.occupancy_source ? 'from ' + c.occupancy_source : 'not given, so one exit'}">
                ${c.estimate_s10 ? `<button class="btn" data-est="${esc(c.id)}" data-val="${c.estimate_s10}" title="One person per 10 m² (annex 1, 1.6.2)">S/10</button>` : ''}</td>
            <td class="text-right">${c.needed}</td></tr>`).join('');
}

export function initResults() {
    ['results-filter', 'results-this-floor', 'results-search'].forEach(id => $(id).addEventListener('input', renderResults));
    $('results-close').onclick = () => $('results').classList.add('hidden');
    $('results-table').querySelector('thead').addEventListener('click', e => {
        const key = e.target.closest('th')?.dataset.sort;
        if (!key) return;
        sortDir = key === sortKey ? -sortDir : 1;
        sortKey = key;
        renderResults();
    });
    $('results-table').querySelector('tbody').addEventListener('click', e => {
        if (e.target.tagName === 'SELECT' || e.target.tagName === 'OPTION') return;
        const row = e.target.closest('tr.row');
        if (row) emit('select', row.dataset.id);
    });
    $('results-table').querySelector('tbody').addEventListener('change', async e => {
        const id = e.target.dataset.use;
        if (!id) return;
        const value = e.target.value || null;
        try {
            await api.overrides(state.project.id, { use: { [id]: value } });
            const r = state.results.routes.find(x => x.space_id === id);
            if (r) { r.use = value; r.use_source = value ? 'set' : null; }
            emit('rerun');
        } catch (err) { errorToast(err); }
    });
    const compTable = $('compartments-table');
    compTable.addEventListener('change', async e => {
        const id = e.target.dataset.occ;
        if (!id) return;
        await setOccupancy(id, e.target.value === '' ? null : Number(e.target.value));
    });
    compTable.addEventListener('click', async e => {
        const id = e.target.dataset.est;
        if (!id) return;
        await setOccupancy(id, Number(e.target.dataset.val));
    });
}

async function setOccupancy(id, value) {
    try {
        await api.overrides(state.project.id, { occupancy: { [id]: value } });
        emit('rerun');
    } catch (err) { errorToast(err); }
}
