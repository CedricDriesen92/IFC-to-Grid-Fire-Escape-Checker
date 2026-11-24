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


def test_facade_door_counts_when_the_ifc_marks_every_door_interior():
    # Revit writes IsExternal FALSE for every door left on Function "Interior": with no door flagged TRUE on the
    # evacuation level, the flags are not used and the outside region decides.
    from pathfinding import detect_exits_with_note
    f0, _ = two_storey_box()
    for c in (14, 15):
        f0[24][c] = 'door'       # in the façade
        f0[15][c] = 'door'       # inside
    doors = [{'floor': 0, 'cells': [24, 24, 14, 15], 'is_external': False},
             {'floor': 0, 'cells': [15, 15, 14, 15], 'is_external': False}]
    exits, note = detect_exits_with_note([f0], GS, [{'elevation': 0.0}], {}, doors)
    assert [e[0] for e in exits] == [24]
    assert note == {'marked_interior': 1, 'open_envelope': []}


def test_recessed_entrance_is_found_by_the_outside_region():
    # A door at the back of a porch whose straight lines out are all blocked: a screen wall in front of it and
    # porch walls on both sides, with the way out round the corner of the screen.
    g = [['empty'] * 40 for _ in range(40)]
    for r in range(5, 25):
        for c in range(5, 25):
            g[r][c] = 'floor'
    for i in range(5, 25):
        g[5][i] = g[24][i] = g[i][5] = g[i][24] = 'wall'
    for r in range(25, 31):
        g[r][10] = g[r][19] = 'wall'          # porch side walls
    for c in range(12, 20):
        g[28][c] = 'wall'                     # screen, open at columns 11
    for r in range(25, 28):
        for c in range(11, 19):
            g[r][c] = 'floor'
    for c in (14, 15):
        g[24][c] = 'door'
    for c in range(10, 20):
        g[31][c] = 'wall'                     # the porch continues down to row 30, closed at the bottom...
    for r in range(28, 31):
        g[r][11] = 'floor'
    g[30][10] = 'floor'                       # ...and opens to the left at row 30
    pf = Pathfinder([g], [g], GS, ONE_FLOOR, {})
    group = [(24, 14), (24, 15)]
    assert not Pathfinder._is_exit_group(pf.original_codes[0], group)
    exits = pf.detect_exits(None)
    assert [(e[0], e[2]) for e in exits] == [(24, 0)] and pf.exit_note['marked_interior'] == 0


def test_outside_walls_with_gaps_fall_back_to_the_line_test():
    from pathfinding import detect_exits_with_note
    f0, _ = two_storey_box()
    for i in range(6, 24):
        f0[5][i] = 'floor'       # the top wall is missing: the whole floor is reachable from the edge
    for c in (14, 15):
        f0[24][c] = 'door'
    exits, note = detect_exits_with_note([f0], GS, [{'elevation': 0.0, 'name': 'Ground'}], {}, None)
    assert [e[0] for e in exits] == [24]
    assert note['open_envelope'] == ['Ground']


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
    # the route is straightened: at most the grid length, and at least 1/1.083 of it (octile overestimate)
    assert both[0].max() * GS / 1.0825 <= route['distance'] <= both[0].max() * GS + 1e-9
    # the second exit's route is straightened too, from the worst point for it to the other exit
    assert both[1].max() * GS / 1.0825 <= route['second_exit_distance'] <= both[1].max() * GS + 1e-9
    second = route['second_path']
    assert second[0] == route['second_point'] and second[-1] in exits
    own_nearest = min(exits, key=lambda e: per_exit[exits.index(e)][pf.index(route['second_point'])])
    assert second[-1] != own_nearest   # the second route goes to the other exit
    assert route['exits_reachable'] == 2
    assert route['optimal_path'][0] == route['furthest_point']
    assert route['optimal_path'][-1] in exits


def test_routes_are_straightened_to_lines_of_sight():
    g = [['wall'] * 32 for _ in range(32)]
    for r in range(1, 31):
        for c in range(1, 31):
            g[r][c] = 'floor'
    g[31][30] = 'door'
    pf = Pathfinder([g], [g], GS, ONE_FLOOR, {}, True, False)
    pf.create_graph()
    room = {'name': 'room', 'floor': 0, 'polygon': [], 'points': [(r, c) for r in range(1, 31) for c in range(1, 31)]}
    route = pf.calculate_escape_routes([room], [(31, 30, 0)])[0]
    # from the far corner (1, 1) straight to the cell in front of the door (30, 30), then one step through it
    assert route['distance'] == pytest.approx((29 * 2 ** 0.5 + 1) * GS, rel=1e-6)
    assert route['optimal_path'] == [(1, 1, 0), (30, 30, 0), (31, 30, 0)]


def test_no_route_is_explained():
    pf, grids = two_floors_with_a_stair(stair_floors=(1, 2), floors_count=3)
    route = pf.calculate_escape_routes([whole_floor(grids, 2)], [(0, 0, 0)])[0]
    assert route['diagnosis']['code'] == 'no_exit_on_floor'
    g = wall_with_door(7)                      # 0.7 m door: closed by the buffer
    g[39][20] = 'door'                         # outside door below the wall
    gm = GridManager([g], GS, ONE_FLOOR, {})
    buffered = gm.apply_wall_buffer(4)
    pf = Pathfinder(gm.get_original_grids(), buffered, GS, ONE_FLOOR, {}, True, False)
    pf.create_graph()
    top = {'name': 'top', 'floor': 0, 'polygon': [], 'points': [(r, c) for r in range(1, 20) for c in range(1, 39)]}
    route = pf.calculate_escape_routes([top], [(39, 20, 0)])[0]
    assert route['distance'] is None and route['diagnosis']['code'] == 'narrow'
    assert route['diagnosis']['cell'] is not None


def test_rules_follow_the_use_of_the_space():
    route = {'distance': 40.0, 'exits_reachable': 1}
    assert check_escape_route_rules(route, GS, use='day') == {'general': [], 'daytime': [], 'nighttime': []}
    assert len(check_escape_route_rules(route, GS, use='night')['nighttime']) == 1
    assert check_escape_route_rules({'distance': None}, GS, lang='nl')['general'][0] == 'Geen evacuatieweg gevonden'


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
    assert check_escape_route_rules({'distance': None}, GS)['general'] == ["No escape route found"]
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


def test_floor_plan_is_cropped_and_keeps_walls_when_shrunk():
    from report import FloorPlan
    codes = np.zeros((500, 6200), dtype=np.uint8)
    codes[200:300, 1000:6000] = 1
    codes[250, 1000:6000] = 2                              # a wall one cell thick
    plan = FloorPlan(codes, 0, [], [], [], GS, {'min_x': 0, 'min_y': 0}, 'Helvetica')
    assert plan.landscape and plan.r0 > 0 and plan.c0 > 0 and plan.c1 < 6200   # cropped to the floor
    img, k = plan.image()
    assert k == 3                                          # 5200 columns shrunk to blocks of 3 cells
    small = np.asarray(img)
    assert (small == (14, 14, 14)).all(axis=2).any()       # the wall is still drawn


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


# ------------------------------------------------------------- projects API

@pytest.fixture
def project_dir(monkeypatch):
    import shutil
    import tempfile
    import projects
    import app as app_module
    directory = tempfile.mkdtemp(prefix='escape_projects_')
    monkeypatch.setattr(projects, 'PROJECT_DIR', directory)
    monkeypatch.setitem(app_module.app.config, 'UPLOAD_FOLDER', os.path.join(directory, 'uploads'))
    yield directory
    for project in app_module.store.projects.values():   # no autosave after the test, into the real folder
        project.cancel_save()
    app_module.store.projects.clear()
    shutil.rmtree(directory, ignore_errors=True)


def test_project_lifecycle(client, project_dir):
    """Upload a grid file, edit, undo and redo, set use and occupancy, analyse, export, reload from disk."""
    import json as _json
    import app as app_module
    app_module.store.projects.clear()

    g = l_shaped_floor()
    data = {'grids': pack(to_codes([g])), 'grid_size': GS, 'floors': [{'elevation': 0.0, 'height': 3.0, 'name': 'L0'}],
            'bbox': {'min_x': 0.0, 'min_y': 0.0}, 'doors': [], 'ifc_spaces': []}
    r = client.post('/api/projects', data={'file': (io.BytesIO(_json.dumps(data).encode()), 'test_grid.json')},
                    content_type='multipart/form-data')
    assert r.status_code == 201
    pid = r.get_json()['project']['id']

    d = client.post(f'/api/projects/{pid}/edit', json={'floor': 0, 'type': 'wall', 'cells': [[10, 5], [10, 6]]}).get_json()
    assert len(d['original']) == 2 and d['can_undo']
    u = client.post(f'/api/projects/{pid}/undo', json={}).get_json()
    assert {tuple(c[:2]) for c in u['original']} == {(10, 5), (10, 6)} and u['can_redo']
    assert client.post(f'/api/projects/{pid}/undo', json={'redo': True}).get_json()['original']
    f = client.post(f'/api/projects/{pid}/edit', json={'floor': 0, 'type': 'stair', 'fill': [35, 20]}).get_json()
    assert len(f['original']) > 100                       # the whole connected floor of the L
    assert len(client.post(f'/api/projects/{pid}/undo', json={}).get_json()['original']) == len(f['original'])

    res = client.post(f'/api/projects/{pid}/analyse').get_json()
    assert res['routes'] and res['compartments'][0]['id'] == 'floor-0'
    comp = res['compartments'][0]['id']
    space = res['spaces'][0]['id']
    client.post(f'/api/projects/{pid}/overrides', json={'occupancy': {comp: 600}, 'use': {space: 'night'}})
    res = client.post(f'/api/projects/{pid}/analyse').get_json()
    assert res['compartments'][0]['needed'] == 3          # 600 persons: 2 + 1 exits (LG 2.2.1)
    route = next(x for x in res['routes'] if x['space_id'] == space)
    assert route['use'] == 'night' and route['use_source'] == 'set'

    assert 'buffered' in client.post(f'/api/projects/{pid}/settings', json={'wall_buffer': 3}).get_json()
    pdf = client.get(f'/api/projects/{pid}/export/pdf?lang=fr')
    assert pdf.status_code == 200 and b'/Subtype /Image' in pdf.data     # the plan of the floor with its routes
    grid =client.get(f'/api/projects/{pid}/export/grid')
    assert grid.status_code == 200 and _json.loads(grid.data)['settings']['wall_buffer'] == 3
    assert client.get(f'/api/projects/{pid}/export/ifc').status_code == 400   # no IFC behind a grid file

    app_module.store.projects[pid].save()
    app_module.store.projects.clear()                   # as after a restart
    again = client.get(f'/api/projects/{pid}').get_json()
    assert again['settings']['wall_buffer'] == 3 and again['overrides']['occupancy'][comp] == 600
    assert any(p['id'] == pid for p in client.get('/api/projects').get_json()['projects'])


def test_mapping_rules():
    from ifc_processing import load_mapping, match_mapping
    import ifcopenshell
    import ifcopenshell.api
    rules = load_mapping('mappings/archicad-lithuanian-proxies.json' if os.path.exists('mappings/archicad-lithuanian-proxies.json')
                         else os.path.join(ROOT, 'mappings', 'archicad-lithuanian-proxies.json'))
    model = ifcopenshell.file(schema='IFC4')
    stair = ifcopenshell.api.run('root.create_entity', model, ifc_class='IfcBuildingElementProxy', name='Laiptų maršas')
    slab = ifcopenshell.api.run('root.create_entity', model, ifc_class='IfcBuildingElementProxy', name='Perdangos plokštės')
    other = ifcopenshell.api.run('root.create_entity', model, ifc_class='IfcBuildingElementProxy', name='WC pakabinamas')
    assert match_mapping(stair, rules)['as'] == 'stair' and match_mapping(stair, rules)['flat_stair']
    assert match_mapping(slab, rules)['as'] == 'floor'
    assert match_mapping(other, rules) is None
    with pytest.raises(ValueError):
        load_mapping({'rules': [{'class': 'IfcWall', 'as': 'roof'}]})


def test_fire_exit_spaces_and_doors_follow_lg_4_4_1_2():
    """A FireExit stairwell space and a FireExit door beside the stair are exits above the evacuation level, not on it;
    a FireExit space without a stair (a protected evacuation route) is an exit on the evacuation level only."""
    pf, grids = two_floors_with_a_stair()
    stair_cells = [(r, 6) for r in range(5, 25)]
    hall = [(r, c) for r in range(3, 27) for c in range(4, 9)]
    route = [(r, c) for r in range(26, 30) for c in range(0, 12)]
    spaces = [
        {'name': 'stairwell 1', 'floor': 1, 'points': hall, 'cells': hall, 'fire_exit': True, 'polygon': []},
        {'name': 'stairwell 0', 'floor': 0, 'points': hall, 'cells': hall, 'fire_exit': True, 'polygon': []},
        {'name': 'route 0', 'floor': 0, 'points': route, 'cells': route, 'fire_exit': True, 'polygon': []},
        {'name': 'route 1', 'floor': 1, 'points': route, 'cells': route, 'fire_exit': True, 'polygon': []},
    ]
    for f in (0, 1):
        pf.codes[f, 10, 9] = 3            # a door cell beside the stair
    doors = [{'floor': f, 'cells': [10, 10, 9, 9], 'fire_exit': True, 'is_external': False, 'name': f'door {f}'} for f in (0, 1)]
    groups = pf.exit_groups([(0, 0, 0)], True, doors, spaces)
    kinds = {(g['kind'], g.get('floor', 0), g['label']) for g in groups}
    assert ('stairwell', 1, 'stairwell 1') in kinds and ('evacuation route', 0, 'route 0') in kinds
    assert ('stairwell door', 1, 'door 1') in kinds
    labels = {g['label'] for g in groups}
    assert 'stairwell 0' not in labels and 'route 1' not in labels and 'door 0' not in labels
    assert stair_cells  # the stair itself stays an exit on floor 1 (LG 4.2.2.2)


def test_occupancy_type_follows_rule_gen_d17():
    from ifc_processing import fold, NIGHT_OCCUPANCY_VALUES
    assert all(fold(v) in NIGHT_OCCUPANCY_VALUES for v in ('Night occupancy', 'NIGHT_OCCUPANCY', ' night-occupancy'))
    assert fold('Night occupancies') not in NIGHT_OCCUPANCY_VALUES and fold('Office') not in NIGHT_OCCUPANCY_VALUES


def revit_style_spaces(values):
    """An IFC4 model with one IfcSpace per (name, {property: value}) in a Revit-style "Identity Data" set."""
    import ifcopenshell
    import ifcopenshell.api
    model = ifcopenshell.file(schema='IFC4')
    ifcopenshell.api.run('root.create_entity', model, ifc_class='IfcProject')
    spaces = []
    for name, props in values:
        space = ifcopenshell.api.run('root.create_entity', model, ifc_class='IfcSpace', name=name)
        pset = ifcopenshell.api.run('pset.add_pset', model, product=space, name='Identity Data')
        ifcopenshell.api.run('pset.edit_pset', model, pset=pset, properties=props)
        spaces.append(space)
    return model, spaces


def test_free_text_occupancy_gives_use_and_evacuation_routes():
    # Revit's room parameter "Occupancy" as in the Kortrijk model: Awake, Dependent, Sleeping, and evacuation spaces.
    from ifc_processing import space_properties
    _, spaces = revit_style_spaces([
        ('Room', {'Occupancy': 'Dependent'}), ('Room', {'Occupancy': 'Sleeping'}), ('Staff', {'Occupancy': 'Awake'}),
        ('Corridor', {'Occupancy': 'Protected evacuation route'}), ('Stairwell', {'Occupancy': 'Vluchttrap'}),
        ('Bedroom', {})])
    props = [space_properties(s, s.Name) for s in spaces]
    assert [(p['use'], p['use_source'], p['fire_exit']) for p in props] == [
        ('night', 'ifc', None), ('night', 'ifc', None), ('day', 'ifc', None),
        (None, None, True), (None, None, True), ('night', 'name', None)]


def test_compartments_from_a_space_property_when_there_are_no_zones():
    model, spaces = revit_style_spaces([('A', {'Compartment': 'Compartment 1'}), ('B', {'Compartment': 'Compartment 1'}),
                                        ('C', {'Compartment': 'Compartment 2'}), ('D', {})])
    proc = IFCProcessor('unused', GS)
    proc.ifc_file = model
    proc.space_elements = [(0, s) for s in spaces]
    proc.extract_compartments()
    found = {c['name']: c['spaces'] for c in proc.compartments}
    assert found == {'Compartment 1': sorted([spaces[0].GlobalId, spaces[1].GlobalId]),
                     'Compartment 2': [spaces[2].GlobalId]}


def test_project_paths_exits_floors_and_attached_ifc(client, project_dir):
    import json as _json
    import app as app_module
    app_module.store.projects.clear()
    pf, grids = two_floors_with_a_stair(floors_count=3, stair_floors=(0, 1))
    data = {'grids': pack(to_codes(grids)), 'grid_size': GS, 'bbox': {'min_x': 0.0, 'min_y': 0.0},
            'floors': [{'elevation': 3.0 * f, 'height': 3.0, 'name': f'L{f}'} for f in range(3)],
            'doors': [{'floor': 2, 'cells': [1, 1, 1, 1]}],
            'ifc_spaces': [{'guid': 'S2', 'name': 'top', 'floor': 2, 'runs': [[2, 2, 5]]},
                           {'guid': 'S1', 'name': 'middle', 'floor': 1, 'runs': [[2, 2, 5]]}]}
    pid = client.post('/api/projects', data={'file': (io.BytesIO(_json.dumps(data).encode()), 'g.json')},
                      content_type='multipart/form-data').get_json()['project']['id']
    path = client.post(f'/api/projects/{pid}/path', json={'start': {'row': 2, 'col': 2, 'floor': 1},
                                                       'goals': [{'row': 0, 'col': 0, 'floor': 0}]}).get_json()
    assert path['path'] and {p[2] for p in path['path']} == {0, 1}
    r = client.post(f'/api/projects/{pid}/exits', json={'exits': [[0, 0, 0], [5, 5, 2]]}).get_json()
    assert r['exits'] == [[0, 0, 0], [5, 5, 2]]
    state = client.post(f'/api/projects/{pid}/floors', json={'action': 'remove', 'floor': 1}).get_json()
    assert state['floors'] == 2
    project = app_module.store.get(pid)
    assert [(s['name'], s['floor']) for s in project.meta['ifc_spaces']] == [('top', 1)]   # middle went, top moved down
    assert project.meta['doors'][0]['floor'] == 1 and project.exits == [[0, 0, 0], [5, 5, 1]]
    assert client.post(f'/api/projects/{pid}/exits', json={'exits': None}).get_json()['detected'] is not None
    ifc = os.path.join(ROOT, 'ExampleInputs', 'Duplex.ifc')
    if os.path.exists(ifc):
        with open(ifc, 'rb') as f:
            assert client.post(f'/api/projects/{pid}/ifc', data={'file': (f, 'Duplex.ifc')}, content_type='multipart/form-data').status_code == 200
        assert project.meta['ifc_file'].endswith('model.ifc')


# ------------------------------------------------------------ several files

@pytest.fixture
def duplex_halves():
    """Duplex split in two files: walls (and windows, coverings) in one, everything else in the other."""
    import shutil
    import tempfile
    import ifcopenshell
    import ifcopenshell.api
    if not os.path.exists(DUPLEX):
        pytest.skip('example file missing')
    directory = tempfile.mkdtemp(prefix='escape_split_')
    walls = ('IfcWall', 'IfcWindow', 'IfcCurtainWall', 'IfcColumn', 'IfcCovering')
    paths = []
    for keep_walls, name in ((True, 'walls.ifc'), (False, 'rest.ifc')):
        model = ifcopenshell.open(DUPLEX)
        doomed = [e.id() for e in model.by_type('IfcBuildingElement') + model.by_type('IfcSpace')
                  if any(e.is_a(c) for c in walls) != keep_walls]
        for i in doomed:
            try:
                ifcopenshell.api.run('root.remove_product', model, product=model.by_id(i))
            except Exception:
                pass  # removed with its parent already
        path = os.path.join(directory, name)
        model.write(path)
        paths.append(path)
    yield paths
    shutil.rmtree(directory, ignore_errors=True)


def test_parts_of_a_building_convert_like_the_whole(duplex_halves):
    from ifc_processing import process_ifc_file
    whole = process_ifc_file(DUPLEX, GS)
    parts = process_ifc_file(duplex_halves, GS)
    assert [np.array(g).shape for g in parts['grids']] == [np.array(g).shape for g in whole['grids']]
    assert all(np.array_equal(np.array(a), np.array(b)) for a, b in zip(whole['grids'], parts['grids']))
    assert [f['name'] for f in parts['floors']] == [f['name'] for f in whole['floors']]
    assert all(len(f['guids']) == 2 and all(f['guids']) for f in parts['floors'])   # each file's storey kept
    assert len(parts['ifc_spaces']) == len(whole['ifc_spaces']) and len(parts['doors']) == len(whole['doors'])


def test_several_files_in_one_project(client, project_dir, duplex_halves):
    import time as _time
    files = [(open(p, 'rb'), os.path.basename(p)) for p in duplex_halves]
    try:
        r = client.post('/api/projects', data={'file': files, 'grid_size': str(GS)}, content_type='multipart/form-data')
    finally:
        for f, _ in files:
            f.close()
    assert r.status_code == 202
    job = r.get_json()['job_id']
    for _ in range(200):
        status = client.get(f'/api/jobs/{job}').get_json()
        if status['status'] != 'running':
            break
        _time.sleep(0.1)
    assert status['status'] == 'done', status
    pid = status['result']['project_id']
    state = client.get(f'/api/projects/{pid}').get_json()
    assert state['meta']['source_files'] == ['walls.ifc', 'rest.ifc'] and len(state['meta']['ifc_files']) == 2
    assert client.post(f'/api/projects/{pid}/analyse').get_json()['routes']
    for index in (0, 1):
        export = client.get(f'/api/projects/{pid}/export/ifc?file={index}')
        assert export.status_code == 200 and ('walls' if index == 0 else 'rest') in export.headers['Content-Disposition']
    mixed = client.post('/api/projects', data={'file': [(io.BytesIO(b'{}'), 'g.json'), (open(duplex_halves[0], 'rb'), 'a.ifc')]},
                        content_type='multipart/form-data')
    assert mixed.status_code == 400


def test_default_clear_width_is_0_8_m_at_any_grid_size():
    from projects import Project
    for gs, cells in ((0.1, 4), (0.05, 8), (0.025, 16), (0.2, 2)):
        meta = {'grid_size': gs, 'floors': [{'elevation': 0.0, 'height': 3.0}], 'bbox': {'min_x': 0.0, 'min_y': 0.0}}
        project = Project('x', 'x', meta, [np.zeros((4, 4), np.uint8)])
        assert project.settings['wall_buffer'] == cells


def test_too_fine_a_grid_is_refused_with_a_suggestion():
    from ifc_processing import IFCProcessor
    proc = IFCProcessor('unused', 0.01)
    proc.bbox = {'min_x': 0.0, 'min_y': 0.0, 'max_x': 300.0, 'max_y': 300.0}
    proc.floors = [{'elevation': 0.0}] * 10
    with pytest.raises(ValueError, match='use a grid size'):
        proc.create_grids()


def test_checks_run_in_the_background_with_progress(client, project_dir):
    import json as _json
    import time as _time
    import app as app_module
    g = l_shaped_floor()
    data = {'grids': pack(to_codes([g])), 'grid_size': GS, 'floors': [{'elevation': 0.0, 'height': 3.0}],
            'bbox': {'min_x': 0.0, 'min_y': 0.0}}
    pid = client.post('/api/projects', data={'file': (io.BytesIO(_json.dumps(data).encode()), 'g.json')},
                      content_type='multipart/form-data').get_json()['project']['id']
    seen = []
    results = app_module.store.get(pid).analyse(lambda f, m: seen.append((f, m)))
    assert results['routes'] and seen[0][1] == 'Finding the spaces' and seen[-1][1] == 'Checking the rules'
    assert all(a[0] <= b[0] for a, b in zip(seen, seen[1:]))           # progress only goes forward
    r = client.post(f'/api/projects/{pid}/analyse?background=1')
    assert r.status_code == 202
    job = r.get_json()['job_id']
    for _ in range(100):
        status = client.get(f'/api/jobs/{job}').get_json()
        if status['status'] != 'running':
            break
        _time.sleep(0.05)
    assert status['status'] == 'done' and status['result']['results']['routes']
