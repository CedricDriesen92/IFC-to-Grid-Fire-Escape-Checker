// Shared state of the app and a tiny event bus.

export const NAMES = ['empty', 'floor', 'wall', 'door', 'stair', 'walla'];
export const CODE = { empty: 0, floor: 1, wall: 2, door: 3, stair: 4, walla: 5 };
const CHAR_CODE = { e: 0, f: 1, w: 2, d: 3, s: 4, a: 5 };
export const COLORS = [
    [255, 255, 255],  // empty
    [229, 209, 229],  // floor
    [14, 14, 14],     // wall
    [155, 107, 95],   // door
    [225, 193, 105],  // stair
    [146, 160, 160],  // walla: too narrow to pass
];
export const ROUTE_COLORS = { ok: '#16a34a', day: '#dc2626', night: '#f59e0b', none: '#6b7280', second: '#38bdf8' };

export const state = {
    project: null,          // id, name, meta, settings, overrides, exits, can_undo, can_redo
    floors: [],             // { rows, cols, original: Uint8Array, buffered: Uint8Array, version }
    currentFloor: 0,
    tool: 'select',
    cellType: 'wall',
    brush: 1,
    showBuffer: false,
    showResults: true,
    results: null,          // last analysis
    selected: null,         // selected space id
    start: null,            // { row, col, floor } for "path between two points"
    goals: [],
    path: null,
    detectedExits: null,    // [[row, col, floor]] when exits are detected
    exitsNote: null,        // what to check about them ({marked_interior, open_envelope})
    mode: '2d',
};

const listeners = {};
export function on(event, fn) { (listeners[event] ||= []).push(fn); }
export function emit(event, data) { (listeners[event] || []).forEach(fn => fn(data)); }

// Packed rows (one character per cell) to a Uint8Array of codes.
export function unpackFloor(rows) {
    const height = rows.length, width = rows[0].length;
    const data = new Uint8Array(height * width);
    for (let r = 0; r < height; r++) {
        const row = rows[r], offset = r * width;
        for (let c = 0; c < width; c++) data[offset + c] = CHAR_CODE[row[c]] ?? 0;
    }
    return { rows: height, cols: width, data };
}

export function loadGrids(original, buffered) {
    state.floors = original.map((rows, i) => {
        const o = unpackFloor(rows);
        const b = unpackFloor(buffered[i]);
        return { rows: o.rows, cols: o.cols, original: o.data, buffered: b.data, version: 0 };
    });
    if (state.currentFloor >= state.floors.length) state.currentFloor = 0;
}

export function loadBuffered(buffered) {
    buffered.forEach((rows, i) => {
        state.floors[i].buffered = unpackFloor(rows).data;
        state.floors[i].version++;
    });
}

// A server diff: { floor, original: [[r, c, code]], buffered: [[r, c, code]] }
export function applyDiff(diff) {
    if (diff.floor === null || diff.floor === undefined) return;
    const f = state.floors[diff.floor];
    for (const [r, c, code] of diff.original) f.original[r * f.cols + c] = code;
    for (const [r, c, code] of diff.buffered) f.buffered[r * f.cols + c] = code;
    f.version++;
    if (state.project) {
        state.project.can_undo = diff.can_undo;
        state.project.can_redo = diff.can_redo;
    }
    if (state.results) state.results.stale = true;
}

export function cellAt(floor, row, col, buffered = false) {
    const f = state.floors[floor];
    if (!f || row < 0 || col < 0 || row >= f.rows || col >= f.cols) return null;
    return (buffered ? f.buffered : f.original)[row * f.cols + col];
}

export function gridSize() { return state.project ? state.project.meta.grid_size : 0.1; }

// Space polygons come in world coordinates; to cell coordinates (col, row).
export function polygonToCells(polygon) {
    const m = state.project.meta, gs = m.grid_size;
    return polygon.map(([px, py]) => [(px - m.bbox.min_x) / gs, (py - m.bbox.min_y) / gs]);
}

export function routeStatus(route) {
    if (!route) return 'none';
    const v = route.violations;
    if (route.distance === null || route.distance === undefined) return 'day';
    if (v.general.length || v.daytime.length) return 'day';
    if (v.nighttime.length) return 'night';
    return 'ok';
}
