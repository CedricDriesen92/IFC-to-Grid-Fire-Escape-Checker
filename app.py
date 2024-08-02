from flask import Flask, request, jsonify, render_template, send_from_directory, redirect
from werkzeug.utils import secure_filename
import os
from typing import List, Dict, Tuple, Any
from ifc_processing import process_ifc_file
from grid_management import GridManager, validate_grid_data
from pathfinding import Pathfinder, find_path, detect_exits, calculate_escape_route, calculate_escape_routes, check_escape_route_rules
import json
import webbrowser
from threading import Timer

import logging
import sys, traceback


logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Last created graph
graphs = None

hasGridChanged = True

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
        file.save(filepath)
        
        if filename.lower().endswith('.json'):
            return jsonify({'output': 'Reset...'}), 200
        else:
            grid_size = float(request.form.get('grid_size', 0.1))
            try:
                result = process_ifc_file(filepath, grid_size)
                return jsonify(result), 200
            except Exception as e:
                app.logger.error(f"Error processing file: {str(e)}")
                traceback.print_exc(file=sys.stdout)
                return jsonify({'error': 'An error occurred while processing the file'}), 500
    
    return jsonify({'error': 'Invalid file type'}), 400

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'ifc', 'json'}

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
        grid_manager = GridManager(data['grids'], data['grid_size'], data['floors'], data['bbox'])
        buffered_grids = grid_manager.apply_wall_buffer(int(data['wall_buffer']))
        return jsonify({
            'buffered_grids': buffered_grids,
            'original_grids': grid_manager.get_original_grids()
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
        buffered_grids = grid_manager.apply_wall_buffer(int(data['wall_buffer']))
        return jsonify({
            'buffered_grids': buffered_grids,
            'original_grids': grid_manager.get_original_grids()
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
        buffered_grids = grid_manager.apply_wall_buffer(int(data['wall_buffer']))
        return jsonify({
            'original_grids': grid_manager.get_original_grids(),
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
        exits = detect_exits(data['grids'], data['grid_size'], data['floors'], data['bbox'])
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
        spaces = grid_manager.detect_spaces(data.get('include_empty_tiles', False))
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
            data.get('allow_diagonal', False)
        )
        if not graphs:
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
        floor = data['floor']

        connections = []
        for edge in graph.edges():
            start_node, end_node = edge
            if start_node[2] != end_node[2]:  # Different floors
                connections.append({
                    'start': start_node,
                    'end': end_node
                })

        return jsonify(connections)
    except Exception as e:
        logger.error(f"Error getting stair connections: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/api/calculate-escape-route', methods=['POST'])
def api_calculate_escape_route():
    data = request.json
    try:
        graph, pathfinder = graphs
        
        space = data['space']
        exits = data['exits']
        
        result = pathfinder.calculate_escape_route(space, exits)
        violations = check_escape_route_rules(result, pathfinder.grid_size)
        result['violations'] = violations
        
        return jsonify({'escape_route': result})
    except ValueError as e:
        logger.error(f"Validation error: {str(e)}", exc_info=True)
        return jsonify({'error': f'Invalid input data: {str(e)}'}), 400
    except Exception as e:
        logger.error(f"Error calculating escape route: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

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
