// 3D view of the grids and routes (three.js, loaded on first use).
import { state, COLORS, CODE, ROUTE_COLORS, routeStatus } from './state.js';

let THREE = null, OrbitControls = null;
let renderer, scene, camera, controls, group, container, running = false, builtKey = null;

async function load() {
    if (THREE) return;
    THREE = await import('three');
    ({ OrbitControls } = await import('three/addons/controls/OrbitControls.js'));
}

function init(el) {
    container = el;
    renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(window.devicePixelRatio || 1);
    el.appendChild(renderer.domElement);
    scene = new THREE.Scene();
    scene.background = new THREE.Color(0x151515);
    camera = new THREE.PerspectiveCamera(45, 1, 0.1, 5000);
    controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    scene.add(new THREE.HemisphereLight(0xffffff, 0x444444, 1.1));
    const sun = new THREE.DirectionalLight(0xffffff, 0.9);
    sun.position.set(1, 2, 1.5);
    scene.add(sun);
    new ResizeObserver(resize).observe(el);
    resize();
}

function resize() {
    if (!renderer) return;
    const w = container.clientWidth || 1, h = container.clientHeight || 1;
    renderer.setSize(w, h);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
}

function floorTexture(f) {
    const canvas = document.createElement('canvas');
    canvas.width = f.cols;
    canvas.height = f.rows;
    const image = new ImageData(f.cols, f.rows);
    for (let i = 0, k = 0; i < f.original.length; i++, k += 4) {
        const code = f.original[i];
        const c = COLORS[code];
        image.data[k] = c[0]; image.data[k + 1] = c[1]; image.data[k + 2] = c[2];
        image.data[k + 3] = code === CODE.empty ? 0 : 255;
    }
    canvas.getContext('2d').putImageData(image, 0, 0);
    const texture = new THREE.CanvasTexture(canvas);
    texture.magFilter = THREE.NearestFilter;
    texture.minFilter = THREE.LinearFilter;
    texture.colorSpace = THREE.SRGBColorSpace;
    return texture;
}

// Horizontal runs of wall cells as boxes (far fewer than one box per cell).
function wallRuns(f) {
    const runs = [];
    for (let r = 0; r < f.rows; r++) {
        let start = -1;
        for (let c = 0; c <= f.cols; c++) {
            const wall = c < f.cols && f.original[r * f.cols + c] === CODE.wall;
            if (wall && start < 0) start = c;
            if (!wall && start >= 0) { runs.push([r, start, c - start]); start = -1; }
        }
    }
    return runs;
}

function build() {
    const floors = state.project.meta.floors, gs = state.project.meta.grid_size;
    const key = `${state.project.id}:${state.currentFloor}:${state.floors.map(f => f.version).join(',')}:${state.results ? state.results.seconds + ':' + state.results.routes.length : ''}`;
    if (key === builtKey) return;
    const first = builtKey === null;
    builtKey = key;
    if (group) { scene.remove(group); group.traverse(o => { o.geometry?.dispose(); o.material?.map?.dispose(); o.material?.dispose?.(); }); }
    group = new THREE.Group();
    const base = floors[0].elevation;
    const wallMaterial = new THREE.MeshLambertMaterial({ color: 0x8a8a8a });
    const box = new THREE.BoxGeometry(1, 1, 1);
    const matrix = new THREE.Matrix4();

    state.floors.forEach((f, i) => {
        if (i > state.currentFloor) return;  // cutaway: floors up to the current one
        const y = floors[i].elevation - base;
        const height = Math.min((floors[i].height || 3) - 0.1, 1.2);  // cutaway walls, so floors and routes stay visible
        const plane = new THREE.Mesh(new THREE.PlaneGeometry(f.cols * gs, f.rows * gs),
            new THREE.MeshBasicMaterial({ map: floorTexture(f), transparent: true, side: THREE.DoubleSide, opacity: i === state.currentFloor ? 1 : 0.85 }));
        plane.rotation.x = -Math.PI / 2;
        plane.position.set(f.cols * gs / 2, y, f.rows * gs / 2);
        group.add(plane);

        const runs = wallRuns(f);
        const walls = new THREE.InstancedMesh(box, wallMaterial, runs.length);
        runs.forEach(([r, c, n], k) => {
            matrix.makeScale(n * gs, height, gs);
            matrix.setPosition((c + n / 2) * gs, y + height / 2, (r + 0.5) * gs);
            walls.setMatrixAt(k, matrix);
        });
        group.add(walls);

        if (state.results) {
            for (const route of state.results.routes) {
                if (route.floor !== i || !route.optimal_path) continue;
                const pts = route.optimal_path.map(([x, yy, fl]) => new THREE.Vector3((yy + 0.5) * gs, floors[fl].elevation - base + 0.15, (x + 0.5) * gs));
                const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts),
                    new THREE.LineBasicMaterial({ color: ROUTE_COLORS[routeStatus(route)] }));
                group.add(line);
                if (route.second_path) {
                    const pts2 = route.second_path.map(([x, yy, fl]) => new THREE.Vector3((yy + 0.5) * gs, floors[fl].elevation - base + 0.2, (x + 0.5) * gs));
                    const dashed = new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts2),
                        new THREE.LineDashedMaterial({ color: ROUTE_COLORS.second, dashSize: 0.4, gapSize: 0.25 }));
                    dashed.computeLineDistances();
                    group.add(dashed);
                }
            }
        }
    });
    scene.add(group);
    if (first) frame();
}

function frame() {
    const f = state.floors[0], gs = state.project.meta.grid_size;
    const w = f.cols * gs, d = f.rows * gs;
    const size = Math.max(w, d);
    controls.target.set(w / 2, 0, d / 2);
    camera.position.set(w / 2 + size * 0.55, size * 1.1, d / 2 + size * 1.0);
    controls.update();
}

function loop() {
    if (!running) return;
    controls.update();
    renderer.render(scene, camera);
    requestAnimationFrame(loop);
}

export async function show3d(el) {
    await load();
    if (!renderer) init(el);
    resize();
    build();
    running = true;
    loop();
}

export function hide3d() { running = false; }

export function refresh3d() { if (running) build(); }
