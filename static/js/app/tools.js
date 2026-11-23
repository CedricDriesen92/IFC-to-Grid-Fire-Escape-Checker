// Mouse interaction on the plan: tools, panning and zooming.
import { state, emit, CODE, NAMES, applyDiff, cellAt, polygonToCells } from './state.js';
import { api } from './api.js';
import { errorToast } from './ui.js';

export function brushCells(row, col) {
    const n = state.brush, half = Math.floor(n / 2), out = [];
    for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) out.push([row - half + i, col - half + j]);
    return out;
}

function lineCells(r0, c0, r1, c1) {
    const out = [];
    const dr = Math.abs(r1 - r0), dc = Math.abs(c1 - c0), sr = r0 < r1 ? 1 : -1, sc = c0 < c1 ? 1 : -1;
    let err = dc - dr, r = r0, c = c0;
    for (;;) {
        out.push(...brushCells(r, c));
        if (r === r1 && c === c1) break;
        const e2 = 2 * err;
        if (e2 > -dr) { err -= dr; c += sc; }
        if (e2 < dc) { err += dc; r += sr; }
    }
    return out;
}

function pointInPolygon(x, y, pts) {
    let inside = false;
    for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
        const [xi, yi] = pts[i], [xj, yj] = pts[j];
        if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) inside = !inside;
    }
    return inside;
}

export function spaceAt(row, col) {
    if (!state.results) return null;
    // polygons are cell outlines: test the cell centre, smallest space first (nested spaces)
    const hits = state.results.spaces.filter(s => s.floor === state.currentFloor && s.polygon && s.polygon.length >= 3
        && pointInPolygon(col, row, polygonToCells(s.polygon)));
    hits.sort((a, b) => (a.area || 0) - (b.area || 0));
    return hits[0] || null;
}

export function attachTools(view, viewportEl) {
    const canvas = view.canvas;
    view.brushCells = (r, c) => (['paint', 'line'].includes(state.tool) ? brushCells(r, c) : []);
    let stroke = null;      // { cells: Map, type }
    let line = null;        // { r, c }
    let pan = null;         // { x, y, panX, panY }
    let spaceDown = false;

    const pos = e => {
        const rect = canvas.getBoundingClientRect();
        return { x: e.clientX - rect.left, y: e.clientY - rect.top };
    };

    window.addEventListener('keydown', e => { if (e.code === 'Space' && !isTyping(e)) { spaceDown = true; e.preventDefault(); } });
    window.addEventListener('keyup', e => { if (e.code === 'Space') spaceDown = false; });

    canvas.addEventListener('contextmenu', e => e.preventDefault());
    canvas.addEventListener('wheel', e => {
        e.preventDefault();
        const p = pos(e);
        view.zoomAt(Math.exp(-e.deltaY * 0.0015), p.x, p.y);
    }, { passive: false });

    canvas.addEventListener('pointerdown', e => {
        if (!state.project) return;
        canvas.setPointerCapture(e.pointerId);
        const p = pos(e);
        const { row, col } = view.toCell(p.x, p.y);
        if (e.button === 2 && removeMarker(row, col)) return;
        if (e.button === 1 || e.button === 2 || (e.button === 0 && spaceDown)) {
            pan = { x: p.x, y: p.y, panX: view.panX, panY: view.panY };
            view.autoFit = false;
            viewportEl.classList.add('panning');
            e.preventDefault();
            return;
        }
        if (e.button !== 0) return;
        switch (state.tool) {
            case 'paint':
                stroke = { cells: new Map(), type: state.cellType, last: { row, col } };
                addToStroke(brushCells(row, col));
                break;
            case 'line':
                line = { row, col };
                view.preview = { cells: lineCells(row, col, row, col), type: state.cellType };
                view.request();
                break;
            case 'fill':
                send({ floor: state.currentFloor, type: state.cellType, fill: [row, col] });
                break;
            case 'exit': toggleExit(row, col); break;
            case 'start': state.start = { row, col, floor: state.currentFloor }; state.path = null; view.request(); break;
            case 'goal': state.goals.push({ row, col, floor: state.currentFloor }); state.path = null; view.request(); break;
            default: {
                const space = spaceAt(row, col);
                emit('select', space ? space.id : null);
            }
        }
    });

    canvas.addEventListener('pointermove', e => {
        const p = pos(e);
        if (pan) {
            view.panX = pan.panX + (p.x - pan.x);
            view.panY = pan.panY + (p.y - pan.y);
            view.request();
            return;
        }
        const { row, col } = view.toCell(p.x, p.y);
        view.hover = { row, col };
        emit('hover', { row, col });
        if (stroke) {
            addToStroke(lineCells(stroke.last.row, stroke.last.col, row, col));
            stroke.last = { row, col };
        } else if (line) {
            view.preview = { cells: lineCells(line.row, line.col, row, col), type: state.cellType };
        }
        view.request();
    });

    const end = e => {
        if (pan) { pan = null; viewportEl.classList.remove('panning'); return; }
        if (stroke) {
            const cells = [...stroke.cells.values()];
            const type = stroke.type;
            stroke = null;
            view.preview = null;
            if (cells.length) send({ floor: state.currentFloor, type, cells });
        } else if (line) {
            const cells = view.preview ? view.preview.cells : [];
            line = null;
            view.preview = null;
            if (cells.length) send({ floor: state.currentFloor, type: state.cellType, cells });
        }
        view.request();
    };
    canvas.addEventListener('pointerup', end);
    canvas.addEventListener('pointercancel', end);
    canvas.addEventListener('pointerleave', () => { view.hover = null; emit('hover', null); view.request(); });

    function addToStroke(cells) {
        const f = state.floors[state.currentFloor];
        for (const [r, c] of cells) {
            if (r < 0 || c < 0 || r >= f.rows || c >= f.cols) continue;
            stroke.cells.set(r * f.cols + c, [r, c]);
        }
        view.preview = { cells: [...stroke.cells.values()], type: stroke.type };
    }

    async function send(body) {
        try {
            const diff = await api.edit(state.project.id, body);
            applyDiff(diff);
            emit('edited', diff);
            view.request();
        } catch (e) { errorToast(e); }
    }

    function removeMarker(row, col) {
        const near = (a) => a && a.floor === state.currentFloor && Math.abs(a.row - row) <= 1 && Math.abs(a.col - col) <= 1;
        if (near(state.start)) { state.start = null; state.path = null; view.request(); return true; }
        const i = state.goals.findIndex(near);
        if (i >= 0) { state.goals.splice(i, 1); state.path = null; view.request(); return true; }
        if (state.tool === 'exit') { toggleExit(row, col, true); return true; }
        return false;
    }

    async function toggleExit(row, col, removeOnly = false) {
        const current = (state.project.exits || state.detectedExits || []).map(e => [...e]);
        const i = current.findIndex(([r, c, f]) => f === state.currentFloor && Math.abs(r - row) <= 2 && Math.abs(c - col) <= 2);
        if (i >= 0) current.splice(i, 1);
        else if (!removeOnly) {
            const code = cellAt(state.currentFloor, row, col);
            if (code === null || code === CODE.wall || code === CODE.empty) {
                errorToast(new Error(`Exits go on walkable cells, not on ${NAMES[code] ?? 'the outside'}`));
                return;
            }
            current.push([row, col, state.currentFloor]);
        } else return;
        try {
            const res = await api.exits(state.project.id, current);
            state.project.exits = res.exits;
            if (state.results) state.results.stale = true;
            emit('exits');
            view.request();
        } catch (e) { errorToast(e); }
    }
}

export function isTyping(e) {
    const t = e.target;
    return t && (t.tagName === 'INPUT' || t.tagName === 'SELECT' || t.tagName === 'TEXTAREA' || t.isContentEditable);
}
