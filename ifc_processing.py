import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element
import ifcopenshell.util.placement
import ifcopenshell.util.representation
import ifcopenshell.util.shape_builder
import ifcopenshell.util.unit
import ifcopenshell.api
import ifcopenshell.file
import math
import multiprocessing
import numpy as np
from collections import Counter
from typing import Dict, List, Tuple, Any, Optional
import traceback
import logging
import os, sys

from contextlib import contextmanager

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Classes are matched with is_a(), so subtypes count too (IfcWallStandardCase, IfcDoorStandardCase,
# IfcSlabElementedCase, ...).
WALL_TYPES = ['IfcWall', 'IfcColumn', 'IfcCurtainWall', 'IfcWindow', 'IfcCovering']
FLOOR_TYPES = ['IfcSlab']
DOOR_TYPES = ['IfcDoor']
STAIR_TYPES = ['IfcStair', 'IfcStairFlight']
ALL_TYPES = WALL_TYPES + FLOOR_TYPES + DOOR_TYPES + STAIR_TYPES
# Floor finishes and ceilings lie flat on or above a floor: read as walls they would block whole rooms.
IGNORED_COVERING_TYPES = {'FLOORING', 'CEILING'}
TYPE_PRECEDENCE = {'door': 0, 'stair': 1, 'wall': 2, 'floor': 3}


def get_element_type(element: ifcopenshell.entity_instance) -> Optional[str]:
    if element.is_a('IfcDoor'):
        return 'door'
    if any(element.is_a(t) for t in STAIR_TYPES):
        return 'stair'
    if element.is_a('IfcCovering') and getattr(element, 'PredefinedType', None) in IGNORED_COVERING_TYPES:
        return None
    if any(element.is_a(t) for t in WALL_TYPES):
        return 'wall'
    if any(element.is_a(t) for t in FLOOR_TYPES):
        return 'floor'
    return None


def cells_overlapping_triangle(tri: np.ndarray, shape: Tuple[int, int], eps: float = 1e-3) -> Tuple[np.ndarray, np.ndarray]:
    """Grid cells whose square overlaps a triangle given in cell units (3 x 2), by the separating axis test.

    A degenerate triangle (a vertical face seen in plan) is a segment and gives the cells along that segment, not
    its bounding box. Cells that only touch the triangle's edge or corner (within eps) are left out."""
    lo = np.maximum(np.floor(tri.min(axis=0)).astype(int), 0)
    hi = np.minimum(np.floor(tri.max(axis=0)).astype(int), [shape[0] - 1, shape[1] - 1])
    if (hi < lo).any():
        return np.empty(0, int), np.empty(0, int)
    if (lo == hi).all():
        return np.array([lo[0]]), np.array([lo[1]])

    gx, gy = np.meshgrid(np.arange(lo[0], hi[0] + 1), np.arange(lo[1], hi[1] + 1), indexing='ij')
    gx = gx.ravel()
    gy = gy.ravel()
    cx = gx + 0.5
    cy = gy + 0.5
    h = 0.5 - eps

    keep = ((cx + h > tri[:, 0].min()) & (cx - h < tri[:, 0].max()) &
            (cy + h > tri[:, 1].min()) & (cy - h < tri[:, 1].max()))
    for i in range(3):
        a, b = tri[i], tri[(i + 1) % 3]
        n = np.array([a[1] - b[1], b[0] - a[0]])
        length = math.hypot(n[0], n[1])
        if length < 1e-12:
            continue
        n /= length
        proj = tri @ n
        c = cx * n[0] + cy * n[1]
        r = h * (abs(n[0]) + abs(n[1]))
        keep &= (c + r > proj.min()) & (c - r < proj.max())

    if not keep.any():
        # A sliver that lies exactly on cell borders: fall back to the cells holding its corners.
        corners = np.clip(np.floor(tri).astype(int), 0, [shape[0] - 1, shape[1] - 1])
        return corners[:, 0], corners[:, 1]
    return gx[keep], gy[keep]


def cells_overlapping_triangles(tris: np.ndarray, shape: Tuple[int, int], eps: float = 1e-3) -> Tuple[np.ndarray, np.ndarray]:
    """cells_overlapping_triangle for many triangles (n x 3 x 2, cell units) at once; returns the unique cells.

    Scanline: for each row of cells a triangle reaches, the part of the triangle inside that row's strip is convex,
    so the cells it overlaps are exactly those within its y-extent there. The work follows the triangle's area,
    not its bounding box (long thin wall and slab triangles have huge boxes), and all triangles of an element
    are done in a handful of numpy calls. Cells only touching the triangle (within eps) are left out, as in
    cells_overlapping_triangle."""
    if len(tris) == 0:
        return np.empty(0, int), np.empty(0, int)
    limit = np.array([shape[0] - 1, shape[1] - 1])
    lo_x = np.maximum(np.floor(tris[:, :, 0].min(axis=1)).astype(np.int64), 0)
    hi_x = np.minimum(np.floor(tris[:, :, 0].max(axis=1)).astype(np.int64), limit[0])
    counts = np.maximum(hi_x - lo_x + 1, 0)
    total = int(counts.sum())
    if total == 0:
        return np.empty(0, int), np.empty(0, int)

    # One entry per (triangle, row of cells).
    tri = np.repeat(np.arange(len(tris)), counts)
    row = lo_x[tri] + np.arange(total) - np.repeat(np.cumsum(counts) - counts, counts)
    a = (row + eps)[:, None]
    b = (row + 1 - eps)[:, None]
    v = tris[tri]                       # (m, 3, 2)
    px, py = v[:, :, 0], v[:, :, 1]
    qx, qy = np.roll(px, -1, axis=1), np.roll(py, -1, axis=1)

    values = [py]
    masks = [(px >= a) & (px <= b)]     # corners inside the strip
    dx = qx - px
    safe = np.where(dx != 0, dx, 1.0)
    for c in (a, b):                    # edges crossing the strip's borders
        t = (c - px) / safe
        values.append(py + t * (qy - py))
        masks.append((dx != 0) & (t >= 0) & (t <= 1))
    vals = np.concatenate(values, axis=1)
    mask = np.concatenate(masks, axis=1)
    ymin = np.where(mask, vals, np.inf).min(axis=1)
    ymax = np.where(mask, vals, -np.inf).max(axis=1)

    hit = mask.any(axis=1)
    ymin = np.where(hit, ymin, 0.0)
    ymax = np.where(hit, ymax, 0.0)
    first = np.floor(ymin - 1 + eps).astype(np.int64) + 1      # cells with y0 + 1 - eps > ymin
    last = np.ceil(ymax - eps).astype(np.int64) - 1            # cells with y0 + eps < ymax
    first = np.where(hit, np.maximum(first, 0), 0)
    last = np.where(hit, np.minimum(last, limit[1]), -1)
    spans = np.maximum(last - first + 1, 0)

    n_cells = int(spans.sum())
    xs = np.repeat(row, spans)
    ys = np.repeat(first, spans) + np.arange(n_cells) - np.repeat(np.cumsum(spans) - spans, spans)

    # Slivers lying exactly on cell borders keep no cell: fall back to the cells holding their corners.
    empty = (np.bincount(tri, weights=spans, minlength=len(tris)) == 0) & (counts > 0)
    if empty.any():
        corners = np.clip(np.floor(tris[empty]).astype(np.int64), 0, limit).reshape(-1, 2)
        xs = np.concatenate([xs, corners[:, 0]])
        ys = np.concatenate([ys, corners[:, 1]])
    linear = np.unique(xs * shape[1] + ys)
    return linear // shape[1], linear % shape[1]


def cells_to_runs(xs: np.ndarray, ys: np.ndarray) -> List[List[int]]:
    """Cells as runs [row, first column, last column], a compact form for JSON."""
    order = np.lexsort((ys, xs))
    xs, ys = np.asarray(xs)[order], np.asarray(ys)[order]
    breaks = np.nonzero((np.diff(xs) != 0) | (np.diff(ys) != 1))[0] + 1
    starts = np.concatenate([[0], breaks])
    ends = np.concatenate([breaks, [len(xs)]]) - 1
    return [[int(xs[a]), int(ys[a]), int(ys[b])] for a, b in zip(starts, ends)]


class IFCProcessor:
    def __init__(self, file_path: str, grid_size: float = 0.1):
        self.file_path = file_path
        self.grid_size = grid_size
        self.ifc_file = None
        self.bbox = None
        self.floors = None
        self.grids = None
        self.unit_size = 1.0  # geometry from ifcopenshell is always in metres; kept for the JSON format
        self.spaces = []
        self.ifc_spaces = []  # IfcSpace footprints on the grid
        self.space_elements = []
        self.dropped_spaces = []  # IfcSpaces on no grid floor (a roof, a storey left out)
        self.doors = []
        self.targets = {}   # step id -> (instance, element type)
        self.shapes = {}    # step id -> (verts (n, 3), faces (m, 3)) in world metres
        self.skipped = Counter()

    def process(self) -> Dict[str, Any]:
        """Turn the IFC file into one grid per floor. Errors are raised, not hidden."""
        self.ifc_file = self.load_ifc_file()
        logger.info("IFC file loaded")
        self.collect_targets()
        self.load_shapes()
        self.bbox, self.floors = self.calculate_bounding_box_and_floors()
        self.grids = self.create_grids()
        self.process_elements()
        self.extract_ifc_spaces()
        self.trim_grids()

        warnings = {}
        if self.skipped:
            warnings['skipped_elements'] = dict(self.skipped)
            logger.warning(f"Elements without usable geometry were skipped: {dict(self.skipped)}")
        if self.dropped_spaces:
            warnings['spaces_on_no_floor'] = self.dropped_spaces
        return {
            'grids': [grid.tolist() for grid in self.grids],
            'bbox': self.bbox,
            'floors': self.floors,
            'grid_size': self.grid_size,
            'unit_size': self.unit_size,
            'spaces': self.spaces,
            'ifc_spaces': self.ifc_spaces,
            'doors': self.doors,
            'warnings': warnings,
        }

    def load_ifc_file(self) -> ifcopenshell.file:
        try:
            return ifcopenshell.open(self.file_path)
        except Exception as e:
            raise RuntimeError(f"Error loading IFC file: {str(e)}")

    def collect_targets(self) -> None:
        """Every element of a grid type, and its parts (curtain wall panels, stair flights, ...) with the parent's type.

        An element that has a type of its own and is also a part (a door in a curtain wall, a landing slab in a stair)
        gets the stronger of the two, door > stair > wall > floor, as the marking order does."""
        for cls in ALL_TYPES:
            for element in self.ifc_file.by_type(cls):
                element_type = get_element_type(element)
                if element_type is None:
                    continue
                self._add_target(element, element_type)
                for part in ifcopenshell.util.element.get_parts(element) or []:
                    self._add_target(part, element_type)
        self.space_elements = [s for s in self.ifc_file.by_type('IfcSpace') if s.Representation]

    def _add_target(self, element, element_type: str) -> None:
        current = self.targets.get(element.id())
        if current is None or TYPE_PRECEDENCE[element_type] < TYPE_PRECEDENCE[current[1]]:
            self.targets[element.id()] = (element, element_type)

    def load_shapes(self) -> None:
        """Triangulate all targets once with the geometry iterator, which picks each element's Body representation.

        (create_shape without a representation can pick the 2D Axis of a wall and fail.) Elements the iterator leaves
        out are retried one by one with their Body representation; the ones that still fail are counted in
        self.skipped, so the caller can report them."""
        settings = ifcopenshell.geom.settings()
        settings.set(settings.USE_WORLD_COORDS, True)
        elements = [inst for inst, _ in self.targets.values() if inst.Representation]
        instances = elements + self.space_elements
        if not instances:
            return

        iterator = ifcopenshell.geom.iterator(settings, self.ifc_file, max(1, multiprocessing.cpu_count() - 1), include=instances)
        if iterator.initialize():
            while True:
                shape = iterator.get()
                self._store_shape(shape.id, shape.geometry)
                if not iterator.next():
                    break

        for inst in instances:
            if inst.id() in self.shapes:
                continue
            body = next((r for r in inst.Representation.Representations if r.RepresentationIdentifier == 'Body'), None)
            try:
                shape = ifcopenshell.geom.create_shape(settings, inst, body)
                self._store_shape(inst.id(), shape.geometry)
            except Exception:
                pass
            if inst.id() not in self.shapes:
                self.skipped[inst.is_a()] += 1
        logger.info(f"Triangulated {len(self.shapes)} of {len(instances)} elements")

    def _store_shape(self, step_id: int, geometry) -> None:
        verts = np.asarray(geometry.verts, dtype=float).reshape(-1, 3)
        faces = np.asarray(geometry.faces, dtype=int).reshape(-1, 3)
        if len(verts) and len(faces):
            self.shapes[step_id] = (verts, faces)

    def calculate_bounding_box_and_floors(self) -> Tuple[Dict[str, float], List[Dict]]:
        wall_ids = [i for i, (_, t) in self.targets.items() if t == 'wall' and i in self.shapes]
        space_ids = {s.id() for s in self.space_elements}
        ids = wall_ids or [i for i in self.shapes if i not in space_ids]
        if not ids:
            raise RuntimeError("No walls, slabs, doors or stairs with usable geometry were found in the IFC file")
        verts = np.vstack([self.shapes[i][0] for i in ids])
        mins, maxs = verts.min(axis=0), verts.max(axis=0)
        bbox = {'min_x': float(mins[0]), 'min_y': float(mins[1]), 'min_z': float(mins[2]),
                'max_x': float(maxs[0]), 'max_y': float(maxs[1]), 'max_z': float(maxs[2])}
        logger.info(f"Calculated bounding box: {bbox}")
        for axis in 'xyz':
            size = bbox[f'max_{axis}'] - bbox[f'min_{axis}']
            if size > 1000:
                logger.warning(f"Unreasonably large bounding box size for {axis}-axis: {size} meters")

        storeys = []
        seen = set()
        for storey in sorted(self.storey_elevations(), key=lambda s: s['elevation']):
            if round(storey['elevation'], 4) in seen:
                continue
            seen.add(round(storey['elevation'], 4))
            storeys.append(storey)

        if not storeys:
            logger.warning("No storeys with an elevation found, creating floors every 3 m")
            num_floors = max(1, int((bbox['max_z'] - bbox['min_z']) / 3))
            storeys = [{'elevation': float(e), 'guid': None, 'name': f"Level {i}"}
                       for i, e in enumerate(np.linspace(bbox['min_z'], bbox['max_z'], num_floors + 1)[:-1])]

        floors = []
        for i, storey in enumerate(storeys):
            next_elevation = storeys[i + 1]['elevation'] if i < len(storeys) - 1 else bbox['max_z']
            height = next_elevation - storey['elevation']
            if 1.6 < height < 10:
                floors.append({**storey, 'height': height})

        if not floors:
            logger.warning("No valid floors found, creating a single floor based on bounding box")
            floors = [{'elevation': bbox['min_z'], 'height': bbox['max_z'] - bbox['min_z'], 'guid': None, 'name': 'Level 0'}]

        logger.debug(f"Created {len(floors)} floors: {floors}")
        return bbox, floors

    def storey_elevations(self) -> List[Dict[str, Any]]:
        """World height of each storey in metres, the frame the geometry is in.

        IfcBuildingStorey.Elevation is relative to the building, so a georeferenced model (site placed at 198.5 m,
        say) would match no element to any floor. The storey's placement gives its world height; when all storeys
        share one placement height (an exporter that only fills Elevation) that height is the base and Elevation
        is added to it."""
        unit_scale = ifcopenshell.util.unit.calculate_unit_scale(self.ifc_file)
        rows = []
        for storey in self.ifc_file.by_type("IfcBuildingStorey"):
            placed = None
            if storey.ObjectPlacement:
                placed = float(ifcopenshell.util.placement.get_local_placement(storey.ObjectPlacement)[2][3]) * unit_scale
            attribute = float(storey.Elevation) * unit_scale if storey.Elevation is not None else None
            if placed is None and attribute is None:
                continue
            rows.append((storey, placed, attribute))
        if not rows:
            return []

        placed_heights = {round(p, 3) for _, p, _ in rows if p is not None}
        attribute_heights = {round(a, 3) for _, _, a in rows if a is not None}
        collapsed = len(placed_heights) <= 1 < len(attribute_heights)
        storeys = []
        for storey, placed, attribute in rows:
            if placed is None:
                elevation = attribute
            elif collapsed and attribute is not None:
                elevation = placed + attribute
            else:
                elevation = placed
            # relative_elevation (the Elevation attribute, 0 = the building's ±0.00) finds the evacuation level.
            storeys.append({'elevation': elevation, 'relative_elevation': attribute,
                            'guid': storey.GlobalId, 'name': storey.Name})
        return storeys

    def create_grids(self) -> List[np.ndarray]:
        x_cells = int(np.ceil((self.bbox['max_x'] - self.bbox['min_x']) / self.grid_size)) + 6
        y_cells = int(np.ceil((self.bbox['max_y'] - self.bbox['min_y']) / self.grid_size)) + 6
        logger.info(f"Creating grid with dimensions: {x_cells} x {y_cells}")
        if x_cells > 10000 or y_cells > 10000:
            logger.warning(f"Very large grid size: {x_cells} x {y_cells}. Use a larger grid size for this model.")
        return [np.full((x_cells, y_cells), 'empty', dtype=object) for _ in self.floors]

    def process_elements(self) -> None:
        for i, (step_id, (element, element_type)) in enumerate(self.targets.items()):
            if i % 250 == 0:
                logger.info(f"Processing element {i} out of {len(self.targets)}.")
            if step_id in self.shapes:
                verts, faces = self.shapes[step_id]
                self.process_single_element(element, verts, faces, element_type)

    def process_single_element(self, element, verts: np.ndarray, faces: np.ndarray, element_type: str) -> bool:
        min_x, min_y, min_z = verts.min(axis=0)
        max_x, max_y, max_z = verts.max(axis=0)
        if element_type == 'floor':
            min_z += 0.5
        if element_type in ('floor', 'stair'):
            max_z += 1.5  # Extend the floors/stairs up so they get detected better

        for floor_index, floor in enumerate(self.floors):
            if min_z < floor['elevation'] + 2 and max_z > floor['elevation'] + 0.1:
                if element_type == 'door':
                    cells = self.mark_door(floor_index, min_x, min_y, max_x, max_y, floor)
                    self.record_door(element, floor_index, cells)
                else:
                    self.mark_triangles(verts, faces, self.grids[floor_index], floor, element_type)
        return True

    def extract_ifc_spaces(self) -> None:
        """Each IfcSpace's footprint as grid cells on the floor its bottom stands on, with its name.

        The routes are checked per IFC space by default (detected regions are the fallback for floors without
        IfcSpaces). A space is put on the floor whose level is the highest at or below its bottom (0.6 m margin)."""
        origin = np.array([self.bbox['min_x'], self.bbox['min_y']])
        shape = self.grids[0].shape if self.grids else (0, 0)
        names = Counter()
        for space in self.space_elements:
            if space.id() not in self.shapes:
                continue
            verts, faces = self.shapes[space.id()]
            bottom = float(verts[:, 2].min())
            floor_index = None
            for i, floor in enumerate(self.floors):
                if floor['elevation'] - 0.6 <= bottom:
                    floor_index = i
            if floor_index is None or bottom >= self.floors[floor_index]['elevation'] + self.floors[floor_index]['height']:
                self.dropped_spaces.append(' '.join(t for t in (space.Name, getattr(space, 'LongName', None)) if t) or space.GlobalId)
                continue
            plan = (verts[faces][:, :, :2] - origin) / self.grid_size
            xs, ys = cells_overlapping_triangles(plan, shape)
            if len(xs) == 0:
                continue
            label = ' '.join(t for t in (space.Name, getattr(space, 'LongName', None)) if t) or space.GlobalId
            names[label] += 1
            self.ifc_spaces.append({'guid': space.GlobalId, 'name': label, 'floor': floor_index,
                                    'runs': cells_to_runs(xs, ys)})
        for space in self.ifc_spaces:  # names must be unique: results are matched to spaces by name
            if names[space['name']] > 1:
                space['name'] = f"{space['name']} ({space['guid']})"

    def record_door(self, door, floor_index: int, cells: List[int]) -> None:
        """Keep what the IFC says about a door, so exits can be found from data instead of geometry alone."""
        door_common = ifcopenshell.util.element.get_psets(door).get('Pset_DoorCommon', {})
        self.doors.append({
            'guid': door.GlobalId,
            'name': door.Name,
            'floor': floor_index,
            'cells': cells,  # [start_x, end_x, start_y, end_y], inclusive
            'is_external': door_common.get('IsExternal'),
            'fire_exit': door_common.get('FireExit'),
        })

    def mark_door(self, floor_index: int, min_x: float, min_y: float, max_x: float, max_y: float, floor: Dict[str, float]) -> List[int]:
        start_x = (min_x - self.bbox['min_x']) / self.grid_size
        end_x = (max_x - self.bbox['min_x']) / self.grid_size
        start_y = (min_y - self.bbox['min_y']) / self.grid_size
        end_y = (max_y - self.bbox['min_y']) / self.grid_size
        size_x = abs(start_x - end_x)
        size_y = abs(start_y - end_y)
        if size_x > size_y:  # Extend doors somewhat, prevents them being blocked by walls extending slightly too far.
            start_y = start_y - 0.1 / self.grid_size
            end_y = end_y + 0.1 / self.grid_size
        else:
            start_x = start_x - 0.1 / self.grid_size
            end_x = end_x + 0.1 / self.grid_size
        start_x = int(max(0, start_x))
        end_x = int(min(float(self.grids[floor_index].shape[0] - 1), end_x))
        start_y = int(max(0, start_y))
        end_y = int(min(float(self.grids[floor_index].shape[1] - 1), end_y))
        self.grids[floor_index][start_x:end_x + 1, start_y:end_y + 1] = 'door'
        return [start_x, end_x, start_y, end_y]

    def get_element_type(self, element: ifcopenshell.entity_instance) -> Optional[str]:
        return get_element_type(element)

    def mark_triangles(self, verts: np.ndarray, faces: np.ndarray, grid: np.ndarray, floor: Dict[str, float], element_type: str) -> None:
        """Mark the cells each triangle covers in plan (not its bounding box, so rotated walls stay thin)."""
        tris = verts[faces]
        if element_type not in ('floor', 'stair'):
            # Floors and stairs were matched to this floor as a whole; walls by the triangles that reach into it.
            z = tris[:, :, 2]
            tris = tris[(z.min(axis=1) < floor['elevation'] + 2) & (z.max(axis=1) > floor['elevation'])]
        if len(tris) == 0:
            return
        origin = np.array([self.bbox['min_x'], self.bbox['min_y']])
        plan = (tris[:, :, :2] - origin) / self.grid_size
        xs, ys = cells_overlapping_triangles(plan, grid.shape)
        if len(xs) == 0:
            return
        current = grid[xs, ys]
        if element_type == 'wall':
            allowed = current != 'door'
        elif element_type == 'stair':
            allowed = (current != 'door') & (current != 'wall')
        elif element_type == 'floor':
            allowed = current == 'empty'
        else:
            allowed = np.ones(len(xs), bool)
        grid[xs[allowed], ys[allowed]] = element_type

    def mark_cells(self, triangle: List[List[float]], grid: np.ndarray, floor: Dict[str, float], element_type: str) -> None:
        """One triangle given as three [x, y, z] points (kept for callers of the old interface)."""
        self.mark_triangles(np.asarray(triangle, dtype=float), np.array([[0, 1, 2]]), grid, floor, element_type)

    def trim_grids(self, padding: int = 1) -> None:
        logger.info("Starting grid trimming process")
        min_x_global = min_y_global = float('inf')
        max_x_global = max_y_global = float('-inf')
        all_empty = True

        for grid in self.grids:
            non_empty = np.argwhere((grid != 'empty') & (grid != 'floor'))
            if len(non_empty) == 0:
                continue
            all_empty = False
            min_x, min_y = non_empty.min(axis=0)
            max_x, max_y = non_empty.max(axis=0)
            min_x_global = min(min_x_global, min_x)
            max_x_global = max(max_x_global, max_x)
            min_y_global = min(min_y_global, min_y)
            max_y_global = max(max_y_global, max_y)

        if all_empty:
            logger.warning("All grids are empty or contain only floor cells. Skipping trimming.")
            return

        shape = self.grids[0].shape
        start_x = max(0, int(min_x_global - padding))
        end_x = min(shape[0], int(max_x_global + padding + 1))
        start_y = max(0, int(min_y_global - padding))
        end_y = min(shape[1], int(max_y_global + padding + 1))

        trimmed_grids = []
        for grid in self.grids:
            trimmed = grid[start_x:end_x, start_y:end_y]
            padded = np.full((trimmed.shape[0] + 2 * padding, trimmed.shape[1] + 2 * padding), 'empty', dtype=object)
            padded[padding:-padding, padding:-padding] = trimmed
            trimmed_grids.append(padded)
        self.grids = trimmed_grids

        # Cell (start_x, start_y) of the old grid is now cell (padding, padding).
        shift_x, shift_y = padding - start_x, padding - start_y
        for door in self.doors:
            x0, x1, y0, y1 = door['cells']
            door['cells'] = [x0 + shift_x, x1 + shift_x, y0 + shift_y, y1 + shift_y]
        rows, cols = self.grids[0].shape
        for space in self.ifc_spaces:
            runs = [[x + shift_x, max(y0 + shift_y, 0), min(y1 + shift_y, cols - 1)] for x, y0, y1 in space['runs']]
            space['runs'] = [r for r in runs if 0 <= r[0] < rows and r[1] <= r[2]]
        self.bbox['min_x'] -= self.grid_size * shift_x
        self.bbox['min_y'] -= self.grid_size * shift_y
        self.bbox['max_x'] = self.bbox['min_x'] + self.grids[0].shape[0] * self.grid_size
        self.bbox['max_y'] = self.bbox['min_y'] + self.grids[0].shape[1] * self.grid_size

        logger.info(f"Final grid dimensions: {self.grids[0].shape}, bounding box: {self.bbox}")


def process_ifc_file(file_path: str, grid_size: float = 0.1) -> Dict[str, Any]:
    processor = IFCProcessor(file_path, grid_size)
    return processor.process()

def create_escape_route_segment(ifcfile, sb, body, storey, points, grid_type, width=0.8, height=1.5, plan_width=0.8, unit_scale=1.0, space_name="", floor_number = 0):
    unit_scale = 1
    width = width / unit_scale
    height = height / unit_scale
    plan_width = plan_width / unit_scale
    plan_height = 0.01 / unit_scale  # 1cm height for plan view

    # Create two separate IfcBuildingElementProxy elements
    escape_route_3d = ifcopenshell.api.run("root.create_entity", ifcfile, ifc_class="IfcBuildingElementProxy", name=f"EscapeRoute3D_{space_name}_floor_{floor_number}")
    escape_route_plan = ifcopenshell.api.run("root.create_entity", ifcfile, ifc_class="IfcBuildingElementProxy", name=f"EscapeRoutePlan_{space_name}_floor_{floor_number}")

    # Calculate offset points for left and right curves
    left_points = []
    right_points = []
    plan_left_points = []
    plan_right_points = []
    
    for i in range(len(points)):
        #if path_info[i]['space'] and path_info[i]['space'] not in passed_spaces:
        #    passed_spaces.append(path_info[i]['space'])
        if i == 0:
            dx = points[1][0] - points[0][0]
            dy = points[1][1] - points[0][1]
        elif i == len(points) - 1:
            dx = points[-1][0] - points[-2][0]
            dy = points[-1][1] - points[-2][1]
        else:
            dx1 = points[i][0] - points[i-1][0]
            dy1 = points[i][1] - points[i-1][1]
            dx2 = points[i+1][0] - points[i][0]
            dy2 = points[i+1][1] - points[i][1]
            dx = (dx1 + dx2) / 2
            dy = (dy1 + dy2) / 2

        length = math.sqrt(dx*dx + dy*dy)
        if length <= 0:
            length = 1
        dx /= length
        dy /= length

        perpx = -dy
        perpy = dx

        # Adjust width and height based on path_info
        current_width = width
        current_height = height
        current_plan_width = plan_width
        
        if grid_type[i] == 'door':
            current_width *= 0.6  # Reduce width at doors
            current_plan_width *= 0.6
        elif grid_type[i] == 'stair':
            current_width *= 0.6
            current_plan_width *= 0.6

        left_points.append((
            points[i][0] + perpx * current_width/2,
            points[i][1] + perpy * current_width/2,
            points[i][2]
        ))
        right_points.append((
            points[i][0] - perpx * current_width/2,
            points[i][1] - perpy * current_width/2,
            points[i][2]
        ))
        plan_left_points.append((
            points[i][0] + perpx * current_plan_width/2,
            points[i][1] + perpy * current_plan_width/2,
            points[i][2]
        ))
        plan_right_points.append((
            points[i][0] - perpx * current_plan_width/2,
            points[i][1] - perpy * current_plan_width/2,
            points[i][2]
        ))

    # Create vertices for the 3D polygon
    vertices = []
    for i in range(len(left_points)):
        vertices.append(left_points[i])
        vertices.append((left_points[i][0], left_points[i][1], left_points[i][2] + current_height))
        vertices.append(right_points[i])
        vertices.append((right_points[i][0], right_points[i][1], right_points[i][2] + current_height))

    # Create edges for the 3D polygon
    edges = []
    n = len(left_points)
    for i in range(0, 4*n-4, 4):
        edges.extend([(i, i+4), (i+1, i+5), (i+2, i+6), (i+3, i+7)])
        edges.extend([(i, i+1), (i+2, i+3)])
        edges.extend([(i, i+2), (i+1, i+3)])
    edges.extend([(4*n-4, 4*n-3), (4*n-2, 4*n-1), (4*n-4, 4*n-2), (4*n-3, 4*n-1)])

    # Create faces for the 3D polygon
    faces = []
    for i in range(0, 4*n-4, 4):
        faces.append([i, i+4, i+5, i+1])
        faces.append([i+2, i+3, i+7, i+6])
        faces.append([i, i+2, i+6, i+4])
        faces.append([i+1, i+5, i+7, i+3])
    faces.append([0, 1, 3, 2])
    faces.append([4*n-4, 4*n-2, 4*n-1, 4*n-3])

    # Create mesh representation for 3D geometry
    representation_3d = ifcopenshell.api.run(
        "geometry.add_mesh_representation",
        ifcfile,
        context=body,
        vertices=[vertices],
        edges=[edges],
        faces=[faces]
    )

    # Create vertices for the plan view polygon
    plan_vertices = []
    for i in range(len(plan_left_points)):
        plan_vertices.append(plan_left_points[i])
        plan_vertices.append((plan_left_points[i][0], plan_left_points[i][1], plan_left_points[i][2] + plan_height))
        plan_vertices.append(plan_right_points[i])
        plan_vertices.append((plan_right_points[i][0], plan_right_points[i][1], plan_right_points[i][2] + plan_height))

    # Create edges and faces for the plan view polygon (similar to 3D polygon)
    plan_edges = []
    plan_faces = []
    for i in range(0, 4*n-4, 4):
        plan_edges.extend([(i, i+4), (i+1, i+5), (i+2, i+6), (i+3, i+7)])
        plan_edges.extend([(i, i+1), (i+2, i+3)])
        plan_edges.extend([(i, i+2), (i+1, i+3)])
        plan_faces.append([i, i+4, i+6, i+2])
        plan_faces.append([i+1, i+3, i+7, i+5])
    plan_edges.extend([(4*n-4, 4*n-3), (4*n-2, 4*n-1), (4*n-4, 4*n-2), (4*n-3, 4*n-1)])
    plan_faces.append([0, 1, 3, 2])
    plan_faces.append([4*n-4, 4*n-2, 4*n-1, 4*n-3])

    # Create mesh representation for plan view geometry
    representation_plan = ifcopenshell.api.run(
        "geometry.add_mesh_representation",
        ifcfile,
        context=body,
        vertices=[plan_vertices],
        edges=[plan_edges],
        faces=[plan_faces]
    )

    # Assign representations
    ifcopenshell.api.run("geometry.assign_representation", ifcfile, product=escape_route_3d, representation=representation_3d)
    ifcopenshell.api.run("geometry.assign_representation", ifcfile, product=escape_route_plan, representation=representation_plan)

    # Assign to storey
    ifcopenshell.api.run("spatial.assign_container", ifcfile, relating_structure=storey, products=[escape_route_3d])
    ifcopenshell.api.run("spatial.assign_container", ifcfile, relating_structure=storey, products=[escape_route_plan])

    # Set placement
    ifcopenshell.api.run("geometry.edit_object_placement", ifcfile, product=escape_route_3d)
    ifcopenshell.api.run("geometry.edit_object_placement", ifcfile, product=escape_route_plan)

    return escape_route_3d, escape_route_plan

def add_escape_routes_to_ifc(original_file, new_file, routes, grid_size, bbox, floors):
    ifcfile = ifcopenshell.open(original_file)

    # Detect the length unit
    project = ifcfile.by_type("IfcProject")[0]
    unit_scale = ifcopenshell.util.unit.calculate_unit_scale(ifcfile)#, unit_type="si_meters")

    
    logger.debug(f"Detected unit scale: {unit_scale}")
    unit_scale = 1
    
    # Get or create necessary IFC elements
    project = ifcfile.by_type("IfcProject")[0]
    site = ifcfile.by_type("IfcSite")[0] if ifcfile.by_type("IfcSite") else ifcopenshell.api.run("root.create_entity", ifcfile, ifc_class="IfcSite")
    building = ifcfile.by_type("IfcBuilding")[0] if ifcfile.by_type("IfcBuilding") else ifcopenshell.api.run("root.create_entity", ifcfile, ifc_class="IfcBuilding")
    
    # Ensure site and building are in the project structure
    with suppress_stdout():
        ifcopenshell.api.run("aggregate.assign_object", ifcfile, relating_object=project, products=[site])
        ifcopenshell.api.run("aggregate.assign_object", ifcfile, relating_object=site, products=[building])

    storeys_by_guid = {storey.GlobalId: storey for storey in ifcfile.by_type("IfcBuildingStorey")}

    # Get context
    body = ifcopenshell.util.representation.get_context(ifcfile, "Model", "Body", "MODEL_VIEW")
    if not body:
        model = ifcopenshell.api.run("context.add_context", ifcfile, context_type="Model")
        body = ifcopenshell.api.run("context.add_context", ifcfile, 
                                            context_type="Model", 
                                            context_identifier="Body", 
                                            target_view="MODEL_VIEW", 
                                            parent=model)
    
    # Create shape builder
    sb = ifcopenshell.util.shape_builder.ShapeBuilder(ifcfile)

    # Create IfcGroup for all escape routes
    escape_routes_group = ifcfile.create_entity("IfcGroup", Name="EscapeRoutes")

    # Create separate groups for 3D and plan representations
    escape_routes_3d_group = ifcfile.create_entity("IfcGroup", Name="EscapeRoutes3D")
    escape_routes_plan_group = ifcfile.create_entity("IfcGroup", Name="EscapeRoutesPlan")

    # Assign 3D and plan groups to the main escape routes group
    ifcopenshell.api.run("group.assign_group", ifcfile, group=escape_routes_group, products=[escape_routes_3d_group, escape_routes_plan_group])


    # Create floor groups for 3D and plan
    floor_groups_3d = {}
    floor_groups_plan = {}
    for floor_index in range(len(floors)):
        floor_group_3d = ifcfile.create_entity("IfcGroup", Name=f"EscapeRoutes3D_Floor_{floor_index}")
        floor_group_plan = ifcfile.create_entity("IfcGroup", Name=f"EscapeRoutesPlan_Floor_{floor_index}")
        ifcopenshell.api.run("group.assign_group", ifcfile, group=escape_routes_3d_group, products=[floor_group_3d])
        ifcopenshell.api.run("group.assign_group", ifcfile, group=escape_routes_plan_group, products=[floor_group_plan])
        floor_groups_3d[floor_index] = floor_group_3d
        floor_groups_plan[floor_index] = floor_group_plan

    for route in routes:
        logger.info(f"Processing route for space: {route['space_name']}")
        
        # Create IfcGroup for the specific route
        route_group = ifcfile.create_entity("IfcGroup", Name=f"EscapeRoute_{route['space_name']}")
        ifcopenshell.api.run("group.assign_group", ifcfile, group=escape_routes_group, products=[route_group])

        # Prepare route properties
        prop_dict = {
            "RoomName": route['space_name']
        }
        if 'distance' in route and route['distance'] is not None:
            prop_dict["TotalPathLength"] = float(route['distance'])
        if 'distance_to_stair' in route and route['distance_to_stair'] is not None and route['distance_to_stair'] > 0:
            prop_dict["DistanceToFirstStair"] = float(route['distance_to_stair'])
        if route.get('second_exit_distance') is not None:
            prop_dict["DistanceToSecondExit"] = float(route['second_exit_distance'])

        violations = route['violations']
        has_violations = False
        has_violations_day_general = False
        # Add route properties
        if violations['general']:
            prop_dict.update({"General violations": violations['general']})
            has_violations = True
            has_violations_day_general = True
        if violations['daytime']:
            prop_dict.update({"Daytime violations": violations['daytime']})
            has_violations = True
            has_violations_day_general = True
        if violations['nighttime']:
            prop_dict.update({"Nighttime violations": violations['nighttime']})
            has_violations = True
        #logger.info(f"Floors: {floors}")
        if 'optimal_path' in route and route['optimal_path']:
            #logger.info(f"Optimal path found: {route['optimal_path']}")
            # Points per floor, each with its own cell type, plus the connection points where the route changes floor.
            points_by_floor = {}
            types_by_floor = {}
            grid_types = route.get('grid_type') or ['floor'] * len(route['optimal_path'])
            prev_floor = None
            prev_point = None
            prev_type = None
            for point, cell_type in zip(route['optimal_path'], grid_types):
                floor_index = int(point[2])
                points_by_floor.setdefault(floor_index, [])
                types_by_floor.setdefault(floor_index, [])

                if prev_floor is not None and floor_index != prev_floor:
                    points_by_floor[prev_floor].append(point)
                    types_by_floor[prev_floor].append(cell_type)
                    points_by_floor[floor_index].append(prev_point)
                    types_by_floor[floor_index].append(prev_type)

                points_by_floor[floor_index].append(point)
                types_by_floor[floor_index].append(cell_type)

                prev_floor = floor_index
                prev_point = point
                prev_type = cell_type
                
            #logger.warning(f"Points by floor: {points_by_floor}")

            # Process each floor segment
            for floor_index, floor_points in points_by_floor.items():
                if len(floor_points) < 2:
                    continue  # a single point has no direction to build a segment from
                floor_data = floors[floor_index]
                storey = None
                if floor_data.get('guid'):
                    try:
                        storey = ifcfile.by_guid(floor_data['guid'])
                    except RuntimeError:
                        storey = None
                elevation = floor_data['elevation']
                #logger.info(f"Processing floor: {floor_index}")
                #logger.info(f"Storey: {storey}")
                if not storey:
                    logger.warning(f"Storey not found for floor {floor_index}, using default storey")
                    storey = ifcfile.by_type("IfcBuildingStorey")[0]

                points = prepare_route_points(floor_points, grid_size, bbox, elevation, floors)
                
                # Create separate 3D and plan segments for this floor segment
                segment_3d, segment_plan = create_escape_route_segment(
                    ifcfile, sb, body, storey, points, types_by_floor[floor_index],
                    width=0.7, height=1.5, plan_width=0.8, unit_scale=unit_scale, space_name=route['space_name'],
                    floor_number=floor_index
                )

                # Add properties to both 3D and plan segments
                add_properties_to_element(ifcfile, segment_3d, prop_dict)
                add_properties_to_element(ifcfile, segment_plan, prop_dict)

                # Add route segments to respective groups
                ifcopenshell.api.run("group.assign_group", ifcfile, group=floor_groups_3d[floor_index], products=[segment_3d])
                ifcopenshell.api.run("group.assign_group", ifcfile, group=floor_groups_plan[floor_index], products=[segment_plan])
                ifcopenshell.api.run("group.assign_group", ifcfile, group=route_group, products=[segment_3d, segment_plan])

                # Set color (green for routes with no violations, red for with, orange for only nighttime)
                if has_violations and has_violations_day_general:
                    set_color(ifcfile, segment_3d, (1.0, 0.5, 0.5))
                    set_color(ifcfile, segment_plan, (1.0, 0.5, 0.5))
                elif has_violations and not has_violations_day_general:
                    set_color(ifcfile, segment_3d, (1.0, 0.7, 0.1))
                    set_color(ifcfile, segment_plan, (1.0, 0.7, 0.1))
                else:
                    set_color(ifcfile, segment_3d, (0.5, 1.0, 0.5))
                    set_color(ifcfile, segment_plan, (0.5, 1.0, 0.5))

    ifcfile.write(new_file)
    return {"new_file_path": new_file}


def create_polygon_segment(ifcfile, sb, body, storey, points, elevation):
    # Create the polygon segment as an IfcBuildingElementProxy
    polygon_segment = ifcopenshell.api.run("root.create_entity", ifcfile, ifc_class="IfcBuildingElementProxy", name="SpacePolygon")

    # Create profile
    profile_points = [ifcfile.createIfcCartesianPoint(list(map(float, point[:2]))) for point in points]
    polyline = ifcfile.createIfcPolyline(profile_points)
    
    # Create IfcArbitraryClosedProfileDef
    profile = ifcfile.createIfcArbitraryClosedProfileDef("AREA", None, polyline)

    # Create extrusion
    extrusion_vector = ifcfile.createIfcDirection((0.0, 0.0, 1.0))
    position = ifcfile.createIfcAxis2Placement3D(
        ifcfile.createIfcCartesianPoint((0.0, 0.0, points[0][2])),
        ifcfile.createIfcDirection((0.0, 0.0, 1.0)),
        ifcfile.createIfcDirection((1.0, 0.0, 0.0))
    )
    extruded_solid = ifcfile.createIfcExtrudedAreaSolid(profile, position, extrusion_vector, 1.0)  # 1.0m height

    # Get representation
    representation = ifcfile.createIfcShapeRepresentation(
        body, "Body", "SweptSolid", [extruded_solid]
    )

    # Assign representation
    ifcopenshell.api.run("geometry.assign_representation", ifcfile, products=[polygon_segment], representation=representation)

    # Assign to storey
    with suppress_stdout():
        ifcopenshell.api.run("spatial.assign_container", ifcfile, relating_structure=storey, products=[polygon_segment])

    # Set placement
    ifcopenshell.api.run("geometry.edit_object_placement", ifcfile, products=[polygon_segment])

    return polygon_segment

def set_color(ifcfile, product, color):
    style = ifcopenshell.api.run("style.add_style", ifcfile, name=f"Color_{product.Name}")
    ifcopenshell.api.run("style.add_surface_style", ifcfile, style=style, ifc_class="IfcSurfaceStyleShading", attributes={
        "SurfaceColour": { "Name": None, "Red": color[0], "Green": color[1], "Blue": color[2] }
    })
    ifcopenshell.api.run("style.assign_representation_styles", ifcfile, shape_representation=product.Representation.Representations[0], styles=[style])


def prepare_route_points(optimal_path, grid_size, bbox, elevation, floors):
    return [
        (float(p[0] * grid_size) + bbox['min_x'],
         float(p[1] * grid_size) + bbox['min_y'],
         float(floors[int(p[2])]['elevation']) + 0.1)
        for p in optimal_path
    ]

def add_properties_to_group(ifcfile, group, properties):
    property_set = ifcopenshell.api.run("pset.add_pset", ifcfile, products=[group], name="EscapeRouteProperties")
    for name, value in properties.items():
        ifcopenshell.api.run("pset.edit_pset", ifcfile, pset=property_set, properties={name: str(value)})

def add_properties_to_element(ifcfile, element, properties):
    property_set = ifcopenshell.api.run("pset.add_pset", ifcfile, product=element, name="EscapeRouteProperties")
    for name, value in properties.items():
        ifcopenshell.api.run("pset.edit_pset", ifcfile, pset=property_set, properties={name: str(value)})

def create_site(ifc_file, project):
    site = ifc_file.create_entity("IfcSite", GlobalId=ifcopenshell.guid.new(), Name="Site")
    ifc_file.create_entity("IfcRelAggregates", GlobalId=ifcopenshell.guid.new(), 
                           RelatingObject=project, RelatedObjects=[site])
    return site

def create_building(ifc_file, site):
    building = ifc_file.create_entity("IfcBuilding", GlobalId=ifcopenshell.guid.new(), Name="Building")
    ifc_file.create_entity("IfcRelAggregates", GlobalId=ifcopenshell.guid.new(), 
                           RelatingObject=site, RelatedObjects=[building])
    return building

def prepare_route_properties(route):
    prop_dict = {
        "RoomName": route['space_name'],
        "TotalPathLength": route['distance']
    }
    if route['distance_to_stair'] > 0:
        prop_dict["DistanceToFirstStair"] = route['distance_to_stair']
    
    for violation_type, violations in route['violations'].items():
        if violations:
            prop_dict[f"{violation_type.capitalize()}Violations"] = ", ".join(violations)
    
    return prop_dict

def assign_color_to_element(ifc_file, element, color):
    rgb = ifc_file.createIfcColourRgb(None, *color)
    color_style = ifc_file.createIfcSurfaceStyleRendering(rgb, 0.0, None, None, None, None, None, None, "FLAT")
    surface_style = ifc_file.createIfcSurfaceStyle(None, "BOTH", [color_style])
    presentation_style_assignment = ifc_file.createIfcPresentationStyleAssignment([surface_style])
    styled_item = ifc_file.createIfcStyledItem(element.Representation.Representations[0].Items[0], [presentation_style_assignment], None)
    return styled_item

@contextmanager
def suppress_stdout():
    with open(os.devnull, "w") as devnull:
        old_stdout = sys.stdout
        sys.stdout = devnull
        try:  
            yield
        finally:
            sys.stdout = old_stdout