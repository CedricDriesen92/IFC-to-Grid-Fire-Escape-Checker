from flask import Flask, request, jsonify, render_template, send_from_directory
from werkzeug.utils import secure_filename
import os
from typing import List, Dict, Tuple, Any
from ifc_processing import process_ifc_file
from grid_management import GridManager, validate_grid_data
from pathfinding import find_path
import json

import logging
import traceback


logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config.from_object('config')

@app.route('/')
def index() -> str:
    return render_template('index.html')

@app.route('/api/process-file', methods=['POST'])
def process_file() -> tuple[Dict[str, Any], int]:
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
            with open(filepath, 'r') as f:
                data = json.load(f)
            return jsonify(data), 200
        else:
            grid_size = float(request.form.get('grid_size', 0.1))
            try:
                result = process_ifc_file(filepath, grid_size)
                return jsonify(result), 200
            except Exception as e:
                app.logger.error(f"Error processing file: {str(e)}")
                return jsonify({'error': 'An error occurred while processing the file'}), 500
    
    return jsonify({'error': 'Invalid file type'}), 400

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'ifc', 'json'}

@app.route('/api/edit-grid', methods=['POST'])
def edit_grid() -> tuple[Dict[str, Any], int]:
    data = request.json
    try:
        grid_manager = GridManager(data['grids'], data['grid_size'], data['floors'], data['bbox'])
        updated_grids = grid_manager.edit_grid(data['edits'])
        return jsonify({'grids': updated_grids}), 200
    except Exception as e:
        app.logger.error(f"Error editing grid: {str(e)}")
        return jsonify({'error': 'An error occurred while editing the grid'}), 500

@app.route('/api/find-path', methods=['POST'])
def find_path_route() -> tuple[Dict[str, Any], int]:
    data = request.json
    try:
        path, path_length = find_path(
            data['grids'], 
            data['grid_size'], 
            data['floors'], 
            data['bbox'], 
            data['start'], 
            data['goals'],
            data.get('allow_diagonal', True),
            data.get('minimize_cost', True)
        )
        return jsonify({'path': path, 'path_length': path_length}), 200
    except Exception as e:
        app.logger.error(f"Error finding path: {str(e)}")
        return jsonify({'error': f'An error occurred while finding the path: {str(e)}'}), 500

@app.route('/api/apply-wall-buffer', methods=['POST'])
def apply_wall_buffer() -> Tuple[Dict[str, Any], int]:
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
        app.logger.error(f"Validation error: {str(e)}", exc_info=True)
        return jsonify({'error': f'Invalid input data: {str(e)}'}), 400
    except Exception as e:
        app.logger.error(f"Error applying wall buffer: {str(e)}", exc_info=True)
        return jsonify({'error': f'An error occurred while applying wall buffer: {str(e)}'}), 500

@app.route('/api/update-cell', methods=['POST'])
def update_cell() -> Tuple[Dict[str, Any], int]:
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

@app.route('/static/<path:path>')
def send_static(path: str) -> Any:
    return send_from_directory('static', path)

def allowed_file(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

if __name__ == '__main__':
    app.run(debug=app.config['DEBUG'])
