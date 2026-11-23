// The plan: a canvas the size of the viewport, drawn with its own pan and zoom (cells -> screen pixels).
import { state, COLORS, ROUTE_COLORS, CODE, polygonToCells, routeStatus } from './state.js';

const MIN_SCALE = 0.2, MAX_SCALE = 80;

export class PlanView {
    constructor(canvas) {
        this.canvas = canvas;
        this.ctx = canvas.getContext('2d');
        this.scale = 4;         // screen pixels per cell
        this.panX = 0;          // screen position of cell (0, 0)
        this.panY = 0;
        this.base = document.createElement('canvas');
        this.baseKey = null;
        this.preview = null;    // { cells: [[row, col]], type }
        this.hover = null;      // { row, col }
        this.pending = false;
        new ResizeObserver(() => this.resize()).observe(canvas.parentElement);
        this.resize();
    }

    resize() {
        const rect = this.canvas.parentElement.getBoundingClientRect();
        const ratio = window.devicePixelRatio || 1;
        this.canvas.width = Math.max(1, Math.round(rect.width * ratio));
        this.canvas.height = Math.max(1, Math.round(rect.height * ratio));
        this.ratio = ratio;
        if (this.autoFit && rect.width > 50 && rect.height > 50) this.fit();
        this.request();
    }

    floor() { return state.floors[state.currentFloor]; }

    fit() {
        const f = this.floor();
        if (!f) return;
        const w = this.canvas.width / this.ratio, h = this.canvas.height / this.ratio;
        // stay fitted while the layout settles or the window is resized, until the user zooms or pans
        this.autoFit = true;
        if (w < 50 || h < 50) return;
        this.scale = Math.max(MIN_SCALE, Math.min(MAX_SCALE, 0.95 * Math.min(w / f.cols, h / f.rows)));
        this.panX = (w - f.cols * this.scale) / 2;
        this.panY = (h - f.rows * this.scale) / 2;
        this.request();
    }

    zoomAt(factor, x, y) {
        this.autoFit = false;
        const next = Math.max(MIN_SCALE, Math.min(MAX_SCALE, this.scale * factor));
        const k = next / this.scale;
        this.panX = x - (x - this.panX) * k;
        this.panY = y - (y - this.panY) * k;
        this.scale = next;
        this.request();
    }

    zoomCenter(factor) {
        this.zoomAt(factor, this.canvas.width / this.ratio / 2, this.canvas.height / this.ratio / 2);
    }

    centerOn(row, col, minScale = 6) {
        this.autoFit = false;
        if (this.scale < minScale) this.scale = minScale;
        const w = this.canvas.width / this.ratio, h = this.canvas.height / this.ratio;
        this.panX = w / 2 - (col + 0.5) * this.scale;
        this.panY = h / 2 - (row + 0.5) * this.scale;
        this.request();
    }

    // screen (CSS pixels relative to the canvas) -> cell
    toCell(x, y) {
        return { row: Math.floor((y - this.panY) / this.scale), col: Math.floor((x - this.panX) / this.scale) };
    }

    request() {
        if (this.pending) return;
        this.pending = true;
        requestAnimationFrame(() => { this.pending = false; this.draw(); });
    }

    rebuildBase(f) {
        const key = `${state.currentFloor}:${f.version}:${state.showBuffer}:${f.rows}x${f.cols}`;
        if (key === this.baseKey) return;
        this.baseKey = key;
        this.base.width = f.cols;
        this.base.height = f.rows;
        const image = new ImageData(f.cols, f.rows);
        const px = image.data;
        const showBuffer = state.showBuffer;
        for (let i = 0, k = 0; i < f.original.length; i++, k += 4) {
            let code = f.buffered[i];
            if (code === CODE.walla && !showBuffer) code = f.original[i];
            const c = COLORS[code];
            px[k] = c[0]; px[k + 1] = c[1]; px[k + 2] = c[2]; px[k + 3] = 255;
        }
        this.base.getContext('2d').putImageData(image, 0, 0);
    }

    invalidate() { this.baseKey = null; this.request(); }

    draw() {
        const ctx = this.ctx, f = this.floor();
        ctx.setTransform(1, 0, 0, 1, 0, 0);
        ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
        if (!f) return;
        this.rebuildBase(f);
        const s = this.scale, r = this.ratio;
        ctx.setTransform(s * r, 0, 0, s * r, this.panX * r, this.panY * r);   // cell units from here
        ctx.imageSmoothingEnabled = false;
        ctx.drawImage(this.base, 0, 0);

        if (s >= 8) this.drawGridLines(f);
        if (state.results && state.showResults) this.drawResults();
        this.drawExits();
        this.drawMarkers();
        this.drawPreview();
        if (state.results && state.showResults) this.drawLabels();
    }

    visibleRange(f) {
        const w = this.canvas.width / this.ratio, h = this.canvas.height / this.ratio;
        const c0 = Math.max(0, Math.floor(-this.panX / this.scale)), c1 = Math.min(f.cols, Math.ceil((w - this.panX) / this.scale));
        const r0 = Math.max(0, Math.floor(-this.panY / this.scale)), r1 = Math.min(f.rows, Math.ceil((h - this.panY) / this.scale));
        return { r0, r1, c0, c1 };
    }

    drawGridLines(f) {
        const ctx = this.ctx, { r0, r1, c0, c1 } = this.visibleRange(f);
        ctx.beginPath();
        for (let c = c0; c <= c1; c++) { ctx.moveTo(c, r0); ctx.lineTo(c, r1); }
        for (let r = r0; r <= r1; r++) { ctx.moveTo(c0, r); ctx.lineTo(c1, r); }
        ctx.strokeStyle = 'rgba(120,120,120,0.35)';
        ctx.lineWidth = 1 / this.scale;
        ctx.stroke();
    }

    routesOnFloor() {
        const res = state.results;
        return res.routes.filter(r => r.floor === state.currentFloor);
    }

    drawResults() {
        const ctx = this.ctx, res = state.results;
        const routeOf = Object.fromEntries(res.routes.map(r => [r.space_id, r]));
        // spaces, tinted by their status
        for (const space of res.spaces) {
            if (space.floor !== state.currentFloor || !space.polygon || space.polygon.length < 3) continue;
            const status = routeStatus(routeOf[space.id]);
            const pts = polygonToCells(space.polygon);
            ctx.beginPath();
            pts.forEach(([x, y], i) => i ? ctx.lineTo(x + 0.5, y + 0.5) : ctx.moveTo(x + 0.5, y + 0.5));
            ctx.closePath();
            const selected = space.id === state.selected;
            ctx.fillStyle = { ok: 'rgba(34,197,94,0.10)', day: 'rgba(239,68,68,0.16)', night: 'rgba(245,158,11,0.16)', none: 'rgba(107,114,128,0.1)' }[status];
            ctx.fill();
            ctx.lineWidth = (selected ? 3 : 1) / this.scale;
            ctx.strokeStyle = selected ? '#fbbf24' : 'rgba(80,80,80,0.6)';
            ctx.stroke();
        }
        // routes: all thin, the selected one thick with its furthest point and exit
        for (const route of this.routesOnFloor()) {
            if (!route.optimal_path) continue;
            const selected = route.space_id === state.selected;
            if (state.selected && !selected) continue;
            this.polyline(route.optimal_path, ROUTE_COLORS[routeStatus(route)], selected ? 3 : 1.5);
            if (selected || this.scale >= 3) {
                const [x, y] = route.furthest_point;
                this.dot(x, y, selected ? 5 : 3, '#a21caf');
            }
        }
        const sel = state.selected && res.routes.find(r => r.space_id === state.selected);
        if (sel && sel.diagnosis && sel.diagnosis.cell && sel.diagnosis.cell[2] === state.currentFloor) {
            const [x, y] = sel.diagnosis.cell;
            this.ring(x, y, 10, '#fbbf24');
        }
    }

    drawLabels() {
        if (this.scale < 2.5) return;
        const ctx = this.ctx, res = state.results;
        ctx.save();
        ctx.setTransform(this.ratio, 0, 0, this.ratio, 0, 0);
        ctx.font = '11px system-ui, sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        const routeOf = Object.fromEntries(res.routes.map(r => [r.space_id, r]));
        for (const space of res.spaces) {
            if (space.floor !== state.currentFloor || !space.polygon || space.polygon.length < 3) continue;
            const pts = polygonToCells(space.polygon);
            const cx = pts.reduce((a, p) => a + p[0], 0) / pts.length + 0.5;
            const cy = pts.reduce((a, p) => a + p[1], 0) / pts.length + 0.5;
            const route = routeOf[space.id];
            const text = route && route.distance != null ? `${space.name} · ${route.distance.toFixed(1)} m` : space.name;
            const x = this.panX + cx * this.scale, y = this.panY + cy * this.scale;
            ctx.lineWidth = 3;
            ctx.strokeStyle = 'rgba(0,0,0,0.75)';
            ctx.strokeText(text, x, y);
            ctx.fillStyle = '#fff';
            ctx.fillText(text, x, y);
        }
        ctx.restore();
    }

    drawExits() {
        const exits = state.project && state.project.exits ? state.project.exits : state.detectedExits;
        if (!exits) return;
        for (const [row, col, floor] of exits) {
            if (floor !== state.currentFloor) continue;
            this.dot(row, col, 6, '#ef4444');
            this.ring(row, col, 6, '#ffffff');
        }
    }

    drawMarkers() {
        if (state.start && state.start.floor === state.currentFloor) this.dot(state.start.row, state.start.col, 6, '#22c55e');
        for (const g of state.goals) if (g.floor === state.currentFloor) this.dot(g.row, g.col, 6, '#3b82f6');
        if (state.path) this.polyline(state.path, '#facc15', 2.5);
    }

    drawPreview() {
        const ctx = this.ctx;
        if (this.preview && this.preview.cells.length) {
            const c = COLORS[CODE[this.preview.type] ?? 0];
            ctx.fillStyle = `rgba(${c[0]},${c[1]},${c[2]},0.6)`;
            for (const [r, col] of this.preview.cells) ctx.fillRect(col, r, 1, 1);
        }
        if (this.hover && this.brushCells) {
            ctx.strokeStyle = '#fbbf24';
            ctx.lineWidth = 1.5 / this.scale;
            const cells = this.brushCells(this.hover.row, this.hover.col);
            if (cells.length) {
                const rs = cells.map(c => c[0]), cs = cells.map(c => c[1]);
                const r0 = Math.min(...rs), r1 = Math.max(...rs), c0 = Math.min(...cs), c1 = Math.max(...cs);
                ctx.strokeRect(c0, r0, c1 - c0 + 1, r1 - r0 + 1);
            }
        }
    }

    // path points are [row, col, floor]; only the current floor's parts are drawn
    polyline(path, color, width) {
        const ctx = this.ctx;
        ctx.beginPath();
        let drawing = false;
        for (const [x, y, f] of path) {
            if (f !== state.currentFloor) { drawing = false; continue; }
            if (!drawing) { ctx.moveTo(y + 0.5, x + 0.5); drawing = true; } else ctx.lineTo(y + 0.5, x + 0.5);
        }
        ctx.strokeStyle = color;
        ctx.lineWidth = Math.max(width / this.scale, 0.15);
        ctx.lineJoin = 'round';
        ctx.lineCap = 'round';
        ctx.stroke();
    }

    dot(row, col, radiusPx, color) {
        const ctx = this.ctx;
        ctx.beginPath();
        ctx.arc(col + 0.5, row + 0.5, Math.max(radiusPx / this.scale, 0.6), 0, Math.PI * 2);
        ctx.fillStyle = color;
        ctx.fill();
    }

    ring(row, col, radiusPx, color) {
        const ctx = this.ctx;
        ctx.beginPath();
        ctx.arc(col + 0.5, row + 0.5, Math.max(radiusPx / this.scale, 0.8), 0, Math.PI * 2);
        ctx.strokeStyle = color;
        ctx.lineWidth = 2 / this.scale;
        ctx.stroke();
    }
}
