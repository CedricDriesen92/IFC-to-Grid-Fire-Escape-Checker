"""Escape routes on the grid, checked against KB 7 July 1994, annex 2/1 (low buildings, LG).

The grid becomes a sparse graph (one node per passable cell, scipy CSR), searched with scipy's Dijkstra in C.

Exits follow LG 4.4.1.2: a door to the open air on an evacuation level, or the access to a stairwell (a stair
that reaches an evacuation level) on any other floor. Distances are measured on the person's own floor to the
access of the exit (LG 4.4.1.1); the way through the stairwell and in the open air does not count."""
import math
from collections import defaultdict
from typing import List, Tuple, Dict, Any, Optional

import numpy as np
from scipy import ndimage, sparse
from scipy.sparse.csgraph import dijkstra, connected_components
from scipy.spatial import cKDTree

import logging

from grid_codec import NAMES, DOOR, STAIR, PASSABLE, to_codes
import i18n

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

BLOCKED = ('wall', 'walla', 'empty')

# LG 4.4.1.1, metres
MAX_TRAVEL_DISTANCES = {
    'daytime': {
        'toEvacRoute': 30,
        'toNearestExit': 45,
        'toSecondExit': 80
    },
    'nighttime': {
        'toEvacRoute': 20,
        'toNearestExit': 30,
        'toSecondExit': 60
    }
}
# Second exits further than this (metres) are reported as "more than" it instead of measured.
SECOND_EXIT_SEARCH_LIMIT = 100.0

# What the grid cannot show; reported with the results so a pass is not read as full compliance.
NOT_CHECKED = i18n.not_checked('en')

# Path smoothing: candidates (cells furthest by grid distance, at least 1 m apart) whose route is straightened to
# true lines of sight.
SMOOTHING_CANDIDATES = 8
SMOOTHING_POOL = 400

_NAME_ARRAY = np.array(NAMES, dtype=object)


def required_exits(occupancy: Optional[float]) -> int:
    """LG 2.2.1: one exit below 100 persons, two from 100 to 499, 2 + n from 500 on, n being the whole number
    immediately greater than occupancy / 1000."""
    if occupancy is None or occupancy < 100:
        return 1
    if occupancy < 500:
        return 2
    return 2 + int(occupancy // 1000) + 1


class Pathfinder:
    def __init__(self, original_grids, buffered_grids, grid_size: float, floors: List[Dict[str, float]], bbox: Dict[str, float], allow_diagonal: bool = True, minimize_cost: bool = False):
        self.original_grids = original_grids
        self.buffered_grids = buffered_grids
        self.grid_size = grid_size
        self.floors = floors
        self.bbox = bbox
        self.allow_diagonal = allow_diagonal
        self.minimize_cost = minimize_cost

        self.codes = np.stack(to_codes(buffered_grids))
        self.original_codes = self.codes if original_grids is buffered_grids else np.stack(to_codes(original_grids))
        self.grids = self.codes  # self.grids[f][x][y] is a cell code
        self.F, self.R, self.C = self.codes.shape
        self.N = self.F * self.R * self.C
        self.passable = np.isin(self.codes, PASSABLE)

        self.graph = None     # all edges (CSR, directed both ways)
        self.planar = None    # without the stair edges between floors
        self.stair_edges: List[Tuple[Tuple[int, int, int], Tuple[int, int, int], float]] = []
        self._stair_labels = None
        self._components = None
        self._planar_labels = None
        self._fields = {}
        self._loose = None        # planar graph of the grid without the wall buffer, for diagnoses
        self._loose_fields = {}

    # ---------------------------------------------------------------- nodes

    def index(self, node) -> int:
        x, y, f = (int(v) for v in node)
        return (f * self.R + x) * self.C + y

    def node(self, index: int) -> Tuple[int, int, int]:
        f, rest = divmod(int(index), self.R * self.C)
        x, y = divmod(rest, self.C)
        return (x, y, f)

    def __contains__(self, node) -> bool:
        x, y, f = node
        return 0 <= f < self.F and 0 <= x < self.R and 0 <= y < self.C and bool(self.passable[f, x, y])

    def cell_name(self, node) -> str:
        x, y, f = node
        return NAMES[self.codes[f, x, y]]

    # ---------------------------------------------------------------- graph

    def create_graph(self):
        P = self.passable
        self.planar = self._planar_graph(P)
        self.stair_edges = self._connect_stairs()
        if self.stair_edges:
            sa = np.array([self.index(u) for u, _, _ in self.stair_edges])
            sb = np.array([self.index(v) for _, v, _ in self.stair_edges])
            sw = np.array([w for _, _, w in self.stair_edges])
            stairs = sparse.csr_matrix((np.concatenate([sw, sw]), (np.concatenate([sa, sb]), np.concatenate([sb, sa]))),
                                       shape=(self.N, self.N))
            self.graph = (self.planar + stairs).tocsr()
        else:
            self.graph = self.planar
        self._components = None
        self._planar_labels = None
        self._fields = {}
        self._loose = None
        self._loose_fields = {}
        return self.graph

    def _planar_graph(self, P: np.ndarray):
        """Edges between neighbouring passable cells on each floor (both directions), as a CSR matrix."""
        idx = np.arange(self.N, dtype=np.int64).reshape(self.F, self.R, self.C)
        directions = [(0, 1, 1.0), (1, 0, 1.0)]
        if self.allow_diagonal:
            directions += [(1, 1, math.sqrt(2)), (1, -1, math.sqrt(2))]
        sources, targets, weights = [], [], []
        for dx, dy, base in directions:
            xa, xb = slice(0, self.R - dx), slice(dx, self.R)
            ya, yb = (slice(0, self.C - dy), slice(dy, self.C)) if dy >= 0 else (slice(-dy, self.C), slice(0, self.C + dy))
            both = P[:, xa, ya] & P[:, xb, yb]
            a = idx[:, xa, ya][both]
            b = idx[:, xb, yb][both]
            w = np.full(len(a), base)
            if self.minimize_cost:
                ta = self.codes[:, xa, ya][both]
                tb = self.codes[:, xb, yb][both]
                special = np.isin(ta, (DOOR, STAIR)) | np.isin(tb, (DOOR, STAIR))
                w[(ta != tb) & special] *= 2.5  # entering and leaving a door: 5 instead of 2
            sources.append(a)
            targets.append(b)
            weights.append(w)

        a = np.concatenate(sources)
        b = np.concatenate(targets)
        w = np.concatenate(weights)
        return sparse.csr_matrix((np.concatenate([w, w]), (np.concatenate([a, b]), np.concatenate([b, a]))),
                                 shape=(self.N, self.N))

    def _stair_groups(self):
        """3D groups of stair cells: 4-connected on a floor and joined to the cell straight above or below."""
        if self._stair_labels is None:
            stair = self.codes == STAIR
            self._stair_labels = ndimage.label(stair, ndimage.generate_binary_structure(3, 1))
        return self._stair_labels

    def _connect_stairs(self) -> List[Tuple[Tuple[int, int, int], Tuple[int, int, int], float]]:
        """Edges between the stair cells of two floors, a stair's run apart at 35 to 75 degrees (first angle
        that gives any), at most one new edge per 26 lower cells; otherwise each lower cell to its nearest upper."""
        labels, count = self._stair_groups()
        edges = []
        for group in range(1, count + 1):
            cells = np.argwhere(labels == group)  # (f, x, y), sorted
            floors = sorted(set(cells[:, 0].tolist()))
            for lower_floor, upper_floor in zip(floors, floors[1:]):
                lower = [tuple(c) for c in cells[cells[:, 0] == lower_floor][:, 1:].tolist() if self.passable[lower_floor, c[0], c[1]]]
                upper_cells = cells[cells[:, 0] == upper_floor][:, 1:]
                upper_cells = upper_cells[self.passable[upper_floor, upper_cells[:, 0], upper_cells[:, 1]]]
                if not lower or len(upper_cells) == 0:
                    continue
                upper = set(map(tuple, upper_cells.tolist()))
                height = self.floors[upper_floor]['elevation'] - self.floors[lower_floor]['elevation']

                made = []
                angle = 35
                while angle <= 80 and not made:
                    run = height / math.tan(math.radians(angle)) / self.grid_size
                    offsets = [(int(round(run * math.cos(k * math.pi / 4))), int(round(run * math.sin(k * math.pi / 4))))
                               for k in range(8)]
                    since_last = 25
                    for x, y in lower:
                        since_last += 1
                        if since_last <= 25:
                            continue
                        for dx, dy in offsets:
                            if (x + dx, y + dy) in upper:
                                made.append(((x, y, lower_floor), (x + dx, y + dy, upper_floor)))
                                since_last = 0
                                break
                    if not made:
                        angle += 10
                if not made:
                    logger.info(f"No stair connections between floors {lower_floor} and {upper_floor} at 35-80 degrees, using fallback method")
                    tree = cKDTree(upper_cells)
                    _, nearest = tree.query(np.array(lower))
                    made = [((x, y, lower_floor), (int(upper_cells[j][0]), int(upper_cells[j][1]), upper_floor))
                            for (x, y), j in zip(lower, nearest)]
                for u, v in made:
                    edges.append((u, v, self._stair_weight(u, v, height)))
        return edges

    def _stair_weight(self, u, v, height_diff) -> float:
        """Walked length of a stair edge in grid cells: the 3D length, taking a stair steeper than 45 degrees as 45."""
        horizontal = math.hypot(u[0] - v[0], u[1] - v[1]) * self.grid_size
        horizontal = max(horizontal, abs(height_diff))
        return math.sqrt(height_diff ** 2 + horizontal ** 2) / self.grid_size

    def connected(self, a, b) -> bool:
        if a not in self or b not in self:
            return False
        if self._components is None:
            self._components = connected_components(self.graph, directed=False)[1]
        return self._components[self.index(a)] == self._components[self.index(b)]

    # ------------------------------------------------------------------ exits

    def detect_exits(self, doors: Optional[List[Dict[str, Any]]] = None, evacuation_floors: Optional[List[int]] = None) -> List[Tuple[int, int, int]]:
        """Doors to the open air on the evacuation level.

        A door group leads outside when a door of the IFC data covering it has IsExternal TRUE. When none of its
        doors says (no data, or an old grid file), the geometric test decides: a straight clear line from the door
        to the edge of the grid. Upper floors have no doors to the open air that count (LG 4.4.1.2), so a balcony
        door is never one.

        Doors are found on the original grid (the wall buffer may block part of a door, which would split it or let
        the line test pass through it); the exit cell is the door cell nearest the door's centre that the buffered
        grid leaves open, or its centre cell when the whole door is too narrow."""
        if evacuation_floors is None:
            evacuation_floors = evacuation_levels(self.floors)
        doors_by_floor = defaultdict(list)
        for door in doors or []:
            doors_by_floor[door.get('floor')].append(door)

        exits = []
        for floor_index in evacuation_floors:
            original = self.original_codes[floor_index]
            for door_group in self._group_connected_doors(original):
                flags = [d.get('is_external') for d in doors_by_floor[floor_index] if _door_covers(d, door_group)]
                known = [f for f in flags if f is not None]
                is_exit = any(known) if known else self._is_exit_group(original, door_group)
                if is_exit:
                    open_cells = [p for p in door_group if self.passable[floor_index, p[0], p[1]]]
                    exits.append(self._calculate_average_position(door_group, floor_index, open_cells))
        return exits

    @staticmethod
    def _group_connected_doors(floor: np.ndarray) -> List[List[Tuple[int, int]]]:
        labels, count = ndimage.label(floor == DOOR)
        groups = []
        for k, region in enumerate(ndimage.find_objects(labels), start=1):
            local = np.argwhere(labels[region] == k) + (region[0].start, region[1].start)
            groups.append([tuple(p) for p in local.tolist()])
        return groups

    @staticmethod
    def _is_exit_group(floor: np.ndarray, door_group: List[Tuple[int, int]]) -> bool:
        """A clear straight line (no wall or door) from a cell next to the door to the edge of the grid."""
        rows, cols = floor.shape
        stop = (floor == DOOR) | (floor == 2)  # door or wall
        for x, y in door_group:
            for dx, dy in [(0, 1), (1, 0), (0, -1), (-1, 0)]:
                nx_, ny_ = x + dx, y + dy
                if not (0 <= nx_ < rows and 0 <= ny_ < cols) or stop[nx_, ny_]:
                    continue
                if dx:
                    line = stop[nx_:, ny_] if dx > 0 else stop[:nx_ + 1, ny_][::-1]
                else:
                    line = stop[nx_, ny_:] if dy > 0 else stop[nx_, :ny_ + 1][::-1]
                if not line.any():
                    return True
        return False

    @staticmethod
    def _calculate_average_position(door_group: List[Tuple[int, int]], floor_index: int,
                                    candidates: Optional[List[Tuple[int, int]]] = None) -> Tuple[int, int, int]:
        """The door cell (of candidates, if any) nearest the group's centre, so the exit is a cell of the door."""
        avg_x = sum(x for x, _ in door_group) / len(door_group)
        avg_y = sum(y for _, y in door_group) / len(door_group)
        x, y = min(candidates or door_group, key=lambda p: (p[0] - avg_x) ** 2 + (p[1] - avg_y) ** 2)
        return (int(x), int(y), floor_index)

    def exit_groups(self, exits: List[Tuple[int, int, int]], stairs_as_exits: bool = True,
                    doors: Optional[List[Dict[str, Any]]] = None, spaces: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
        """All exits of LG 4.4.1.2 as groups of cells:
        - each given exit (a door to the open air on the evacuation level, or a goal placed by hand);
        - on floors other than the evacuation level, the stair cells of each stair that reaches an evacuation level
          (LG 4.2.2.2);
        - spaces with FireExit TRUE: a stairwell (holding stair cells) on floors other than the evacuation level, an
          evacuation route (no stair) only on the evacuation level;
        - doors with FireExit TRUE next to such a stair or space, on the floors where those count: the access to the
          stairwell or route itself."""
        groups = []
        seen = set()
        for e in exits:
            node = (int(e[0]), int(e[1]), int(e[2]))
            if node in self and node not in seen:
                seen.add(node)
                groups.append({'kind': 'outside', 'label': f"door {node}", 'nodes': np.array([self.index(node)])})
        evacuation = set(evacuation_levels(self.floors))
        labels, count = self._stair_groups()
        qualifying = np.zeros(self.codes.shape, bool)  # stair cells of stairs that reach an evacuation level
        for group in range(1, count + 1):
            floors = set(np.nonzero((labels == group).any(axis=(1, 2)))[0].tolist())
            if len(floors) < 2 or not floors & evacuation:
                continue
            qualifying |= labels == group
            if stairs_as_exits:
                for f in sorted(floors - evacuation):
                    cells = np.argwhere((labels[f] == group) & self.passable[f])
                    if len(cells):
                        nodes = (f * self.R + cells[:, 0]) * self.C + cells[:, 1]
                        groups.append({'kind': 'stairwell', 'label': f"stair {group}", 'floor': f, 'nodes': nodes})

        exit_space_cells = np.zeros(self.codes.shape, bool)
        for space in spaces or []:
            if not space.get('fire_exit'):
                continue
            f = space['floor']
            pts = np.asarray(space.get('cells') or space['points'], dtype=np.int64).reshape(-1, 2)
            if len(pts) == 0:
                continue
            has_stair = bool(qualifying[f, pts[:, 0], pts[:, 1]].any() or space.get('is_stairway'))
            if (f in evacuation) == has_stair:
                continue  # a stairwell is an exit above or below the evacuation level, an evacuation route on it
            exit_space_cells[f, pts[:, 0], pts[:, 1]] = True
            ok = self.passable[f, pts[:, 0], pts[:, 1]]
            if ok.any():
                nodes = (f * self.R + pts[ok, 0]) * self.C + pts[ok, 1]
                groups.append({'kind': 'stairwell' if has_stair else 'evacuation route', 'label': space.get('name', 'space'),
                               'floor': f, 'nodes': nodes})

        stair_access = qualifying.copy()
        for f in evacuation:
            stair_access[f] = False  # on the evacuation level the way out is a door outside, not the stair
        near = ndimage.binary_dilation(stair_access | exit_space_cells, structure=np.ones((1, 7, 7), bool))
        for door in doors or []:
            if not door.get('fire_exit') or door.get('is_external'):
                continue
            f = door.get('floor')
            x0, x1, y0, y1 = door['cells']
            if f is None or not 0 <= f < self.F or x1 < x0 or y1 < y0:
                continue
            box = (slice(max(x0, 0), x1 + 1), slice(max(y0, 0), y1 + 1))
            cells = np.argwhere((self.codes[f][box] == DOOR) & self.passable[f][box]) + (box[0].start, box[1].start)
            if len(cells) == 0 or not near[f, cells[:, 0], cells[:, 1]].any():
                continue
            nodes = (f * self.R + cells[:, 0]) * self.C + cells[:, 1]
            groups.append({'kind': 'stairwell door', 'label': door.get('name') or 'door', 'floor': f, 'nodes': nodes})
        return groups

    # ---------------------------------------------------------------- routing

    def find_path(self, start: Dict[str, int], goals: List[Dict[str, int]]) -> Tuple[List[Tuple[int, int, int]], Dict[str, float]]:
        """Shortest path (any floors) from start to the nearest goal."""
        start_node = (start['row'], start['col'], start['floor'])
        goal_nodes = [(goal['row'], goal['col'], goal['floor']) for goal in goals]
        if start_node not in self:
            raise ValueError(f"Start node {start_node} is not in the graph. Cell type: {self.cell_name(start_node)}")
        invalid_goals = [node for node in goal_nodes if node not in self]
        if invalid_goals:
            raise ValueError(f"The following goal nodes are not in the graph: {invalid_goals}")

        dist, pred = dijkstra(self.graph, directed=True, indices=[self.index(g) for g in goal_nodes],
                              min_only=True, return_predecessors=True)[:2]
        s = self.index(start_node)
        if not np.isfinite(dist[s]):
            return [], {}
        path = self._follow(pred, s)
        return path, self._calculate_path_lengths(path)

    def _follow(self, pred: np.ndarray, start_index: int) -> List[Tuple[int, int, int]]:
        path = [start_index]
        while pred[path[-1]] >= 0:
            path.append(int(pred[path[-1]]))
        return [self.node(i) for i in path]

    def exit_field(self, groups: List[Dict[str, Any]], with_second: bool = False):
        """Per cell: distance (grid cells, own floor only) to the nearest exit's access, the predecessor towards it
        and that exit's group; with_second also the distance to the nearest other exit (up to
        SECOND_EXIT_SEARCH_LIMIT, inf beyond)."""
        key = (tuple(tuple(g['nodes'][:3].tolist()) + (len(g['nodes']),) for g in groups), with_second)
        if key in self._fields:
            return self._fields[key]
        group_of = np.full(self.N, -1, dtype=np.int64)
        for gi, g in enumerate(groups):
            group_of[g['nodes']] = gi
        all_nodes = np.concatenate([g['nodes'] for g in groups]) if groups else np.empty(0, np.int64)
        if len(all_nodes) == 0:
            field = (np.full(self.N, np.inf), np.full(self.N, -9999), np.full(self.N, -1), None)
            self._fields[key] = field
            return field

        dist, pred, sources = dijkstra(self.planar, directed=True, indices=all_nodes, min_only=True, return_predecessors=True)
        nearest_group = np.where(sources >= 0, group_of[np.maximum(sources, 0)], -1)

        second = None
        if with_second:
            second = np.full(self.N, np.inf)
            limit = SECOND_EXIT_SEARCH_LIMIT / self.grid_size
            for gi, g in enumerate(groups):
                d = dijkstra(self.planar, directed=True, indices=g['nodes'], min_only=True, limit=limit)
                other = nearest_group != gi
                np.minimum(second, np.where(other, d, np.inf), out=second)
        field = (dist, pred, nearest_group, second)
        self._fields[key] = field
        return field

    def calculate_escape_routes(self, spaces: List[Dict[str, Any]], exits: List[Tuple[int, int, int]],
                                stairs_as_exits: bool = True, with_second: bool = True,
                                doors: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
        groups = self.exit_groups(exits, stairs_as_exits, doors, spaces)
        field = self.exit_field(groups, with_second)
        return [self._route_for_space(space, groups, field) for space in spaces]

    def calculate_escape_route(self, space: Dict[str, Any], exits: List[Tuple[int, int, int]], spaces: List[Dict[str, Any]] = None,
                               stairs_as_exits: bool = True, with_second: bool = True) -> Dict[str, Any]:
        return self.calculate_escape_routes([space], exits, stairs_as_exits, with_second)[0]

    def _route_for_space(self, space: Dict[str, Any], groups, field) -> Dict[str, Any]:
        """The route of a space is the route from its point furthest from any exit; every cell is checked."""
        dist, pred, nearest_group, second = field
        floor = space['floor']
        points = np.asarray(space['points'], dtype=np.int64).reshape(-1, 2)
        nodes = (floor * self.R + points[:, 0]) * self.C + points[:, 1]
        in_grid = (points[:, 0] >= 0) & (points[:, 0] < self.R) & (points[:, 1] >= 0) & (points[:, 1] < self.C)
        nodes = nodes[in_grid]
        d = dist[nodes]
        reachable = np.isfinite(d)

        result = {
            'furthest_point': None,
            'optimal_exit': None,
            'optimal_path': None,
            'grid_type': None,
            'distance': None,
            'distance_to_stair': None,
            'exit_kind': None,
            'exits_reachable': 0,
            'second_exit_distance': None,
            'second_exit_beyond': None,
            'second_point': None,     # the point of the space furthest from a second exit
            'second_path': None,      # its (straightened) route to the nearest other exit
            'unreachable_cells': int(len(points) - reachable.sum()),
            'space_name': space['name'],
            'space_polygon': space.get('polygon'),
            'starting_elevation': floor,
        }
        if not reachable.any():
            result['diagnosis'] = self._diagnose(nodes, floor, groups)
            return result

        # Grid steps overstate walked lengths (up to 8 % with diagonals): straighten the routes of the cells
        # furthest by grid distance and keep the longest straightened one.
        # Straightening never lengthens a route, so a cell whose grid distance is below the best straightened length
        # so far cannot win: candidates are taken by grid distance until that point, at most SMOOTHING_CANDIDATES.
        order = np.argsort(d[reachable])[::-1][:SMOOTHING_POOL]
        pool = nodes[reachable][order]
        pool_d = d[reachable][order] * self.grid_size
        chosen = []
        best = None
        for candidate, grid_length in zip(pool, pool_d):
            if best is not None and grid_length <= best[0] + 1e-9:
                break
            cx, cy, _ = self.node(int(candidate))
            if any((cx - x) ** 2 + (cy - y) ** 2 < (1.0 / self.grid_size) ** 2 for x, y in chosen):
                continue
            chosen.append((cx, cy))
            straight = self.smooth_path(self._follow(pred, int(candidate)))
            length = self._calculate_real_distance(straight)
            if best is None or length > best[0]:
                best = (length, int(candidate), straight)
            if len(chosen) >= SMOOTHING_CANDIDATES:
                break
        distance, furthest, path = best
        group = groups[int(nearest_group[furthest])]

        # Distinct exits that can be reached from the space on its floor, and the worst point for a second one.
        result['exits_reachable'] = self._exits_in_component(int(nodes[reachable][0]), groups)
        if second is not None and result['exits_reachable'] >= 2:
            s = second[nodes[reachable]]
            if np.isfinite(s).all():
                worst = int(nodes[reachable][np.argmax(s)])
                route = self._second_route(worst, int(nearest_group[worst]), groups)
                if route:
                    straight = self.smooth_path(route)
                    result.update({'second_exit_distance': self._calculate_real_distance(straight),
                                   'second_point': self.node(worst), 'second_path': straight})
                else:
                    result['second_exit_distance'] = float(s.max() * self.grid_size)
            else:
                result['second_exit_beyond'] = SECOND_EXIT_SEARCH_LIMIT

        result.update({
            'furthest_point': self.node(furthest),
            'optimal_exit': path[-1],
            'optimal_path': path,
            'grid_type': [self.cell_name(p) for p in path],
            'distance': distance,
            'distance_to_stair': distance if group['kind'] == 'stairwell' else -1,
            'exit_kind': group['kind'],
        })
        return result

    def _second_route(self, start: int, nearest_group: int, groups) -> Optional[List[Tuple[int, int, int]]]:
        """Route on its floor from a cell to the nearest exit other than its nearest one (within the search limit)."""
        limit = SECOND_EXIT_SEARCH_LIMIT / self.grid_size
        dist, pred = dijkstra(self.planar, directed=True, indices=start, return_predecessors=True, limit=limit)
        best = None
        for gi, g in enumerate(groups):
            if gi == nearest_group:
                continue
            d = dist[g['nodes']]
            k = int(np.argmin(d))
            if np.isfinite(d[k]) and (best is None or d[k] < best[0]):
                best = (d[k], int(g['nodes'][k]))
        if best is None:
            return None
        path = [best[1]]
        while path[-1] != start and pred[path[-1]] >= 0:
            path.append(int(pred[path[-1]]))
        return [self.node(i) for i in reversed(path)]

    def _visible(self, f: int, a, b) -> bool:
        """A straight walk from cell a to cell b on floor f stays on passable cells, checked along the centre line and
        a quarter cell to each side (so it never slips between two blocked cells touching at a corner)."""
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy)
        if length == 0:
            return True
        steps = int(length * 4) + 1
        t = np.arange(steps + 1) / steps
        nx_, ny_ = -dy / length * 0.25, dx / length * 0.25
        xs = a[0] + 0.5 + dx * t
        ys = a[1] + 0.5 + dy * t
        cx = np.floor(np.concatenate([xs, xs + nx_, xs - nx_])).astype(np.int64)
        cy = np.floor(np.concatenate([ys, ys + ny_, ys - ny_])).astype(np.int64)
        if cx.min() < 0 or cy.min() < 0 or cx.max() >= self.R or cy.max() >= self.C:
            return False
        return bool(self.passable[f][cx, cy].all())

    def smooth_path(self, path: List[Tuple[int, int, int]]) -> List[Tuple[int, int, int]]:
        """String pulling: keep only the turning points, each the furthest point of the path still in a straight line
        of sight (galloping search). Floor changes are kept as they are."""
        if len(path) <= 2:
            return list(path)
        out = [path[0]]
        i = 0
        n = len(path)
        while i < n - 1:
            f = path[i][2]
            last = i + 1
            while last + 1 < n and path[last + 1][2] == f:
                last += 1
            if path[last][2] != f or last == i + 1:
                out.append(path[i + 1])
                i += 1
                continue
            lo, step = i + 1, 1
            while lo + step <= last and self._visible(f, path[i], path[lo + step]):
                lo += step
                step *= 2
            hi = min(lo + step, last + 1)
            while hi - lo > 1:
                mid = (lo + hi) // 2
                if self._visible(f, path[i], path[mid]):
                    lo = mid
                else:
                    hi = mid
            out.append(path[lo])
            i = lo
        return out

    def _diagnose(self, nodes: np.ndarray, floor: int, groups) -> Dict[str, Any]:
        """Why a space has no route: no exit on its floor, exits only reachable through cells the wall buffer closes
        (with the first such cell, the bottleneck), or walled off."""
        on_floor = [g for g in groups if (g['nodes'] // (self.R * self.C) == floor).any()]
        if not on_floor:
            return {'code': 'no_exit_on_floor', 'cell': None}
        loose_passable = np.isin(self.original_codes, PASSABLE)
        if self._loose is None:
            self._loose = self._planar_graph(loose_passable)
        key = tuple(len(g['nodes']) for g in on_floor) + (floor,)
        if key not in self._loose_fields:
            sources = np.concatenate([g['nodes'] for g in on_floor])
            sources = sources[loose_passable.reshape(-1)[sources]]
            self._loose_fields[key] = dijkstra(self._loose, directed=True, indices=sources, min_only=True,
                                               return_predecessors=True)[:2] if len(sources) else None
        field = self._loose_fields[key]
        if field is None:
            return {'code': 'walled_off', 'cell': None}
        dist, pred = field
        reach = nodes[np.isfinite(dist[nodes])]
        if len(reach) == 0:
            return {'code': 'walled_off', 'cell': None}
        path = [int(reach[0])]
        while pred[path[-1]] >= 0:
            path.append(int(pred[path[-1]]))
        blocked = [i for i in path if not self.passable.reshape(-1)[i]]
        return {'code': 'narrow', 'cell': self.node(blocked[0]) if blocked else None}

    def _planar_components(self):
        if self._planar_labels is None:
            self._planar_labels = connected_components(self.planar, directed=False)[1]
        return self._planar_labels

    def _exits_in_component(self, node_index: int, groups) -> int:
        """Exits that can be reached at all from this node on its floor."""
        labels = self._planar_components()
        component = labels[node_index]
        return sum(1 for g in groups if (labels[g['nodes']] == component).any())

    def _calculate_path_lengths(self, path: List[Tuple[int, int, int]]) -> Dict[str, float]:
        total_length = 0
        floor_lengths = defaultdict(float)
        stairway_distance = 0
        found_stair = False

        for i in range(len(path) - 1):
            current_node = path[i]
            next_node = path[i + 1]
            edge_length = self._calculate_real_distance([current_node, next_node])

            if current_node[2] == next_node[2]:  # Same floor
                floor_lengths[f"floor_{current_node[2]}"] += edge_length
                if not found_stair:
                    stairway_distance += edge_length
            else:  # Floor change
                found_stair = True

            if self.codes[current_node[2], current_node[0], current_node[1]] == STAIR:
                found_stair = True

            total_length += edge_length

        return {
            "total_length": total_length,
            "floor_lengths": dict(floor_lengths),
            "stairway_distance": stairway_distance
        }

    def _calculate_real_distance(self, path: List[Tuple[int, int, int]]) -> float:
        if len(path) < 2:
            return 0.0
        p = np.asarray(path, dtype=float)
        elevation = np.array([f['elevation'] for f in self.floors], dtype=float)
        dx = np.diff(p[:, 0]) * self.grid_size
        dy = np.diff(p[:, 1]) * self.grid_size
        dz = np.diff(elevation[p[:, 2].astype(int)])
        return float(np.sqrt(dx ** 2 + dy ** 2 + dz ** 2).sum())


def _door_covers(door: Dict[str, Any], door_group: List[Tuple[int, int]]) -> bool:
    x0, x1, y0, y1 = door['cells']
    return any(x0 <= x <= x1 and y0 <= y <= y1 for x, y in door_group)


def evacuation_levels(floors: List[Dict[str, Any]]) -> List[int]:
    """The floor at the building's ±0.00: the one whose storey elevation (relative to the building when the IFC
    gives it) is nearest 0. Annex 1, 5.6.8: the evacuation level holds the exits to the outside."""
    if not floors:
        return []

    def level(f):
        rel = f.get('relative_elevation')
        return rel if rel is not None else f.get('elevation', 0)
    return [min(range(len(floors)), key=lambda i: (abs(level(floors[i])), i))]


def find_path(grids, grid_size: float, floors: List[Dict[str, float]], bbox: Dict[str, float],
              start: Dict[str, int], goals: List[Dict[str, int]], allow_diagonal: bool = False, minimize_cost: bool = True) -> Tuple[List[Tuple[int, int, int]], Dict[str, float]]:
    pathfinder = Pathfinder(grids, grids, grid_size, floors, bbox, allow_diagonal, minimize_cost)
    pathfinder.create_graph()
    return pathfinder.find_path(start, goals)


def detect_exits(grids, grid_size: float, floors: List[Dict[str, float]], bbox: Dict[str, float],
                 doors: Optional[List[Dict[str, Any]]] = None, original_grids=None) -> List[Tuple[int, int, int]]:
    """grids are the grids routes run on (buffered); original_grids, when given, the unbuffered ones doors are read from."""
    pathfinder = Pathfinder(original_grids if original_grids is not None else grids, grids, grid_size, floors, bbox)
    return pathfinder.detect_exits(doors)


def check_escape_route_rules(route, grid_size, require_second_exit: bool = False, occupancy: Optional[float] = None,
                             use: Optional[str] = None, lang: str = 'en', needed: Optional[int] = None):
    """LG 2.2.1 (number of exits) and LG 4.4.1.1 (distance to the nearest and to a second exit).

    use: 'day' or 'night' checks that use's limits only; unknown checks both. needed overrides the number of exits
    from occupancy (a compartment's). A second exit is checked when two or more exits are needed."""
    violations = {
        'general': [],
        'daytime': [],
        'nighttime': []
    }

    if route.get('distance') is None:
        violations['general'].append(i18n.t(lang, 'no_route'))
        diagnosis = route.get('diagnosis') or {}
        if diagnosis.get('code'):
            violations['general'].append(i18n.t(lang, 'diag_' + diagnosis['code']))
        return violations

    if needed is None:
        needed = required_exits(occupancy)
    needed = max(needed, 2 if require_second_exit else 1)
    reached = route.get('exits_reachable') or 1
    if reached < needed:
        violations['general'].append(i18n.t(lang, 'needs_exits', needed=needed, reached=reached))

    second = route.get('second_exit_distance')
    beyond = route.get('second_exit_beyond')
    times = {'day': ['daytime'], 'night': ['nighttime']}.get(use, ['daytime', 'nighttime'])
    for time_of_day in times:
        limits = MAX_TRAVEL_DISTANCES[time_of_day]
        if route['distance'] > limits['toNearestExit']:
            violations[time_of_day].append(i18n.t(lang, 'nearest_exit', distance=route['distance'], limit=limits['toNearestExit']))
        if needed >= 2 and reached >= 2:
            if second is not None and second > limits['toSecondExit']:
                violations[time_of_day].append(i18n.t(lang, 'second_exit', distance=second, limit=limits['toSecondExit']))
            elif second is None and beyond:
                violations[time_of_day].append(i18n.t(lang, 'second_exit_beyond', beyond=beyond, limit=limits['toSecondExit']))

    return violations
