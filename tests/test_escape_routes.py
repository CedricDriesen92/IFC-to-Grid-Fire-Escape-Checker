"""Regression tests for the grid, routing, rules and API. Run from the repository root: python -m pytest tests"""
import io
import os
import sys

import numpy as np
import pytest
from scipy.sparse.csgraph import dijkstra

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from grid_management import GridManager  # noqa: E402
from grid_codec import pack, to_codes, to_names  # noqa: E402
from ifc_processing import IFCProcessor, cells_overlapping_triangle, cells_overlapping_triangles  # noqa: E402
from pathfinding import Pathfinder, check_escape_route_rules, detect_exits, evacuation_levels, required_exits  # noqa: E402

GS = 0.1
ONE_FLOOR = [{'elevation': 0.0, 'height': 3.0}]


def wall_with_door(door_cells, size=40):
    g = [['floor'] * size for _ in range(size)]
    for c in range(size):
        g[20][c] = 'wall'
    for r in range(size):
        g[r][0] = g[r][size - 1] = 'wall'
    start = 20 - door_cells // 2
    for c in range(start, start + door_cells):
        g[20][c] = 'door'
    return g


def passable(grid, buffer=4, a_rows=range(5, 15), b_rows=range(25, 35)):
    gm = GridManager([grid], GS, ONE_FLOOR, {})
    buffered = gm.apply_wall_buffer(buffer)
    pf = Pathfinder(gm.get_original_grids(), buffered, GS, ONE_FLOOR, {}, True, False)
    pf.create_graph()
    a = next(((r, c, 0) for r in a_rows for c in range(len(grid[0])) if (r, c, 0) in pf), None)
    b = next(((r, c, 0) for r in b_rows for c in range(len(grid[0])) if (r, c, 0) in pf), None)
    return bool(a and b and pf.connected(a, b))


# ---------------------------------------------------------------- clear width

@pytest.mark.parametrize('cells,expected', [(7, False), (8, True), (9, True)])
def test_door_width_threshold_is_exactly_0_8_m(cells, expected):
    assert passable(wall_with_door(cells)) is expected


@pytest.mark.parametrize('cells,expected', [(7, False), (8, True)])
def test_corridor_width_threshold_is_exactly_0_8_m(cells, expected):
    g = [['wall'] * 40 for _ in range(60)]
    for r in range(1, 59):
        for c in range(10, 10 + cells):
            g[r][c] = 'floor'
    gm = GridManager([g], GS, ONE_FLOOR, {})
    buffered = np.array(gm.apply_wall_buffer(4)[0])
    open_cells = (buffered[30] == 'floor').sum()
    assert bool(open_cells > 0) is expected


# ---------------------------------------------------------- rasterisation

def test_diagonal_wall_face_marks_a_thin_line_not_its_bounding_box():
    proc = IFCProcessor('unused', GS)
    proc.bbox = {'min_x': 0.0, 'min_y': 0.0}
    grid = np.full((20, 20), 'empty', dtype=object)
    proc.mark_cells([[0.0, 0.0, 0.0], [1.95, 1.95, 0.0], [1.95, 1.95, 3.0]], grid, {'elevation': 0.0}, 'wall')
    marked = (grid == 'wall').sum()
    assert 19 <= marked <= 60, marked
    assert grid[19, 0] == 'empty' and grid[0, 19] == 'empty'


def test_batched_scanline_rasterisation_matches_the_single_triangle_test():
    rng = np.random.default_rng(7)
    tris = rng.uniform(-3, 40, (300, 3, 2))
    tris[:80, 2] = tris[:80, 1]                       # segments (vertical faces)
    tris[80:120] = np.round(tris[80:120])             # corners on cell borders
    tris[120:140] = tris[120:140, :1]                 # points
    single = set()
    for t in tris:
        xs, ys = cells_overlapping_triangle(t, (38, 38))
        single |= set(zip(xs.tolist(), ys.tolist()))
    xs, ys = cells_overlapping_triangles(tris, (38, 38))
    assert set(zip(xs.tolist(), ys.tolist())) == single


def test_rotated_door_is_marked_along_its_own_axes():
    """A 1.0 x 0.2 m door turned 30 degrees: its 1.0 x 0.4 m rectangle (0.1 m deeper on both sides), not the
    0.9 m2 axis-aligned box around it."""
    from ifc_processing import door_rectangle
    angle = np.radians(30)
    u = np.array([np.cos(angle), np.sin(angle)])
    v = np.array([-u[1], u[0]])
    corners = np.array([a * u + b * v for a in (0, 1.0) for b in (0, 0.2)]) + [2.0, 2.0]
    verts = np.hstack([np.vstack([corners, corners]), np.repeat([[0.0], [2.0]], 4, axis=0)])
    rect = door_rectangle(verts[:, :2], 0.1)
    assert np.linalg.norm(rect[1] - rect[0]) == pytest.approx(1.0)
    assert np.linalg.norm(rect[3] - rect[0]) == pytest.approx(0.4)

    proc = IFCProcessor('unused', GS)
    proc.bbox = {'min_x': 0.0, 'min_y': 0.0}
    proc.grids = [np.full((50, 50), 'wall', dtype=object)]
    proc.mark_door(0, verts)
    marked = int((proc.grids[0] == 'door').sum())
    assert 40 <= marked <= 75, marked   # 0.4 m2 is 40 cells; the axis-aligned box would be about 90


def test_packed_grids_round_trip():
    names = [[['empty', 'floor', 'wall'], ['door', 'stair', 'walla']]]
    codes = to_codes(names)
    assert pack(codes) == [['efw', 'dsa']]
    assert to_names(to_codes(pack(codes))) == names


def test_triangle_cells_match_area_for_a_filled_triangle():
    xs, ys = cells_overlapping_triangle(np.array([[0.0, 0.0], [10.0, 0.0], [0.0, 10.0]]), (20, 20))
    assert 50 <= len(xs) <= 70  # area 50 plus the cells along the hypotenuse
    assert all(x + y <= 10 for x, y in zip(xs, ys))


# ------------------------------------------------------------------ exits

def two_storey_box():
    def floor():
        g = [['empty'] * 30 for _ in range(30)]
        for r in range(5, 25):
            for c in range(5, 25):
                g[r][c] = 'floor'
        for i in range(5, 25):
            g[5][i] = g[24][i] = g[i][5] = g[i][24] = 'wall'
        return g
    return floor(), floor()


def test_upper_floor_outside_door_is_not_an_exit():
    f0, f1 = two_storey_box()
    for c in (14, 15):
        f1[5][c] = 'door'
        f0[24][c] = 'door'
    exits = detect_exits([f0, f1], GS, [{'elevation': 0.0}, {'elevation': 3.0}], {})
    assert exits == [(24, 14, 0)] or exits == [(24, 15, 0)]


def test_door_data_decides_over_geometry():
    f0, _ = two_storey_box()
    for c in (14, 15):
        f0[24][c] = 'door'       # geometrically leads out
        f0[15][c] = 'door'       # an inside door
    doors = [{'floor': 0, 'cells': [24, 24, 14, 15], 'is_external': False},
             {'floor': 0, 'cells': [15, 15, 14, 15], 'is_external': True}]
    exits = detect_exits([f0], GS, [{'elevation': 0.0}], {}, doors)
    assert [e[0] for e in exits] == [15]


def test_evacuation_level_uses_the_relative_elevation_of_georeferenced_storeys():
    floors = [{'elevation': 194.95, 'relative_elevation': -3.55},
              {'elevation': 198.5, 'relative_elevation': 0.0},
              {'elevation': 203.0, 'relative_elevation': 4.5}]
    assert evacuation_levels(floors) == [1]
    assert evacuation_levels([{'elevation': -2.9}, {'elevation': 0.0}, {'elevation': 3.1}]) == [1]


# ---------------------------------------------------------------- routing

def l_shaped_floor():
    g = [['wall'] * 40 for _ in range(40)]
    for r in range(1, 39):
        for c in range(1, 10):
            g[r][c] = 'floor'
    for r in range(30, 39):
        for c in range(1, 39):
            g[r][c] = 'floor'
    g[38][38] = 'door'
    g[39][38] = 'door'
    return g


def test_furthest_point_is_exact_and_second_exit_matches_brute_force():
    g = l_shaped_floor()
    g[0][5] = 'door'  # a second exit at the far end of the L
    pf = Pathfinder([g], [g], GS, ONE_FLOOR, {}, True, False)
    pf.create_graph()
    exits = [(39, 38, 0), (0, 5, 0)]
    points = [(r, c) for r in range(40) for c in range(40) if g[r][c] == 'floor']
    space = {'name': 'L', 'floor': 0, 'points': points, 'polygon': [], 'is_stairway': False}
    route = pf.calculate_escape_routes([space], exits)[0]

    per_exit = [dijkstra(pf.graph, indices=pf.index(e)) for e in exits]
    idx = [pf.index((r, c, 0)) for r, c in points]
    both = np.sort(np.stack([d[idx] for d in per_exit]), axis=0)
    assert route['distance'] == pytest.approx(both[0].max() * GS, rel=1e-6)
    assert route['second_exit_distance'] == pytest.approx(both[1].max() * GS, rel=1e-6)
    assert route['exits_reachable'] == 2
    assert route['optimal_path'][0] == route['furthest_point']
    assert route['optimal_path'][-1] in exits


def test_stair_edge_costs_its_3d_length():
    rows, cols = 60, 12
    f0 = [['floor'] * cols for _ in range(rows)]
    f1 = [['floor'] * cols for _ in range(rows)]
    for r in range(10, 50):
        for c in range(4, 8):
            f0[r][c] = f1[r][c] = 'stair'
    floors = [{'elevation': 0.0, 'height': 3.0}, {'elevation': 3.0, 'height': 3.0}]
    pf = Pathfinder([f0, f1], [f0, f1], GS, floors, {}, False, False)
    pf.create_graph()
    assert pf.stair_edges
    for u, v, w in pf.stair_edges:
        horizontal = ((u[0] - v[0]) ** 2 + (u[1] - v[1]) ** 2) ** 0.5 * GS
        assert w * GS == pytest.approx((max(horizontal, 3.0) ** 2 + 9.0) ** 0.5, rel=1e-6)


def two_floors_with_a_stair(stair_floors=(0, 1), floors_count=2):
    rows, cols = 30, 12
    grids = [[['floor'] * cols for _ in range(rows)] for _ in range(floors_count)]
    for f in stair_floors:
        for r in range(5, 25):
            grids[f][r][6] = 'stair'
    grids[0][0][0] = 'door'
    floors = [{'elevation': 3.0 * f, 'height': 3.0} for f in range(floors_count)]
    pf = Pathfinder(grids, grids, GS, floors, {}, True, False)
    pf.create_graph()
    return pf, grids


def whole_floor(grids, f):
    return {'name': f'floor {f}', 'floor': f, 'polygon': [], 'is_stairway': False,
            'points': [(r, c) for r in range(len(grids[f])) for c in range(len(grids[f][0])) if grids[f][r][c] == 'floor']}


def test_upper_floor_is_measured_to_the_stairwell_not_the_front_door():
    """LG 4.4.1.2: on a floor other than the evacuation level the exit is the stairwell."""
    pf, grids = two_floors_with_a_stair()
    upper, ground = pf.calculate_escape_routes([whole_floor(grids, 1), whole_floor(grids, 0)], [(0, 0, 0)])
    assert upper['exit_kind'] == 'stairwell' and ground['exit_kind'] == 'outside'
    assert all(p[2] == 1 for p in upper['optimal_path'])                       # never leaves its floor
    assert pf.cell_name(upper['optimal_path'][-1]) == 'stair'
    assert upper['distance'] < ground['distance'] + 1                          # not the stair plus the ground floor
    assert upper['distance_to_stair'] == pytest.approx(upper['distance'])


def test_a_stair_that_does_not_reach_the_evacuation_level_is_no_exit():
    pf, grids = two_floors_with_a_stair(stair_floors=(1, 2), floors_count=3)
    route = pf.calculate_escape_routes([whole_floor(grids, 2)], [(0, 0, 0)])[0]
    assert route['distance'] is None


# ------------------------------------------------------------------ rules

def test_required_exits_follow_lg_2_2_1():
    assert [required_exits(n) for n in (None, 99, 100, 499, 500, 999, 1000, 2500)] == [1, 1, 2, 2, 3, 3, 4, 5]


def test_rules():
    assert check_escape_route_rules({'distance': None}, GS)['general'] == ["No escape route found!"]
    assert check_escape_route_rules({'distance': 0.0, 'exits_reachable': 1}, GS)['general'] == []
    route = {'distance': 40.0, 'exits_reachable': 2, 'second_exit_distance': 70.0}
    v = check_escape_route_rules(route, GS, True)
    assert v['daytime'] == [] and len(v['nighttime']) == 2                    # 40 > 30 and 70 > 60 at night
    v = check_escape_route_rules(route, GS, occupancy=150)                    # 150 persons need two exits
    assert len(v['nighttime']) == 2
    v = check_escape_route_rules({'distance': 10.0, 'exits_reachable': 1}, GS, occupancy=150)
    assert v['general'] == ["Needs 2 exits (LG 2.2.1), can reach 1"]
    v = check_escape_route_rules({'distance': 10.0, 'exits_reachable': 2, 'second_exit_beyond': 100.0}, GS, True)
    assert len(v['daytime']) == 1 and len(v['nighttime']) == 1
    v = check_escape_route_rules({'distance': 10.0, 'exits_reachable': 1, 'second_exit_distance': None}, GS, False)
    assert v == {'general': [], 'daytime': [], 'nighttime': []}


# -------------------------------------------------------------------- API

@pytest.fixture
def client():
    import app as app_module
    app_module.graphs = None
    return app_module.app.test_client()


def test_api_errors_are_reported(client):
    r = client.post('/api/calculate-escape-routes', json={'spaces': [], 'exits': []})
    assert r.status_code == 400
    r = client.post('/api/process-file', data={'file': (io.BytesIO(b'not an ifc'), 'test_broken_upload.ifc')},
                    content_type='multipart/form-data')
    try:
        assert r.status_code == 500 and 'error' in r.get_json()
    finally:
        path = os.path.join(ROOT, 'uploads', 'test_broken_upload.ifc')
        if os.path.exists(path):
            os.remove(path)


def test_api_routes_and_report(client):
    g = l_shaped_floor()
    body = {'original_grids': [g], 'buffered_grids': [g], 'grid_size': GS, 'floors': [{'elevation': 0.0, 'name': 'L0'}],
            'bbox': {'min_x': 0, 'min_y': 0}, 'allow_diagonal': True, 'minimize_cost': False}
    assert client.post('/api/create-graph', json=body).status_code == 200
    points = [(r, c) for r in range(40) for c in range(40) if g[r][c] == 'floor']
    space = {'name': 'Space 0_1', 'floor': 0, 'points': points, 'polygon': [], 'is_stairway': False}
    r = client.post('/api/calculate-escape-routes', json={'spaces': [space], 'exits': [[39, 38, 0]]})
    assert r.status_code == 200
    routes = r.get_json()['escape_routes']
    assert routes[0]['distance'] > 0 and 'violations' in routes[0]
    r = client.post('/api/generate-pdf-report', json={'escape_routes': routes, 'grid_size': GS,
                                                      'floors': [{'name': 'L0 & <ground>'}], 'filename': '015.10_Kortrijk.ifc'})
    assert r.status_code == 200
    assert '015.10_Kortrijk_report.pdf' in r.headers['Content-Disposition']
    packed = client.post('/api/apply-wall-buffer', json={'grids': pack(to_codes([g])), 'packed': True, 'wall_buffer': 4,
                                                         'grid_size': GS, 'floors': [{'elevation': 0.0}], 'bbox': {}})
    assert packed.status_code == 200 and isinstance(packed.get_json()['buffered_grids'][0][0], str)


# ------------------------------------------------------- IFC (example files)

DUPLEX = os.path.join(ROOT, 'ExampleInputs', 'Duplex.ifc')


@pytest.mark.skipif(not os.path.exists(DUPLEX), reason='example file missing')
def test_duplex_converts_with_closed_rooms():
    from ifc_processing import process_ifc_file
    result = process_ifc_file(DUPLEX, GS)
    assert 'skipped_elements' not in result['warnings']
    assert result['warnings'].get('spaces_on_no_floor') == ['R301 Roof']  # the roof space stands on no floor
    assert [f['name'] for f in result['floors']] == ['Level 1', 'Level 2']
    gm = GridManager(result['grids'], GS, result['floors'], result['bbox'])
    buffered = gm.apply_wall_buffer(4)
    spaces = GridManager(buffered, GS, result['floors'], result['bbox']).detect_spaces(False)
    assert len(spaces) >= 10  # rooms stay separate (4 spaces when walls were dropped)
    assert len(result['ifc_spaces']) == 20
    ifc = GridManager(buffered, GS, result['floors'], result['bbox']).detect_spaces(False, result['ifc_spaces'])
    rooms = [sp for sp in ifc if sp['source'] == 'ifc']
    assert len(rooms) == 20 and all(sp['points'] for sp in rooms)
    assert any(sp['name'].endswith('Kitchen') for sp in ifc)
    exits = detect_exits(buffered, GS, result['floors'], result['bbox'], result['doors'])
    assert exits and all(e[2] == 0 for e in exits)


def test_door_inside_a_curtain_wall_stays_a_door():
    import ifcopenshell
    import ifcopenshell.api
    model = ifcopenshell.file(schema='IFC4')
    ifcopenshell.api.run('root.create_entity', model, ifc_class='IfcProject')
    wall = ifcopenshell.api.run('root.create_entity', model, ifc_class='IfcCurtainWall')
    door = ifcopenshell.api.run('root.create_entity', model, ifc_class='IfcDoor')
    panel = ifcopenshell.api.run('root.create_entity', model, ifc_class='IfcPlate')
    ifcopenshell.api.run('aggregate.assign_object', model, relating_object=wall, products=[door, panel])
    proc = IFCProcessor('unused', GS)
    proc.ifc_file = model
    proc.collect_targets()
    types = {e.is_a(): t for e, t in proc.targets.values()}
    assert types == {'IfcCurtainWall': 'wall', 'IfcDoor': 'door', 'IfcPlate': 'wall'}


def test_buffered_inside_door_is_not_an_exit_and_exit_cell_is_open():
    # A closed box (walls all round, empty outside) split by an inside wall with a 0.9 m door,
    # and a 0.9 m outside door in the bottom wall.
    g = [['empty'] * 40 for _ in range(44)]
    for r in range(1, 42):
        for c in range(1, 39):
            g[r][c] = 'floor'
    for c in range(1, 39):
        g[1][c] = g[41][c] = g[20][c] = 'wall'
    for r in range(1, 42):
        g[r][1] = g[r][38] = 'wall'
    for c in range(15, 24):
        g[20][c] = 'door'
        g[41][c] = 'door'
    gm = GridManager([g], GS, ONE_FLOOR, {})
    buffered = gm.apply_wall_buffer(4)
    exits = detect_exits(buffered, GS, ONE_FLOOR, {}, None, gm.get_original_grids())
    assert len(exits) == 1 and exits[0][0] == 41
    assert buffered[0][exits[0][0]][exits[0][1]] == 'door'
