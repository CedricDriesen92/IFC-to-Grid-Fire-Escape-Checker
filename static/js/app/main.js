// Escape Route Checker: start-up and wiring of the page.
import { state, on, emit, loadGrids, loadBuffered, applyDiff, NAMES, cellAt, ROUTE_COLORS, COLORS } from './state.js';
import { api, waitForJob, download } from './api.js';
import { toast, errorToast, jobDialog, busy, steps, showDialog } from './ui.js';
import { PlanView } from './view2d.js';
import { attachTools, isTyping, spaceAt } from './tools.js';
import { initResults, renderResults, renderDetail } from './results.js';
import { show3d, hide3d, refresh3d } from './view3d.js';

const $ = id => document.getElementById(id);
const view = new PlanView($('plan'));
attachTools(view, $('viewport'));
initResults();
steps.init();
steps.set(1);

// ------------------------------------------------------------------ projects

async function loadRecent() {
    try {
        const { projects } = await api.listProjects();
        const list = $('recent-projects');
        list.innerHTML = projects.length ? '' : '<li class="text-gray-500">None yet</li>';
        for (const p of projects.slice(0, 12)) {
            const li = document.createElement('li');
            const when = p.updated ? new Date(p.updated * 1000).toLocaleString() : '';
            li.innerHTML = `<button class="w-full text-left hover:bg-dark-300 rounded px-1 py-0.5"><span class="text-gray-200">${p.name.replace(/</g, '&lt;')}</span>
                <span class="text-gray-500"> · ${p.floors} floor${p.floors === 1 ? '' : 's'} · ${when}</span></button>`;
            li.querySelector('button').onclick = () => openProject(p.id);
            list.appendChild(li);
        }
    } catch (e) { errorToast(e); }
}

$('upload-form').addEventListener('submit', async e => {
    e.preventDefault();
    const file = $('file-input').files[0];
    if (!file) { toast('Choose an .ifc or grid .json file first', 'warn'); return; }
    const form = new FormData();
    form.append('file', file);
    form.append('grid_size', $('grid-size').value);
    const mapping = $('mapping-input').files[0];
    if (mapping) form.append('mapping_file', mapping);
    const button = e.submitter || e.target.querySelector('button[type=submit]');
    await busy(button, async () => {
        try {
            const res = await api.createProject(form);
            let id;
            if (res.job_id) {
                jobDialog.show(`Converting ${file.name}`);
                try {
                    id = (await waitForJob(res.job_id, (f, m) => jobDialog.update(f, m))).project_id;
                } finally { jobDialog.hide(); }
            } else id = res.project.id;
            await openProject(id);
            toast(`${file.name} loaded`, 'success');
            loadRecent();
        } catch (err) { errorToast(err); }
    });
});

async function openProject(id) {
    try {
        const p = await api.project(id);
        state.project = p;
        state.results = p.results || null;
        state.selected = null;
        state.start = null; state.goals = []; state.path = null;
        state.currentFloor = 0;
        loadGrids(p.original, p.buffered);
        delete p.original; delete p.buffered;
        document.body.dataset.project = id;
        location.hash = `project=${id}`;
        $('project-name').textContent = p.name;
        $('empty-state').classList.add('hidden');
        $('legend').classList.remove('hidden');
        applySettingsToControls();
        renderFloorTabs();
        updateUndo();
        await refreshExits();
        view.invalidate();
        view.fit();
        renderResults();
        refresh3d();
        steps.set(state.results ? 4 : 2, state.results ? [1, 2, 3] : [1]);
        const w = p.meta.warnings || {};
        if (w.skipped_elements) toast(`No geometry, so missing from the grid: ${Object.entries(w.skipped_elements).map(([k, v]) => `${v} ${k}`).join(', ')}`, 'warn', 12000);
        if (w.spaces_on_no_floor) toast(`IfcSpaces on no floor, not checked: ${w.spaces_on_no_floor.join(', ')}`, 'warn', 8000);
        $('attach-ifc-note').classList.toggle('hidden', !!p.meta.ifc_file);
    } catch (e) { errorToast(e); }
}

async function refreshExits() {
    if (state.project.exits) { state.detectedExits = null; }
    else if (state.results && state.results.exits_detected) { state.detectedExits = state.results.exits.map(e => e.cell); }
    else {
        try { state.detectedExits = (await api.exits(state.project.id, null)).detected; } catch (e) { errorToast(e); }
    }
    const hand = !!state.project.exits;
    const n = (state.project.exits || state.detectedExits || []).length;
    $('exits-mode').textContent = hand ? `${n} exits placed by hand` : `${n} outside doors found`;
    $('exits-reset').classList.toggle('hidden', !hand);
}

$('exits-reset').onclick = async () => {
    try {
        await api.exits(state.project.id, null);
        state.project.exits = null;
        if (state.results) state.results.stale = true;
        await refreshExits();
        renderResults();
        view.request();
    } catch (e) { errorToast(e); }
};
on('exits', async () => { await refreshExits(); renderResults(); rerunSoon(); });

// ------------------------------------------------------------------ floors

function renderFloorTabs() {
    const box = $('floor-tabs');
    box.innerHTML = '';
    state.project.meta.floors.forEach((f, i) => {
        const b = document.createElement('button');
        b.textContent = f.name || `Floor ${i + 1}`;
        b.title = `${f.name || ''} · elevation ${Number(f.elevation).toFixed(2)} m (PageUp / PageDown)`;
        b.className = i === state.currentFloor ? 'active' : '';
        b.onclick = () => setFloor(i);
        box.appendChild(b);
    });
}

function setFloor(i) {
    if (!state.project || i < 0 || i >= state.floors.length) return;
    state.currentFloor = i;
    renderFloorTabs();
    view.invalidate();
    refresh3d();
    if ($('results-this-floor').checked) renderResults();
}

async function floorAction(action) {
    const name = state.project.meta.floors[state.currentFloor].name || `floor ${state.currentFloor + 1}`;
    if (action !== 'add' && !confirm(`${action === 'clear' ? 'Clear' : 'Remove'} ${name}? You cannot undo this.`)) return;
    try {
        const p = await api.floors(state.project.id, action, state.currentFloor);
        state.project.meta = p.meta;
        loadGrids(p.original, p.buffered);
        if (action === 'add') state.currentFloor = state.floors.length - 1;
        if (state.results) state.results.stale = true;
        renderFloorTabs(); updateUndo(); view.invalidate(); renderResults();
    } catch (e) { errorToast(e); }
}
$('floor-add').onclick = () => floorAction('add');
$('floor-clear').onclick = () => floorAction('clear');
$('floor-remove').onclick = () => floorAction('remove');

// ------------------------------------------------------------------ settings

function clearWidthOptions() {
    const gs = state.project.meta.grid_size, sel = $('clear-width');
    sel.innerHTML = '';
    for (let b = 0; b <= 10; b++) {
        const w = 2 * b * gs;
        const o = document.createElement('option');
        o.value = b;
        o.textContent = b === 0 ? 'Not checked' : `${w.toFixed(2)} m${Math.abs(w - 0.8) < 1e-6 ? ' (LG minimum)' : ''}`;
        sel.appendChild(o);
    }
}

function applySettingsToControls() {
    const s = state.project.settings;
    clearWidthOptions();
    $('clear-width').value = s.wall_buffer;
    $('space-source').value = s.space_source;
    $('default-occupancy').value = s.occupancy ?? '';
    $('require-second-exit').checked = !!s.require_second_exit;
    $('stairs-as-exits').checked = s.stairs_as_exits !== false;
    $('allow-diagonal').checked = !!s.allow_diagonal;
    $('minimize-cost').checked = !!s.minimize_cost;
    $('include-empty').checked = !!s.include_empty;
    $('language').value = s.language || 'en';
}

// Changes are saved in order, and the checks wait for them (otherwise a run could use the old settings).
let saving = Promise.resolve();
function whenSaved() { return saving; }
function saveSetting(changes) {
    if (!state.project) return Promise.resolve();
    saving = saving.then(async () => {
        try {
            const res = await api.settings(state.project.id, changes);
            state.project.settings = res.settings;
            if (res.buffered) { loadBuffered(res.buffered); view.invalidate(); }
        } catch (e) { errorToast(e); }
    });
    if (state.results) rerunSoon();
    return saving;
}

// With results on screen, re-run the checks shortly after a change to the settings, uses, occupancy or exits.
let rerunTimer = null;
function rerunSoon() {
    if (!state.results) return;
    state.results.stale = true;
    renderResults();
    clearTimeout(rerunTimer);
    rerunTimer = setTimeout(runChecks, 300);
}
$('clear-width').onchange = e => saveSetting({ wall_buffer: Number(e.target.value) });
$('space-source').onchange = e => saveSetting({ space_source: e.target.value });
let occupancyTimer = null;
$('default-occupancy').oninput = e => {
    clearTimeout(occupancyTimer);
    occupancyTimer = setTimeout(() => saveSetting({ occupancy: e.target.value === '' ? null : Number(e.target.value) }), 400);
};
$('require-second-exit').onchange = e => saveSetting({ require_second_exit: e.target.checked });
$('stairs-as-exits').onchange = e => saveSetting({ stairs_as_exits: e.target.checked });
$('allow-diagonal').onchange = e => saveSetting({ allow_diagonal: e.target.checked });
$('minimize-cost').onchange = e => saveSetting({ minimize_cost: e.target.checked });
$('include-empty').onchange = e => saveSetting({ include_empty: e.target.checked });
$('language').onchange = e => saveSetting({ language: e.target.value });
$('show-buffer').onchange = e => { state.showBuffer = e.target.checked; view.invalidate(); };
$('show-results').onchange = e => { state.showResults = e.target.checked; view.request(); };
$('brush-size').oninput = e => { state.brush = Number(e.target.value); $('brush-size-value').textContent = state.brush; view.request(); };

// ------------------------------------------------------------------ tools

function setTool(tool) {
    state.tool = tool;
    document.querySelectorAll('.tool').forEach(b => b.classList.toggle('active', b.dataset.tool === tool));
    $('viewport').classList.toggle('tool-select', tool === 'select');
    view.request();
}
function setType(type) {
    state.cellType = type;
    document.querySelectorAll('.ctype').forEach(b => b.classList.toggle('active', b.dataset.type === type));
    if (!['paint', 'line', 'fill'].includes(state.tool)) setTool('paint');
}
document.querySelectorAll('.tool').forEach(b => b.onclick = () => setTool(b.dataset.tool));
document.querySelectorAll('.ctype').forEach(b => b.onclick = () => setType(b.dataset.type));
setTool('select');
state.cellType = 'wall';
document.querySelector('.ctype[data-type=wall]').classList.add('active');

function updateUndo() {
    $('btn-undo').disabled = !state.project || !state.project.can_undo;
    $('btn-redo').disabled = !state.project || !state.project.can_redo;
}
async function undo(redo = false) {
    if (!state.project) return;
    try {
        const diff = await api.undo(state.project.id, redo);
        if (diff.floor !== null && diff.floor !== undefined) {
            applyDiff(diff);
            if (diff.floor !== state.currentFloor) setFloor(diff.floor);
        }
        state.project.can_undo = diff.can_undo;
        state.project.can_redo = diff.can_redo;
        updateUndo(); view.request(); renderResults(); refresh3d();
    } catch (e) { errorToast(e); }
}
$('btn-undo').onclick = () => undo(false);
$('btn-redo').onclick = () => undo(true);
on('edited', () => { updateUndo(); renderResults(); refresh3d(); });

// path between two points
$('find-path').onclick = async () => {
    if (!state.start || !state.goals.length) { toast('Set a start and a goal first', 'warn'); return; }
    try {
        const res = await api.path(state.project.id, state.start, state.goals);
        state.path = res.path.length ? res.path : null;
        $('path-info').textContent = res.path.length ? `${res.path_lengths.total_length.toFixed(1)} m over ${new Set(res.path.map(p => p[2])).size} floor(s)` : 'No path found';
        view.request();
    } catch (e) { errorToast(e); }
};
$('clear-path').onclick = () => { state.start = null; state.goals = []; state.path = null; $('path-info').textContent = ''; view.request(); };

// ------------------------------------------------------------------ checks and results

let checking = false, checkAgain = false;
async function runChecks() {
    if (!state.project) return;
    if (checking) { checkAgain = true; return; }   // one run at a time; run once more after this one
    checking = true;
    await busy($('run-checks'), async () => {
        try {
            await whenSaved();
            state.results = await api.analyse(state.project.id);
            if (state.results.exits_detected) state.detectedExits = state.results.exits.map(e => e.cell);
            renderResults(); view.request(); refresh3d();
            steps.set(4, [1, 2, 3]);
            const problems = state.results.routes.filter(r => r.distance == null || Object.values(r.violations).some(v => v.length)).length;
            toast(`${state.results.routes.length} spaces checked, ${problems ? problems + ' with problems' : 'no problems'}`, problems ? 'warn' : 'success', 2500);
        } catch (e) { errorToast(e); }
    });
    checking = false;
    if (checkAgain) { checkAgain = false; runChecks(); }
}
$('run-checks').onclick = runChecks;
$('results-stale').onclick = runChecks;
on('rerun', rerunSoon);

on('select', id => {
    state.selected = id;
    const r = id && state.results && state.results.routes.find(x => x.space_id === id);
    if (r) {
        if (r.floor !== state.currentFloor) setFloor(r.floor);
        const p = r.furthest_point || (r.diagnosis && r.diagnosis.cell);
        if (p && !insideView(p[0], p[1])) view.centerOn(p[0], p[1], view.scale);
        document.querySelector(`#results-table tr[data-id="${CSS.escape(id)}"]`)?.scrollIntoView({ block: 'nearest' });
    }
    renderResults();
    view.request();
});
on('goto', ({ row, col, floor }) => { if (floor !== state.currentFloor) setFloor(floor); view.centerOn(row, col, 10); });

function insideView(row, col) {
    const x = view.panX + (col + 0.5) * view.scale, y = view.panY + (row + 0.5) * view.scale;
    const w = view.canvas.width / view.ratio, h = view.canvas.height / view.ratio;
    return x > 40 && y > 40 && x < w - 40 && y < h - 40;
}

on('hover', cell => {
    const box = $('hover-info');
    if (!cell || !state.project) { box.classList.add('hidden'); return; }
    const code = cellAt(state.currentFloor, cell.row, cell.col);
    if (code === null) { box.classList.add('hidden'); return; }
    const buffered = cellAt(state.currentFloor, cell.row, cell.col, true);
    const space = spaceAt(cell.row, cell.col);
    const gs = state.project.meta.grid_size;
    box.textContent = `${NAMES[code]}${buffered === 5 && code !== 2 ? ' (too narrow)' : ''} · row ${cell.row}, col ${cell.col} · ${(cell.col * gs).toFixed(1)} m, ${(cell.row * gs).toFixed(1)} m${space ? ' · ' + space.name : ''}`;
    box.classList.remove('hidden');
});

// ------------------------------------------------------------------ export

async function exportKind(kind, button) {
    if (!state.project) return;
    await busy(button, async () => {
        try { await download(api.exportUrl(state.project.id, kind, kind === 'pdf' ? $('language').value : null)); }
        catch (e) { errorToast(e); }
    });
}
$('export-pdf').onclick = e => exportKind('pdf', e.target);
$('export-ifc').onclick = e => {
    if (state.project && !state.project.meta.ifc_file) { $('attach-ifc').click(); return; }
    exportKind('ifc', e.target);
};
$('attach-ifc').onchange = async e => {
    const file = e.target.files[0];
    if (!file) return;
    const form = new FormData();
    form.append('file', file);
    try {
        await api.attachIfc(state.project.id, form);
        state.project.meta.ifc_file = true;
        $('attach-ifc-note').classList.add('hidden');
        toast(`${file.name} attached`, 'success');
        exportKind('ifc', $('export-ifc'));
    } catch (err) { errorToast(err); }
    e.target.value = '';
};
$('export-grid').onclick = e => exportKind('grid', e.target);

// ------------------------------------------------------------------ view

$('btn-fit').onclick = () => view.fit();
$('btn-zoom-in').onclick = () => view.zoomCenter(1.4);
$('btn-zoom-out').onclick = () => view.zoomCenter(1 / 1.4);

async function toggleView() {
    if (!state.project) return;
    if (state.mode === '2d') {
        state.mode = '3d';
        $('view3d').classList.remove('hidden');
        $('plan').classList.add('hidden');
        $('btn-view').textContent = '2D';
        try { await show3d($('view3d')); } catch (e) { errorToast(new Error('The 3D view needs internet the first time: ' + e.message)); }
    } else {
        state.mode = '2d';
        hide3d();
        $('view3d').classList.add('hidden');
        $('plan').classList.remove('hidden');
        $('btn-view').textContent = '3D';
        view.request();
    }
}
$('btn-view').onclick = toggleView;

function legend() {
    const chip = (rgb) => `<span class="legend-chip" style="background:rgb(${rgb.join(',')})"></span>`;
    const line = (color) => `<span class="legend-chip" style="background:${color};height:3px;border:0;vertical-align:3px"></span>`;
    $('legend').innerHTML = `
        <div>${chip(COLORS[2])}wall ${chip(COLORS[3])}door ${chip(COLORS[4])}stair ${chip(COLORS[1])}floor ${chip(COLORS[5])}too narrow</div>
        <div>${line(ROUTE_COLORS.ok)}OK ${line(ROUTE_COLORS.day)}problem ${line(ROUTE_COLORS.night)}night only
            <span class="legend-chip" style="background:#a21caf;border-radius:99px"></span>furthest point
            <span class="legend-chip" style="background:#ef4444;border-radius:99px;border-color:#fff"></span>exit</div>`;
}
legend();

// ------------------------------------------------------------------ keyboard

const SHORTCUTS = [
    ['V', 'Select', () => setTool('select')],
    ['B', 'Brush', () => setTool('paint')],
    ['L', 'Line', () => setTool('line')],
    ['F', 'Fill', () => setTool('fill')],
    ['E', 'Exits', () => setTool('exit')],
    ['S / G', 'Path start / goal', null],
    ['1 to 5', 'Wall, door, stair, floor, empty', null],
    ['[ ]', 'Brush size', null],
    ['PageUp / PageDown', 'Next / previous floor', null],
    ['0', 'Zoom to fit', () => view.fit()],
    ['+ / −', 'Zoom in / out', null],
    ['Ctrl+Z / Ctrl+Y', 'Undo / redo', null],
    ['R', 'Run the checks', () => runChecks()],
    ['T', '2D / 3D', () => toggleView()],
    ['Esc', 'Deselect', null],
    ['Wheel', 'Zoom', null],
    ['Middle or right drag, Space + drag', 'Pan', null],
    ['Right click', 'Remove a start, goal or exit', null],
    ['?', 'Shortcuts', null],
];
$('help-table').innerHTML = SHORTCUTS.map(([k, d]) => `<tr><td class="py-0.5 pr-3"><kbd>${k}</kbd></td><td>${d}</td></tr>`).join('');
$('btn-help').onclick = () => showDialog('help-dialog');
document.querySelectorAll('[data-close]').forEach(b => b.onclick = () => showDialog(b.closest('.fixed').id, false));

window.addEventListener('keydown', e => {
    if (isTyping(e)) return;
    const k = e.key;
    if ((e.ctrlKey || e.metaKey) && (k === 'z' || k === 'Z')) { e.preventDefault(); undo(e.shiftKey); return; }
    if ((e.ctrlKey || e.metaKey) && (k === 'y' || k === 'Y')) { e.preventDefault(); undo(true); return; }
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    const types = { 1: 'wall', 2: 'door', 3: 'stair', 4: 'floor', 5: 'empty' };
    if (types[k]) { setType(types[k]); return; }
    switch (k) {
        case 'v': case 'V': setTool('select'); break;
        case 'b': case 'B': setTool('paint'); break;
        case 'l': case 'L': setTool('line'); break;
        case 'f': case 'F': setTool('fill'); break;
        case 'e': case 'E': setTool('exit'); break;
        case 's': case 'S': setTool('start'); break;
        case 'g': case 'G': setTool('goal'); break;
        case '[': $('brush-size').value = Math.max(1, state.brush - 1); $('brush-size').dispatchEvent(new Event('input')); break;
        case ']': $('brush-size').value = Math.min(15, state.brush + 1); $('brush-size').dispatchEvent(new Event('input')); break;
        case 'PageUp': e.preventDefault(); setFloor(state.currentFloor + 1); break;
        case 'PageDown': e.preventDefault(); setFloor(state.currentFloor - 1); break;
        case '0': view.fit(); break;
        case '+': case '=': view.zoomCenter(1.4); break;
        case '-': view.zoomCenter(1 / 1.4); break;
        case 'r': case 'R': runChecks(); break;
        case 't': case 'T': toggleView(); break;
        case '?': showDialog('help-dialog'); break;
        case 'Escape':
            showDialog('help-dialog', false);
            if (state.selected) emit('select', null); else setTool('select');
            break;
        default: return;
    }
});

// ------------------------------------------------------------------ start

loadRecent();
function openFromHash() {
    const match = location.hash.match(/project=([\w-]+)/);
    if (match && (!state.project || state.project.id !== match[1])) openProject(match[1]);
}
openFromHash();
window.addEventListener('hashchange', openFromHash);
window.addEventListener('beforeunload', () => { /* edits are saved on the server as they happen */ });
renderDetail();
