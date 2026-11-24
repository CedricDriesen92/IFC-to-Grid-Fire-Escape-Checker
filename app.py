from flask import Flask, request, jsonify, render_template, send_from_directory, send_file
from werkzeug.utils import secure_filename
import os
from typing import List, Dict, Tuple, Any
from ifc_processing import process_ifc_file, add_escape_routes_to_ifc
from grid_management import GridManager, validate_grid_data
from pathfinding import Pathfinder, find_path, detect_exits, check_escape_route_rules, required_exits, NOT_CHECKED
from grid_codec import pack, to_codes
import json
from xml.sax.saxutils import escape
import webbrowser
from threading import Timer

from io import BytesIO

from report import build_pdf
from projects import ProjectStore, Jobs, project_from_grid_file
import i18n

import logging
import sys, traceback


logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Last created graph
graphs = None
hasGridChanged = True
ifc_filepath = None
origin_filepath = None

if getattr(sys, 'frozen', False):
    template_folder = os.path.join(sys._MEIPASS, 'templates')
    static_folder = os.path.join(sys._MEIPASS, 'static')
    app = Flask(__name__, template_folder=template_folder, static_folder=static_folder)
else:
    app = Flask(__name__)
app.config.from_object('config')

@app.route('/')
def index() -> str:
    return render_template('index.html')

@app.route('/api/process-file', methods=['POST'])
def process_file() -> tuple[Dict[str, Any], int]:
    global graphs
    global hasGridChanged
    global ifc_filepath
    global origin_filepath
    graphs = None
    hasGridChanged = True
    
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        origin_filepath = filepath
        file.save(filepath)
        
        if file.filename.lower().endswith('.json'):
            ifc_filepath = file.filename.replace('_edited.json', '.ifc')
            return jsonify({'output': 'Reset...'}), 200
        else:
            ifc_filepath = file.filename
            grid_size = float(request.form.get('grid_size', 0.1))
            try:
                result = process_ifc_file(filepath, grid_size)
                if request.form.get('packed') == '1':
                    result['grids'] = pack(to_codes(result['grids']))
                return jsonify(result), 200
            except Exception as e:
                app.logger.error(f"Error processing file: {str(e)}")
                traceback.print_exc(file=sys.stdout)
                return jsonify({'error': f'An error occurred while processing the file: {str(e)}'}), 500
    
    return jsonify({'error': 'Invalid file type'}), 400

def validate_json_data(data):
    required_keys = ['grids', 'grid_size', 'floors', 'bbox']
    return all(key in data for key in required_keys)

@app.route('/api/edit-grid', methods=['POST'])
def edit_grid() -> tuple[Dict[str, Any], int]:
    global hasGridChanged
    data = request.json
    try:
        grid_manager = GridManager(data['grids'], data['grid_size'], data['floors'], data['bbox'])
        updated_grids = grid_manager.edit_grid(data['edits'])
        hasGridChanged = True
        return jsonify({'grids': updated_grids}), 200
    except Exception as e:
        app.logger.error(f"Error editing grid: {str(e)}")
        return jsonify({'error': 'An error occurred while editing the grid'}), 500

@app.route('/api/find-path', methods=['POST'])
def find_path_route() -> tuple[Dict[str, Any], int]:
    data = request.json
    try:
        path, path_lengths = find_path(
            data['grids'], 
            data['grid_size'], 
            data['floors'], 
            data['bbox'], 
            data['start'], 
            data['goals'],
            data.get('allow_diagonal', False),
            data.get('minimize_cost', True)
        )
        return jsonify({
            'path': path, 
            'path_lengths': path_lengths
        }), 200
    except Exception as e:
        app.logger.error(f"Error finding path: {str(e)}")
        return jsonify({'error': f'An error occurred while finding the path: {str(e)}'}), 500

@app.route('/api/apply-wall-buffer', methods=['POST'])
def apply_wall_buffer() -> Tuple[Dict[str, Any], int]:
    global hasGridChanged
    hasGridChanged = True
    data = request.json
    try:
        validate_grid_data(data['grids'], data['grid_size'], data['floors'], data['bbox'])
        packed = bool(data.get('packed'))
        grid_manager = GridManager(data['grids'], data['grid_size'], data['floors'], data['bbox'])
        buffered_grids = grid_manager.apply_wall_buffer(int(data['wall_buffer']), packed)
        return jsonify({
            'buffered_grids': buffered_grids,
            'original_grids': grid_manager.get_original_grids(packed)
        }), 200
    except ValueError as e:
        logger.error(f"Validation error: {str(e)}", exc_info=True)
        return jsonify({'error': f'Invalid input data: {str(e)}'}), 400
    except Exception as e:
        logger.error(f"Error applying wall buffer: {str(e)}", exc_info=True)
        return jsonify({'error': f'An error occurred while applying wall buffer: {str(e)}'}), 500

@app.route('/api/update-cell', methods=['POST'])
def update_cell() -> Tuple[Dict[str, Any], int]:
    global hasGridChanged
    hasGridChanged = True
    data = request.json
    try:
        grid_manager = GridManager(data['grids'], data['grid_size'], data['floors'], data['bbox'])
        grid_manager.update_cell(data['floor'], data['row'], data['col'], data['cell_type'])
        packed = bool(data.get('packed'))
        buffered_grids = grid_manager.apply_wall_buffer(int(data['wall_buffer']), packed)
        return jsonify({
            'buffered_grids': buffered_grids,
            'original_grids': grid_manager.get_original_grids(packed)
        }), 200
    except ValueError as e:
        app.logger.error(f"Validation error: {str(e)}", exc_info=True)
        return jsonify({'error': f'Invalid input data: {str(e)}'}), 400
    except Exception as e:
        app.logger.error(f"Error updating cell: {str(e)}", exc_info=True)
        return jsonify({'error': f'An error occurred while updating the cell: {str(e)}'}), 500

@app.route('/api/batch-update-cells', methods=['POST'])
def batch_update_cells():
    global hasGridChanged
    hasGridChanged = True
    data = request.json
    try:
        grid_manager = GridManager(data['grids'], data['grid_size'], data['floors'], data['bbox'])
        for update in data['updates']:
            grid_manager.update_cell(update['floor'], update['row'], update['col'], update['type'])
        packed = bool(data.get('packed'))
        buffered_grids = grid_manager.apply_wall_buffer(int(data['wall_buffer']), packed)
        return jsonify({
            'original_grids': grid_manager.get_original_grids(packed),
            'buffered_grids': buffered_grids
        }), 200
    except ValueError as e:
        app.logger.error(f"Validation error: {str(e)}", exc_info=True)
        return jsonify({'error': f'Invalid input data: {str(e)}'}), 400
    except Exception as e:
        app.logger.error(f"Error updating cells: {str(e)}", exc_info=True)
        return jsonify({'error': f'An error occurred while updating cells: {str(e)}'}), 500
    
@app.route('/api/detect-exits', methods=['POST'])
def detect_exits_route() -> tuple[Dict[str, Any], int]:
    data = request.json
    try:
        exits = detect_exits(data['grids'], data['grid_size'], data['floors'], data['bbox'], data.get('doors'), data.get('original_grids'))
        return jsonify({'exits': exits}), 200
    except Exception as e:
        app.logger.error(f"Error detecting exits: {str(e)}")
        return jsonify({'error': f'An error occurred while detecting exits: {str(e)}'}), 500

@app.route('/api/update-spaces', methods=['POST'])
def detect_spaces_route() -> tuple[Dict[str, Any], int]:
    data = request.json
    try:
        validate_grid_data(data['grids'], data['grid_size'], data['floors'], data['bbox'])
        grid_manager = GridManager(data['grids'], data['grid_size'], data['floors'], data['bbox'])
        spaces = grid_manager.detect_spaces(data.get('include_empty_tiles', False), data.get('ifc_spaces'),
                                            data.get('space_source', 'ifc'))
        return jsonify({'spaces': spaces}), 200
    except ValueError as e:
        logger.error(f"Validation error: {str(e)}", exc_info=True)
        return jsonify({'error': f'Invalid input data: {str(e)}'}), 400
    except Exception as e:
        logger.error(f"Error detecting spaces: {str(e)}", exc_info=True)
        return jsonify({'error': f'An error occurred while detecting spaces: {str(e)}'}), 500
    
@app.route('/api/create-graph', methods=['POST'])
def api_create_graph():
    global graphs
    global hasGridChanged
    data = request.json
    try:
        logger.debug(f"Received data for graph creation: {data.keys()}")
        
        required_keys = ['original_grids', 'buffered_grids', 'grid_size', 'floors', 'bbox']
        for key in required_keys:
            if key not in data:
                raise ValueError(f"Missing required key: {key}")

        validate_grid_data(data['buffered_grids'], data['grid_size'], data['floors'], data['bbox'])
        
        pathfinder = Pathfinder(
            data['original_grids'],
            data['buffered_grids'],
            data['grid_size'],
            data['floors'],
            data['bbox'],
            data['allow_diagonal'],
            data['minimize_cost']
        )
        #if not graphs:
        #if hasGridChanged or not graphs:
        graph = pathfinder.create_graph()
        hasGridChanged = False
        graphs = (graph, pathfinder)
        
        return jsonify({'status': 'success'})
    except ValueError as e:
        logger.error(f"Validation error: {str(e)}", exc_info=True)
        return jsonify({'error': f'Invalid input data: {str(e)}'}), 400
    except KeyError as e:
        logger.error(f"Missing key in input data: {str(e)}", exc_info=True)
        return jsonify({'error': f'Missing key in input data: {str(e)}'}), 400
    except Exception as e:
        logger.error(f"Error creating graph: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/api/get-stair-connections', methods=['POST'])
def get_stair_connections():
    global graphs
    data = request.json
    try:
        if graphs is None:
            return jsonify({'error': 'Graph not created'}), 400

        graph, pathfinder = graphs
        connections = [{'start': start_node, 'end': end_node} for start_node, end_node, _ in pathfinder.stair_edges]
        return jsonify(connections)
    except Exception as e:
        logger.error(f"Error getting stair connections: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

def graph_missing():
    return jsonify({'error': 'Create the graph first (/api/create-graph)'}), 400

@app.route('/api/calculate-escape-routes', methods=['POST'])
def api_calculate_escape_routes():
    """Escape routes of all spaces at once, from one distance field from the exits."""
    data = request.json
    if graphs is None:
        return graph_missing()
    try:
        graph, pathfinder = graphs
        require_second_exit = bool(data.get('require_second_exit', False))
        occupancy = data.get('occupancy')
        occupancy = float(occupancy) if occupancy not in (None, '') else None
        needed = max(required_exits(occupancy), 2 if require_second_exit else 1)
        results = pathfinder.calculate_escape_routes(data['spaces'], data['exits'],
                                                     stairs_as_exits=bool(data.get('stairs_as_exits', True)),
                                                     with_second=needed >= 2)
        for result in results:
            result['violations'] = check_escape_route_rules(result, pathfinder.grid_size, require_second_exit, occupancy)
        return jsonify({'escape_routes': results, 'required_exits': needed, 'not_checked': NOT_CHECKED})
    except (ValueError, KeyError) as e:
        logger.error(f"Validation error: {str(e)}", exc_info=True)
        return jsonify({'error': f'Invalid input data: {str(e)}'}), 400
    except Exception as e:
        logger.error(f"Error calculating escape routes: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/api/calculate-escape-route', methods=['POST'])
def api_calculate_escape_route():
    data = request.json
    if graphs is None:
        return graph_missing()
    try:
        graph, pathfinder = graphs

        space = data['space']
        exits = data['exits']
        spaces = data['spaces']
        
        occupancy = data.get('occupancy')
        occupancy = float(occupancy) if occupancy not in (None, '') else None
        require_second_exit = bool(data.get('require_second_exit', False))
        needed = max(required_exits(occupancy), 2 if require_second_exit else 1)
        result = pathfinder.calculate_escape_route(space, exits, spaces, bool(data.get('stairs_as_exits', True)), needed >= 2)
        violations = check_escape_route_rules(result, pathfinder.grid_size, require_second_exit, occupancy)
        result['violations'] = violations
        
        return jsonify({'escape_route': result})
    except ValueError as e:
        logger.error(f"Validation error: {str(e)}", exc_info=True)
        return jsonify({'error': f'Invalid input data: {str(e)}'}), 400
    except Exception as e:
        logger.error(f"Error calculating escape route: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500
    
@app.route('/api/update-ifc-with-routes', methods=['POST'])
def api_update_ifc_with_routes():
    try:
        if 'file' not in request.files:
            logger.error("No file part in the request")
            return jsonify({'error': 'No file part'}), 400
        
        file = request.files['file']
        if file.filename == '':
            logger.error("No selected file")
            return jsonify({'error': 'No selected file'}), 400
        
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            logger.info(f"File saved to {filepath}")
            
            routes = json.loads(request.form['routes'])
            grid_size = float(request.form['grid_size'])
            bbox = json.loads(request.form['bbox'])
            floors = json.loads(request.form['floors'])
            
            output_dir = os.path.join(app.config['UPLOAD_FOLDER'], "ifc_output")
            os.makedirs(output_dir, exist_ok=True)
            new_file = os.path.join(output_dir, os.path.splitext(filename)[0] + "_withroutes.ifc")
            
            logger.info(f"Processing IFC file: {filepath}")
            logger.info(f"Output file: {new_file}")
            
            result = add_escape_routes_to_ifc(filepath, new_file, routes, grid_size, bbox, floors)
            
            if os.path.exists(new_file):
                file_size = os.path.getsize(new_file)
                logger.info(f"New IFC file created: {new_file}, size: {file_size} bytes")
                return send_file(new_file, as_attachment=True, download_name=os.path.basename(new_file))
            else:
                logger.error(f"Failed to create new IFC file: {new_file}")
                return jsonify({'error': 'Failed to create updated IFC file'}), 500
        else:
            logger.error(f"Invalid file type: {file.filename}")
            return jsonify({'error': 'Invalid file type'}), 400
    except Exception as e:
        logger.error(f"Error updating IFC with routes: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@app.route('/api/generate-pdf-report', methods=['POST'])
def generate_pdf_report():
    data = request.json
    filename = os.path.splitext(data['filename'])[0]
    occupancy = data.get('occupancy')
    occupancy = float(occupancy) if occupancy not in (None, '') else None
    needed = max(required_exits(occupancy), 2 if bool(data.get('require_second_exit', False)) else 1)
    pdf = build_pdf(data['escape_routes'], data['floors'], filename + '.ifc', data.get('language', 'en'),
                    occupancy=occupancy, needed=needed)
    return send_file(BytesIO(pdf), as_attachment=True, download_name=f"{filename}_report.pdf", mimetype='application/pdf')


# ------------------------------------------------------------------ projects (server-side state)

store = ProjectStore()
jobs = Jobs()


def project_or_404(pid):
    try:
        return store.get(pid)
    except KeyError:
        return None


def not_found():
    return jsonify({'error': 'Project not found'}), 404


@app.route('/api/projects', methods=['GET'])
def list_projects():
    return jsonify({'projects': store.list()})


@app.route('/api/projects', methods=['POST'])
def create_project():
    """Upload one or more IFC files of one building (converted together in the background: returns a job), or a
    saved grid JSON (returns the project)."""
    uploads = [f for f in request.files.getlist('file') if f and f.filename]
    if not uploads or not all(allowed_file(f.filename) for f in uploads):
        return jsonify({'error': 'Choose .ifc files or one saved grid .json file'}), 400
    is_json = [f.filename.lower().endswith('.json') for f in uploads]
    if any(is_json) and len(uploads) > 1:
        return jsonify({'error': 'Load a grid .json file on its own, not together with other files'}), 400
    file = uploads[0]
    filename = secure_filename(file.filename)
    name = request.form.get('name') or os.path.splitext(file.filename)[0] + (f" + {len(uploads) - 1}" if len(uploads) > 1 else '')
    if filename.lower().endswith('.json'):
        try:
            data = json.load(file.stream)
            parts = project_from_grid_file(data)
        except Exception as e:
            return jsonify({'error': f'Not a grid file this tool can read: {e}'}), 400
        project = store.create(name, parts['meta'], parts['codes'], parts['settings'], parts['overrides'], parts['exits'])
        return jsonify({'project': project.state()}), 201

    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    paths = []
    for upload in uploads:
        path = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(upload.filename))
        upload.save(path)
        paths.append(path)
    names = [u.filename for u in uploads]
    grid_size = float(request.form.get('grid_size') or 0.1)
    mapping = request.form.get('mapping') or None
    if 'mapping_file' in request.files and request.files['mapping_file'].filename:
        mapping = request.files['mapping_file'].read().decode('utf-8')
    if mapping:
        try:
            from ifc_processing import load_mapping
            load_mapping(mapping)
        except Exception as e:
            return jsonify({'error': f'Mapping file: {e}'}), 400

    def work(progress):
        result = process_ifc_file(paths if len(paths) > 1 else paths[0], grid_size, mapping, progress)
        meta = {k: result[k] for k in ('grid_size', 'floors', 'bbox', 'doors', 'ifc_spaces', 'compartments', 'warnings')}
        meta['source_file'] = names[0] if len(names) == 1 else f"{names[0]} + {len(names) - 1} more"
        meta['source_files'] = names
        meta['mapping'] = mapping
        project = store.create(name, meta, to_codes(result['grids']), ifc_paths=paths)
        return {'project_id': project.id}

    return jsonify({'job_id': jobs.start(work, 'Converting the IFC file' if len(paths) == 1 else f'Converting {len(paths)} IFC files')}), 202


@app.route('/api/jobs/<jid>', methods=['GET'])
def job_status(jid):
    try:
        return jsonify(jobs.get(jid))
    except KeyError:
        return jsonify({'error': 'Job not found'}), 404


@app.route('/api/projects/<pid>', methods=['GET'])
def get_project(pid):
    project = project_or_404(pid)
    return jsonify(project.state()) if project else not_found()


@app.route('/api/projects/<pid>/edit', methods=['POST'])
def edit_project(pid):
    """{"floor": f, "type": "wall", "cells": [[row, col], ...]} or {"floor": f, "type": ..., "fill": [row, col]}"""
    project = project_or_404(pid)
    if not project:
        return not_found()
    data = request.json
    try:
        if data.get('fill') is not None:
            diff = project.fill(int(data['floor']), int(data['fill'][0]), int(data['fill'][1]), data['type'])
        else:
            diff = project.edit(int(data['floor']), data.get('cells', []), data['type'])
        return jsonify(diff)
    except (KeyError, ValueError, IndexError) as e:
        return jsonify({'error': f'Invalid edit: {e}'}), 400


@app.route('/api/projects/<pid>/undo', methods=['POST'])
def undo_project(pid):
    project = project_or_404(pid)
    if not project:
        return not_found()
    diff = project.undo_last(redo=bool((request.json or {}).get('redo')))
    return jsonify(diff or {'floor': None, 'original': [], 'buffered': [], 'can_undo': bool(project.undo), 'can_redo': bool(project.redo)})


@app.route('/api/projects/<pid>/settings', methods=['POST'])
def project_settings(pid):
    project = project_or_404(pid)
    if not project:
        return not_found()
    rebuffered = project.update_settings(request.json or {})
    out = {'settings': project.settings}
    if rebuffered:
        out['buffered'] = pack(project.buffered)
    return jsonify(out)


@app.route('/api/projects/<pid>/floors', methods=['POST'])
def project_floors(pid):
    project = project_or_404(pid)
    if not project:
        return not_found()
    data = request.json or {}
    try:
        project.floors_action(data.get('action'), int(data.get('floor', 0)))
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    return jsonify(project.state())


@app.route('/api/projects/<pid>/exits', methods=['POST'])
def project_exits(pid):
    """{"exits": [[row, col, floor], ...]} to place exits by hand, or {"exits": null} to detect them again."""
    project = project_or_404(pid)
    if not project:
        return not_found()
    project.set_exits((request.json or {}).get('exits'))
    detected = project.detected_exits() if project.exits is None else None
    return jsonify({'exits': project.exits, 'detected': detected, 'note': project.exit_note if detected is not None else None})


@app.route('/api/projects/<pid>/overrides', methods=['POST'])
def project_overrides(pid):
    """{"use": {space_id: "day" | "night" | null}, "occupancy": {compartment_id: persons | null}}"""
    project = project_or_404(pid)
    if not project:
        return not_found()
    data = request.json or {}
    project.update_overrides(data.get('use'), data.get('occupancy'))
    return jsonify({'overrides': project.overrides})


@app.route('/api/projects/<pid>/analyse', methods=['POST'])
def analyse_project(pid):
    """Run the checks. With ?background=1 they run as a job with progress (poll /api/jobs/<id>; its result holds
    the results), else the results come back directly."""
    project = project_or_404(pid)
    if not project:
        return not_found()
    if request.args.get('background'):
        return jsonify({'job_id': jobs.start(lambda progress: {'results': project.analyse(progress)}, 'Checking the routes')}), 202
    try:
        return jsonify(project.analyse())
    except Exception as e:
        logger.error(f"Analysis failed: {e}", exc_info=True)
        return jsonify({'error': f'The analysis failed: {e}'}), 500


@app.route('/api/projects/<pid>/path', methods=['POST'])
def project_path(pid):
    project = project_or_404(pid)
    if not project:
        return not_found()
    data = request.json or {}
    try:
        return jsonify(project.find_path(data['start'], data['goals']))
    except (KeyError, ValueError) as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/projects/<pid>/ifc', methods=['POST'])
def attach_project_ifc(pid):
    """Attach the IFC a grid file was made from, so the routes can be exported into it."""
    project = project_or_404(pid)
    if not project:
        return not_found()
    file = request.files.get('file')
    if file is None or not file.filename.lower().endswith('.ifc'):
        return jsonify({'error': 'Choose the .ifc file this grid was made from'}), 400
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    path = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(file.filename))
    file.save(path)
    project.attach_ifc(path)
    return jsonify({'ifc_file': True})


@app.route('/api/projects/<pid>/export/<kind>', methods=['GET'])
def export_project(pid, kind):
    project = project_or_404(pid)
    if not project:
        return not_found()
    base = secure_filename(project.name) or 'project'
    if kind == 'grid':
        body = json.dumps(project.export_grid())
        return send_file(BytesIO(body.encode('utf-8')), as_attachment=True, download_name=f"{base}_grid.json",
                         mimetype='application/json')
    results = project.results or project.analyse()
    if kind == 'pdf':
        lang = request.args.get('lang') or project.settings.get('language', 'en')
        m = project.meta
        plans = {'codes': project.codes, 'grid_size': m['grid_size'], 'bbox': m['bbox'], 'spaces': results['spaces'],
                 'exits': [e['cell'] for e in results['exits']]}
        pdf = build_pdf(project.routes_in(lang), m['floors'], m.get('source_file') or project.name, lang,
                        compartments=results['compartments'], plans=plans)
        return send_file(BytesIO(pdf), as_attachment=True, download_name=f"{base}_report_{lang}.pdf", mimetype='application/pdf')
    if kind == 'ifc':
        # a project of several files: ?file=<index> picks the one the routes are added to (default the first)
        m = project.meta
        ifc_paths = m.get('ifc_files') or ([m['ifc_file']] if m.get('ifc_file') else [])
        index = int(request.args.get('file') or 0)
        if not ifc_paths or not 0 <= index < len(ifc_paths) or not os.path.isfile(ifc_paths[index]):
            return jsonify({'error': 'This project has no IFC file (it was loaded from a grid file): attach the IFC first'}), 400
        names = m.get('source_files') or [m.get('source_file') or base]
        target = os.path.splitext(secure_filename(names[index] if index < len(names) else base))[0] or base
        out = os.path.join(project.directory, f"{target}_with_routes.ifc")
        # each floor's storey in that file (a file without the storey gets the routes on its first storey)
        floors = [{**f, 'guid': f['guids'][index] if index < len(f.get('guids') or []) else f.get('guid')} for f in m['floors']]
        add_escape_routes_to_ifc(ifc_paths[index], out, results['routes'], m['grid_size'], m['bbox'], floors)
        return send_file(out, as_attachment=True, download_name=f"{target}_with_routes.ifc")
    return jsonify({'error': f'Unknown export {kind}'}), 400


@app.route('/static/<path:path>')
def send_static(path: str) -> Any:
    return send_from_directory('static', path)

def allowed_file(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def open_browser():
      webbrowser.open_new("http://localhost:8000")

if __name__ == '__main__':
    Timer(1, open_browser).start()
    app.run(host='localhost', debug=app.config['DEBUG'], port=8000)
