"""Projects kept on the server: the grids of one model with its settings, edits (undo/redo), analysis results and
background conversion jobs. Each project is saved under uploads/projects/<id>/ and reloaded on demand."""
import json
import os
import shutil
import threading
import time
import traceback
import uuid
from typing import Any, Dict, List, Optional

import numpy as np

import i18n
from grid_codec import CODES, NAMES, to_codes, pack
from grid_management import GridManager, buffer_floor
from pathfinding import Pathfinder, check_escape_route_rules, detect_exits, required_exits

PROJECT_DIR = os.path.join('uploads', 'projects')
UNDO_LIMIT = 200
SAVE_DELAY = 2.0  # seconds after the last change

DEFAULT_SETTINGS = {
    'wall_buffer': 4,            # cells; the clear width is 2 * wall_buffer cells
    'allow_diagonal': True,
    'minimize_cost': False,
    'space_source': 'ifc',       # 'ifc' (IfcSpaces, detected where none) or 'detected'
    'include_empty': False,
    'occupancy': None,           # default occupancy of a compartment without its own (persons)
    'require_second_exit': False,
    'stairs_as_exits': True,
    'language': 'en',
}


def _now() -> float:
    return time.time()


class Project:
    def __init__(self, pid: str, name: str, meta: Dict[str, Any], codes: List[np.ndarray],
                 settings: Optional[Dict[str, Any]] = None, overrides: Optional[Dict[str, Any]] = None,
                 exits: Optional[List[List[int]]] = None, created: Optional[float] = None):
        self.id = pid
        self.root = PROJECT_DIR      # where this project is saved, fixed when it is created or loaded
        self.name = name
        self.meta = meta
        self.codes = [np.ascontiguousarray(c, dtype=np.uint8) for c in codes]
        self.settings = {**DEFAULT_SETTINGS, **(settings or {})}
        self.overrides = {'use': {}, 'occupancy': {}, **(overrides or {})}
        self.exits = exits            # None: detected; else exits placed by hand
        self.created = created or _now()
        self.updated = self.created
        self.undo: List[Dict[str, Any]] = []
        self.redo: List[Dict[str, Any]] = []
        self.lock = threading.RLock()
        self.results: Optional[Dict[str, Any]] = None
        self._pathfinder: Optional[Pathfinder] = None
        self._save_timer: Optional[threading.Timer] = None
        self.buffered = [buffer_floor(c, self.settings['wall_buffer']) for c in self.codes]

    # ------------------------------------------------------------------ state

    @property
    def directory(self) -> str:
        return os.path.join(self.root, self.id)

    def cancel_save(self) -> None:
        if self._save_timer is not None:
            self._save_timer.cancel()

    def summary(self) -> Dict[str, Any]:
        return {'id': self.id, 'name': self.name, 'floors': len(self.codes), 'created': self.created,
                'updated': self.updated, 'source': self.meta.get('source_file')}

    def state(self) -> Dict[str, Any]:
        """Everything the app needs to show and edit the project."""
        with self.lock:
            meta = {k: v for k, v in self.meta.items() if k not in ('ifc_spaces',)}
            return {
                **self.summary(),
                'meta': meta,
                'ifc_space_count': len(self.meta.get('ifc_spaces') or []),
                'settings': self.settings,
                'overrides': self.overrides,
                'exits': self.exits,
                'original': pack(self.codes),
                'buffered': pack(self.buffered),
                'can_undo': bool(self.undo),
                'can_redo': bool(self.redo),
                'results': self.results,
            }

    def _changed(self, analysis_stale: bool = True) -> None:
        self.updated = _now()
        self._pathfinder = None
        if analysis_stale and self.results is not None:
            self.results['stale'] = True
        self.save_soon()

    # ------------------------------------------------------------------ edits

    def edit(self, floor: int, cells: List[List[int]], cell_type: str) -> Dict[str, Any]:
        """Set cells of one floor to a type; returns the cells that changed in the original and buffered grids."""
        with self.lock:
            grid = self.codes[floor]
            cells = np.asarray(cells, dtype=np.int64).reshape(-1, 2)
            inside = (cells[:, 0] >= 0) & (cells[:, 0] < grid.shape[0]) & (cells[:, 1] >= 0) & (cells[:, 1] < grid.shape[1])
            cells = np.unique(cells[inside], axis=0)
            code = CODES[cell_type]
            old = grid[cells[:, 0], cells[:, 1]] if len(cells) else np.empty(0, np.uint8)
            changed = old != code
            cells, old = cells[changed], old[changed]
            if len(cells) == 0:
                return self._diff(floor, cells, None)
            grid[cells[:, 0], cells[:, 1]] = code
            self.undo.append({'floor': floor, 'cells': cells, 'old': old, 'new': np.full(len(cells), code, np.uint8)})
            del self.undo[:-UNDO_LIMIT]
            self.redo.clear()
            diff = self._rebuffer(floor, cells)
            self._changed()
            return diff

    def fill(self, floor: int, row: int, col: int, cell_type: str) -> Dict[str, Any]:
        """Flood fill (4-connected) from a cell with a type."""
        from scipy import ndimage
        with self.lock:
            grid = self.codes[floor]
            if not (0 <= row < grid.shape[0] and 0 <= col < grid.shape[1]):
                return self._diff(floor, np.empty((0, 2), np.int64), None)
            labels, _ = ndimage.label(grid == grid[row, col])
            cells = np.argwhere(labels == labels[row, col])
            return self.edit(floor, cells.tolist(), cell_type)

    def undo_last(self, redo: bool = False) -> Optional[Dict[str, Any]]:
        with self.lock:
            source, target = (self.redo, self.undo) if redo else (self.undo, self.redo)
            if not source:
                return None
            step = source.pop()
            values = step['new'] if redo else step['old']
            grid = self.codes[step['floor']]
            grid[step['cells'][:, 0], step['cells'][:, 1]] = values
            target.append(step)
            diff = self._rebuffer(step['floor'], step['cells'])
            self._changed()
            return diff

    def _rebuffer(self, floor: int, cells: np.ndarray) -> Dict[str, Any]:
        before = self.buffered[floor]
        after = buffer_floor(self.codes[floor], self.settings['wall_buffer'])
        self.buffered[floor] = after
        return self._diff(floor, cells, np.argwhere(after != before))

    def _diff(self, floor: int, cells: np.ndarray, buffered_cells: Optional[np.ndarray]) -> Dict[str, Any]:
        grid = self.codes[floor]
        buffered = self.buffered[floor]
        out = {'floor': floor,
               'original': [[int(r), int(c), int(grid[r, c])] for r, c in cells],
               'buffered': [] if buffered_cells is None else [[int(r), int(c), int(buffered[r, c])] for r, c in buffered_cells],
               'can_undo': bool(self.undo), 'can_redo': bool(self.redo)}
        return out

    def floors_action(self, action: str, floor: int) -> None:
        with self.lock:
            if action == 'add':
                self.codes.append(np.zeros_like(self.codes[0]))
                last = self.meta['floors'][-1]
                self.meta['floors'].append({'elevation': last['elevation'] + last.get('height', 3.0),
                                            'height': last.get('height', 3.0), 'name': f"Level {len(self.codes) - 1}"})
            elif action == 'remove':
                if not 0 < floor < len(self.codes):
                    raise ValueError("Cannot remove this floor")
                del self.codes[floor]
                del self.meta['floors'][floor]
                # rooms, doors and exits of the removed floor go; those above move down one floor
                def shifted(items, key):
                    return [{**i, key: i[key] - 1 if i[key] > floor else i[key]} for i in items or [] if i.get(key) != floor]
                self.meta['ifc_spaces'] = shifted(self.meta.get('ifc_spaces'), 'floor')
                self.meta['doors'] = shifted(self.meta.get('doors'), 'floor')
                if self.exits is not None:
                    self.exits = [[r, c, f - 1 if f > floor else f] for r, c, f in self.exits if f != floor]
            elif action == 'clear':
                self.codes[floor].fill(0)
            else:
                raise ValueError(f"Unknown floor action {action}")
            self.undo.clear()
            self.redo.clear()
            self.buffered = [buffer_floor(c, self.settings['wall_buffer']) for c in self.codes]
            self._changed()

    def update_settings(self, changes: Dict[str, Any]) -> bool:
        """Returns True when the buffered grids changed (the app reloads them)."""
        with self.lock:
            rebuffer = 'wall_buffer' in changes and int(changes['wall_buffer']) != self.settings['wall_buffer']
            for key, value in changes.items():
                if key in DEFAULT_SETTINGS:
                    self.settings[key] = value
            if rebuffer:
                self.settings['wall_buffer'] = int(self.settings['wall_buffer'])
                self.buffered = [buffer_floor(c, self.settings['wall_buffer']) for c in self.codes]
            self._changed()
            return rebuffer

    def update_overrides(self, use: Optional[Dict[str, Any]] = None, occupancy: Optional[Dict[str, Any]] = None) -> None:
        with self.lock:
            for key, value in (use or {}).items():
                if value in ('day', 'night'):
                    self.overrides['use'][key] = value
                else:
                    self.overrides['use'].pop(key, None)
            for key, value in (occupancy or {}).items():
                if value in (None, ''):
                    self.overrides['occupancy'].pop(key, None)
                else:
                    self.overrides['occupancy'][key] = float(value)
            self.updated = _now()
            if self.results is not None:
                self.results['stale'] = True
            self.save_soon()

    def set_exits(self, exits: Optional[List[List[int]]]) -> None:
        with self.lock:
            self.exits = [list(map(int, e)) for e in exits] if exits is not None else None
            self._changed()

    # --------------------------------------------------------------- analysis

    def pathfinder(self) -> Pathfinder:
        if self._pathfinder is None:
            m = self.meta
            pf = Pathfinder(self.codes, self.buffered, m['grid_size'], m['floors'], m['bbox'],
                            bool(self.settings['allow_diagonal']), bool(self.settings['minimize_cost']))
            pf.create_graph()
            self._pathfinder = pf
        return self._pathfinder

    def spaces(self) -> List[Dict[str, Any]]:
        m = self.meta
        gm = GridManager(self.buffered, m['grid_size'], m['floors'], m['bbox'])
        return gm.detect_spaces(bool(self.settings['include_empty']), m.get('ifc_spaces'), self.settings['space_source'])

    def detected_exits(self) -> List[List[int]]:
        m = self.meta
        return [list(e) for e in detect_exits(self.buffered, m['grid_size'], m['floors'], m['bbox'], m.get('doors'), self.codes)]

    def compartments(self, spaces: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Fire compartments: those of the IFC (IfcSpatialZone / IfcZone), else one per floor (LG 2.1: a compartment
        is one storey high). Occupancy: set in the app, else the zone's, else the sum of its spaces', else the
        project default."""
        floors = self.meta['floors']
        zones = self.meta.get('compartments') or []
        of_space = {}
        comps: Dict[str, Dict[str, Any]] = {}
        for z in zones:
            comps[z['id']] = {'id': z['id'], 'name': z['name'], 'zone_occupancy': z.get('occupancy'), 'spaces': []}
            for guid in z['spaces']:
                of_space[guid] = z['id']
        for s in spaces:
            cid = of_space.get(s.get('guid'))
            if cid is None:
                cid = f"floor-{s['floor']}"
                if cid not in comps:
                    comps[cid] = {'id': cid, 'name': f"{floors[s['floor']].get('name') or s['floor']}", 'zone_occupancy': None, 'spaces': []}
            comps[cid]['spaces'].append(s)
            s['compartment'] = cid
        default = self.settings.get('occupancy')
        out = {}
        for cid, c in comps.items():
            space_occ = [s.get('occupancy') for s in c['spaces'] if s.get('occupancy') is not None]
            if cid in self.overrides['occupancy']:
                occ, source = self.overrides['occupancy'][cid], 'set'
            elif c['zone_occupancy'] is not None:
                occ, source = float(c['zone_occupancy']), 'ifc zone'
            elif space_occ:
                occ, source = float(sum(space_occ)), 'ifc spaces'
            elif default not in (None, ''):
                occ, source = float(default), 'default'
            else:
                occ, source = None, None
            area = sum(s.get('area') or 0 for s in c['spaces'])
            needed = max(required_exits(occ), 2 if self.settings['require_second_exit'] else 1)
            out[cid] = {'id': cid, 'name': c['name'], 'occupancy': occ, 'occupancy_source': source, 'needed': needed,
                        'area': area, 'estimate_s10': int(np.ceil(area / 10)) if area else None,
                        'spaces': [s['id'] for s in c['spaces']]}
        return out

    def analyse(self) -> Dict[str, Any]:
        with self.lock:
            t0 = time.time()
            lang = self.settings.get('language', 'en')
            spaces = self.spaces()
            comps = self.compartments(spaces)
            exits = self.exits if self.exits is not None else self.detected_exits()
            pf = self.pathfinder()
            with_second = any(c['needed'] >= 2 for c in comps.values())
            routes = pf.calculate_escape_routes(spaces, exits, bool(self.settings['stairs_as_exits']), with_second,
                                                self.meta.get('doors'))
            for space, route in zip(spaces, routes):
                use = self.overrides['use'].get(space['id']) or space.get('use')
                source = 'set' if space['id'] in self.overrides['use'] else space.get('use_source')
                comp = comps[space['compartment']]
                route.update({'space_id': space['id'], 'use': use, 'use_source': source, 'compartment': comp['id'],
                              'floor': space['floor'], 'area': space.get('area'), 'needed': comp['needed']})
                route['violations'] = check_escape_route_rules(route, pf.grid_size, False, None, use, lang, comp['needed'])
            exit_cells = [{'cell': list(map(int, e)), 'kind': 'outside'} for e in exits]
            self.results = {
                'spaces': [{k: v for k, v in s.items() if k not in ('points', 'cells')} for s in spaces],
                'routes': routes,
                'exits': exit_cells,
                'exits_detected': self.exits is None,
                'compartments': list(comps.values()),
                'not_checked': i18n.not_checked(lang),
                'language': lang,
                'seconds': round(time.time() - t0, 2),
                'stale': False,
            }
            return self.results

    def routes_in(self, lang: str) -> List[Dict[str, Any]]:
        """The last results' routes with their messages in another language (no new analysis)."""
        results = self.results or self.analyse()
        if lang == results.get('language'):
            return results['routes']
        gs = self.meta['grid_size']
        return [{**r, 'violations': check_escape_route_rules(r, gs, False, None, r.get('use'), lang, r.get('needed'))}
                for r in results['routes']]

    def find_path(self, start: Dict[str, int], goals: List[Dict[str, int]]) -> Dict[str, Any]:
        with self.lock:
            pf = self.pathfinder()
            path, lengths = pf.find_path(start, goals)
            return {'path': path, 'path_lengths': lengths}

    def attach_ifc(self, path: str) -> None:
        """The IFC to add the routes to, for a project loaded from a grid file."""
        with self.lock:
            os.makedirs(self.directory, exist_ok=True)
            target = os.path.join(self.directory, 'model.ifc')
            shutil.copyfile(path, target)
            self.meta['ifc_file'] = target
            self.save()

    # ---------------------------------------------------------------- exports

    def export_grid(self) -> Dict[str, Any]:
        m = self.meta
        return {'grids': pack(self.codes), 'grid_size': m['grid_size'], 'floors': m['floors'], 'bbox': m['bbox'],
                'unit_size': 1.0, 'doors': m.get('doors', []), 'ifc_spaces': m.get('ifc_spaces', []),
                'compartments': m.get('compartments', []), 'original_ifc_filename': m.get('source_file'),
                'settings': self.settings, 'overrides': self.overrides, 'exits': self.exits}

    # ------------------------------------------------------------------- disk

    def save_soon(self) -> None:
        if self._save_timer is not None:
            self._save_timer.cancel()
        self._save_timer = threading.Timer(SAVE_DELAY, self.save)
        self._save_timer.daemon = True
        self._save_timer.start()

    def save(self) -> None:
        with self.lock:
            os.makedirs(self.directory, exist_ok=True)
            np.savez_compressed(os.path.join(self.directory, 'grids.tmp.npz'), *self.codes)
            os.replace(os.path.join(self.directory, 'grids.tmp.npz'), os.path.join(self.directory, 'grids.npz'))
            state = {'id': self.id, 'name': self.name, 'meta': self.meta, 'settings': self.settings,
                     'overrides': self.overrides, 'exits': self.exits, 'created': self.created, 'updated': self.updated}
            tmp = os.path.join(self.directory, 'project.tmp.json')
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(state, f)
            os.replace(tmp, os.path.join(self.directory, 'project.json'))

    @classmethod
    def load(cls, pid: str) -> 'Project':
        directory = os.path.join(PROJECT_DIR, pid)
        with open(os.path.join(directory, 'project.json'), encoding='utf-8') as f:
            state = json.load(f)
        with np.load(os.path.join(directory, 'grids.npz')) as data:
            codes = [data[f'arr_{i}'] for i in range(len(data.files))]
        project = cls(state['id'], state['name'], state['meta'], codes, state.get('settings'), state.get('overrides'),
                      state.get('exits'), state.get('created'))
        project.updated = state.get('updated', project.created)
        return project


class ProjectStore:
    def __init__(self):
        self.projects: Dict[str, Project] = {}
        self.lock = threading.Lock()

    def create(self, name: str, meta: Dict[str, Any], codes: List[np.ndarray], settings=None, overrides=None,
               exits=None, ifc_path: Optional[str] = None) -> Project:
        pid = uuid.uuid4().hex[:12]
        project = Project(pid, name, meta, codes, settings, overrides, exits)
        os.makedirs(project.directory, exist_ok=True)
        if ifc_path:
            target = os.path.join(project.directory, 'model.ifc')
            shutil.copyfile(ifc_path, target)
            project.meta['ifc_file'] = target
        project.save()
        with self.lock:
            self.projects[pid] = project
        return project

    def get(self, pid: str) -> Project:
        with self.lock:
            if pid not in self.projects:
                if not os.path.isfile(os.path.join(PROJECT_DIR, pid, 'project.json')):
                    raise KeyError(pid)
                self.projects[pid] = Project.load(pid)
            return self.projects[pid]

    def list(self) -> List[Dict[str, Any]]:
        out = []
        if os.path.isdir(PROJECT_DIR):
            for pid in os.listdir(PROJECT_DIR):
                path = os.path.join(PROJECT_DIR, pid, 'project.json')
                if not os.path.isfile(path):
                    continue
                try:
                    with open(path, encoding='utf-8') as f:
                        state = json.load(f)
                    out.append({'id': pid, 'name': state['name'], 'floors': len(state['meta']['floors']),
                                'created': state.get('created'), 'updated': state.get('updated'),
                                'source': state['meta'].get('source_file')})
                except Exception:
                    continue
        return sorted(out, key=lambda p: p.get('updated') or 0, reverse=True)


def project_from_grid_file(data: Dict[str, Any]) -> Dict[str, Any]:
    """meta and codes from a saved grid JSON (packed or nested names)."""
    codes = to_codes(data['grids'])
    meta = {'grid_size': float(data['grid_size']) * float(data.get('unit_size') or 1.0), 'floors': data['floors'],
            'bbox': data['bbox'], 'doors': data.get('doors', []), 'ifc_spaces': data.get('ifc_spaces', []),
            'compartments': data.get('compartments', []), 'warnings': data.get('warnings', {}),
            'source_file': data.get('original_ifc_filename')}
    return {'meta': meta, 'codes': codes, 'settings': data.get('settings'), 'overrides': data.get('overrides'),
            'exits': data.get('exits')}


class Jobs:
    """Background jobs (IFC conversion) with progress."""

    def __init__(self):
        self.jobs: Dict[str, Dict[str, Any]] = {}
        self.lock = threading.Lock()

    def start(self, work, description: str) -> str:
        jid = uuid.uuid4().hex[:12]
        job = {'id': jid, 'status': 'running', 'progress': 0.0, 'message': description, 'result': None, 'error': None,
               'started': _now()}
        with self.lock:
            self.jobs[jid] = job

        def progress(fraction: float, message: str) -> None:
            job['progress'] = round(float(fraction), 3)
            job['message'] = message

        def run():
            try:
                job['result'] = work(progress)
                job['status'] = 'done'
                job['progress'] = 1.0
            except Exception as e:  # reported to the app
                traceback.print_exc()
                job['status'] = 'error'
                job['error'] = str(e)

        threading.Thread(target=run, daemon=True).start()
        return jid

    def get(self, jid: str) -> Dict[str, Any]:
        with self.lock:
            job = self.jobs.get(jid)
        if job is None:
            raise KeyError(jid)
        return {k: v for k, v in job.items()}
