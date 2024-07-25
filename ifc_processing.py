import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.placement
import numpy as np
from typing import Dict, List, Tuple, Any
import traceback
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Constants
WALL_TYPES = ['IfcWall', 'IfcWallStandardCase', 'IfcColumn', 'IfcCurtainWall', 'IfcWindow', 'IfcCovering']
FLOOR_TYPES = ['IfcSlab', 'IfcFloor']
DOOR_TYPES = ['IfcDoor']
STAIR_TYPES = ['IfcStair', 'IfcStairFlight']
ALL_TYPES = WALL_TYPES + FLOOR_TYPES + DOOR_TYPES + STAIR_TYPES

class IFCProcessor:
    def __init__(self, file_path: str, grid_size: float = 0.2):
        self.file_path = file_path
        self.grid_size = grid_size
        self.ifc_file = None
        self.bbox = None
        self.floors = None
        self.grids = None
        self.unit_size = 1.0
        self.spaces = []
        self.global_transform = None
        self.include_empty_tiles = False

    def process(self) -> Dict[str, Any]:
        try:
            self.ifc_file = self.load_ifc_file()
            self.bbox, self.floors = self.calculate_bounding_box_and_floors()
            self.determine_unit_size()
            self.grids = self.create_grids()
            self.process_elements()
            #self.detect_spaces()
            self.trim_grids()

            return {
                'grids': [grid.tolist() for grid in self.grids],
                'bbox': self.bbox,
                'floors': self.floors,
                'grid_size': self.grid_size,
                'unit_size': self.unit_size,
                'spaces': self.spaces
            }
        except Exception as e:
            logger.error(f"Error processing IFC file: {str(e)}")
            logger.error(traceback.format_exc())

    def detect_spaces(self):
        self.spaces = []
        for floor_index, grid in enumerate(self.grids):
            space_id = 0
            visited = np.zeros_like(grid, dtype=bool)
            for i in range(grid.shape[0]):
                for j in range(grid.shape[1]):
                    if not visited[i, j] and (grid[i, j] == 'floor' or (self.include_empty_tiles and grid[i, j] == 'empty')):
                        space_id += 1
                        self.flood_fill(grid, visited, i, j, floor_index, space_id)

    def flood_fill(self, grid, visited, i, j, floor_index, space_id):
        stack = [(i, j)]
        points = []
        while stack:
            x, y = stack.pop()
            if visited[x, y]:
                continue
            visited[x, y] = True
            points.append((x, y))
            for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                nx, ny = x + dx, y + dy
                if 0 <= nx < grid.shape[0] and 0 <= ny < grid.shape[1]:
                    if not visited[nx, ny] and (grid[nx, ny] == 'floor' or (self.include_empty_tiles and grid[nx, ny] == 'empty')):
                        stack.append((nx, ny))
        
        if points:
            min_x = min(p[1] for p in points)
            max_x = max(p[1] for p in points)
            min_y = min(p[0] for p in points)
            max_y = max(p[0] for p in points)
            self.spaces.append({
                "id": f"Space_{floor_index}_{space_id}",
                "name": f"Space {space_id}",
                "floor": floor_index,
                "bounds": {
                    "min_x": min_x * self.grid_size + self.bbox['min_x'],
                    "max_x": (max_x + 1) * self.grid_size + self.bbox['min_x'],
                    "min_y": min_y * self.grid_size + self.bbox['min_y'],
                    "max_y": (max_y + 1) * self.grid_size + self.bbox['min_y']
                },
                "points": points
            })

    def set_include_empty_tiles(self, include: bool):
        self.include_empty_tiles = include
        self.detect_spaces()


    def extract_spaces(self):
        settings = ifcopenshell.geom.settings()
        settings.set(settings.USE_WORLD_COORDS, True)

        for space in self.ifc_file.by_type("IfcSpace"):
            try:
                shape = ifcopenshell.geom.create_shape(settings, space)
                verts = shape.geometry.verts
                faces = shape.geometry.faces
                
                space_info = {
                    "id": space.GlobalId,
                    "name": space.Name,
                    "points": self.extract_2d_points(verts, faces),
                    "floor": self.determine_space_floor(verts)
                }
                self.spaces.append(space_info)
            except Exception as e:
                logger.warning(f"Failed to process space {space.GlobalId}: {str(e)}")

    def extract_2d_points(self, verts, faces):
        points = []
        for i in range(0, len(verts), 3):
            x = (verts[i] - self.bbox['min_x']) / self.grid_size
            y = (verts[i+1] - self.bbox['min_y']) / self.grid_size
            points.append((x, y))
        return list(set(points))  # Remove duplicates

    def determine_space_floor(self, verts):
        z_coords = verts[2::3]
        avg_z = sum(z_coords) / len(z_coords)
        for i, floor in enumerate(self.floors):
            if floor["elevation"] <= avg_z < floor["elevation"] + floor["height"]:
                return i
        return -1  # If no matching floor is found

    def determine_unit_size(self):
        x_size = self.bbox['max_x'] - self.bbox['min_x']
        y_size = self.bbox['max_y'] - self.bbox['min_y']
        x_cells = int(np.ceil(x_size / (self.grid_size/self.unit_size))) + 6
        y_cells = int(np.ceil(y_size / (self.grid_size/self.unit_size))) + 6
        if x_cells>10000 or y_cells > 10000:
            self.unit_size /= 1000
            self.grid_size *= 1000
        logger.info(f"Determined unit scale: {self.unit_size}")
    
    def load_ifc_file(self) -> ifcopenshell.file:
        try:
            return ifcopenshell.open(self.file_path)
        except Exception as e:
            raise RuntimeError(f"Error loading IFC file: {str(e)}")

    def calculate_bounding_box_and_floors(self) -> Tuple[Dict[str, float], List[Dict[str, float]]]:
        settings = ifcopenshell.geom.settings()
        settings.set(settings.USE_WORLD_COORDS, True)

        bbox = {
            'min_x': float('inf'), 'min_y': float('inf'), 'min_z': float('inf'),
            'max_x': float('-inf'), 'max_y': float('-inf'), 'max_z': float('-inf')
        }
        floor_elevations = set()

        for item in self.ifc_file.by_type('IfcWall'):
            if item.Representation:
                try:
                    shape = ifcopenshell.geom.create_shape(settings, item)
                    verts = shape.geometry.verts
                    for i in range(0, len(verts), 3):
                        x, y, z = verts[i:i + 3]
                        bbox['min_x'] = min(bbox['min_x'], x)
                        bbox['min_y'] = min(bbox['min_y'], y)
                        bbox['min_z'] = min(bbox['min_z'], z)
                        bbox['max_x'] = max(bbox['max_x'], x)
                        bbox['max_y'] = max(bbox['max_y'], y)
                        bbox['max_z'] = max(bbox['max_z'], z)
                except RuntimeError:
                    pass

        logger.info(f"Calculated bounding box: {bbox}")

        # Sanity check
        max_reasonable_size = 1000  # 1 km
        for axis in 'xyz':
            size = bbox[f'max_{axis}'] - bbox[f'min_{axis}']
            if size > max_reasonable_size:
                logger.warning(f"Unreasonably large bounding box size for {axis}-axis: {size} meters")

        for storey in self.ifc_file.by_type("IfcBuildingStorey"):
            if storey.Elevation is not None:
                floor_elevations.add(float(storey.Elevation))

        floor_elevations = sorted(list(floor_elevations))

        if not floor_elevations or min(floor_elevations) < bbox['min_z'] or max(floor_elevations) > bbox['max_z']:
            logger.warning("Floor elevations inconsistent with bounding box, creating default floors")
            num_floors = max(1, int((bbox['max_z'] - bbox['min_z']) / 3))  # Assume 3m floor height
            floor_elevations = np.linspace(bbox['min_z'], bbox['max_z'], num_floors + 1)[:-1]

        floors = []
        for i, elevation in enumerate(floor_elevations):
            next_elevation = floor_elevations[i + 1] if i < len(floor_elevations) - 1 else bbox['max_z']
            height = next_elevation - elevation
            if height > 1.6 and height < 10:
                floors.append({'elevation': elevation, 'height': height})

        if not floors:
            logger.warning("No valid floors found, creating a single floor based on bounding box")
            floors = [{'elevation': bbox['min_z'], 'height': bbox['max_z'] - bbox['min_z']}]

        logger.info(f"Created {len(floors)} floors")
        return bbox, floors

    def create_grids(self) -> List[np.ndarray]:
        x_size = self.bbox['max_x'] - self.bbox['min_x']
        y_size = self.bbox['max_y'] - self.bbox['min_y']

        x_cells = int(np.ceil(x_size / (self.grid_size))) + 6
        y_cells = int(np.ceil(y_size / (self.grid_size))) + 6

        logger.info(f"Creating grid with dimensions: {x_cells} x {y_cells}")

        if x_cells > 10000 or y_cells > 10000:
            logger.warning(f"Very large grid size: {x_cells} x {y_cells}. This may cause performance issues.")

        return [np.full((x_cells, y_cells), 'empty', dtype=object) for _ in self.floors]


    def process_elements(self) -> None:
        settings = ifcopenshell.geom.settings()
        settings.set(settings.USE_WORLD_COORDS, True)

        elements = [element for element in self.ifc_file.by_type('IfcProduct') if element.is_a() in ALL_TYPES]

        for element in elements:
            if element.Representation:
                try:
                    self.process_single_element(element, settings)
                except Exception as e:
                    logger.warning(f"Error processing element {element.id()}: {str(e)}")

    def process_single_element(self, element: ifcopenshell.entity_instance, settings: ifcopenshell.geom.settings) -> None:
        try:
            shape = ifcopenshell.geom.create_shape(settings, element)
            verts = shape.geometry.verts
            faces = shape.geometry.faces
        except RuntimeError as e:
            logger.warning(f"Failed to process: {element.is_a()}, Error: {str(e)}")
            return

        element_type = self.get_element_type(element)
        if element_type is None:
            return

        if not verts:
            print(f"Warning: No vertices found for {element.is_a()} (ID: {element.id()}), faces: " + str(len(faces)))
            return
        #else:
        #    print(f"Vertices found for {element.is_a()} (ID: {element.id()}), faces: " + str(len(faces)))

        min_x = min(verts[i] for i in range(0, len(verts), 3))
        max_x = max(verts[i] for i in range(0, len(verts), 3))
        min_y = min(verts[i+1] for i in range(0, len(verts), 3))
        max_y = max(verts[i+1] for i in range(0, len(verts), 3))
        min_z = min(verts[i+2] for i in range(0, len(verts), 3))
        max_z = max(verts[i+2] for i in range(0, len(verts), 3))
        if element.is_a() in FLOOR_TYPES or element.is_a() in STAIR_TYPES:
            max_z += 1.5/self.unit_size # Extend the floors up so they get detected better

        for floor_index, floor in enumerate(self.floors):
            #print(str(min_z) + " " + str(max_z) + " " + str(floor['elevation']) + " " + str(floor['elevation'] + floor['height']) + " " + str(0.5/self.unit_size))
            #print( + 0.5/self.unit_size)
            if min_z < floor['elevation'] + 2/self.unit_size and max_z > floor['elevation'] + 0.5/self.unit_size:
                if element_type == 'door':
                    # Use bounding box for doors
                    self.mark_door(floor_index, min_x, min_y, max_x, max_y, floor)
                elif element_type == 'stair':
                    # Use bounding box for doors
                    self.mark_stair(floor_index, min_x, min_y, max_x, max_y, floor)
                else:
                    # Use detailed geometry for other elements
                    for i in range(0, len(faces), 3):
                        triangle = [verts[faces[i]*3:faces[i]*3+3],
                                    verts[faces[i+1]*3:faces[i+1]*3+3],
                                    verts[faces[i+2]*3:faces[i+2]*3+3]]
                        self.mark_cells(triangle, self.grids[floor_index], floor, element_type)

    def mark_door(self, floor_index: int, min_x: float, min_y: float, max_x: float, max_y: float, floor: Dict[str, float]) -> None:
        start_x = max(0, int((min_x - self.bbox['min_x']) / self.grid_size))
        end_x = min(self.grids[floor_index].shape[0] - 1, int((max_x - self.bbox['min_x']) / self.grid_size))
        start_y = max(0, int((min_y - self.bbox['min_y']) / self.grid_size))
        end_y = min(self.grids[floor_index].shape[1] - 1, int((max_y - self.bbox['min_y']) / self.grid_size))

        for x in range(start_x, end_x + 1):
            for y in range(start_y, end_y + 1):
                self.grids[floor_index][x, y] = 'door'

    def mark_stair(self, floor_index: int, min_x: float, min_y: float, max_x: float, max_y: float, stair: Dict[str, float]) -> None:
        start_x = max(0, int((min_x - self.bbox['min_x']) / self.grid_size))
        end_x = min(self.grids[floor_index].shape[0] - 1, int((max_x - self.bbox['min_x']) / self.grid_size))
        start_y = max(0, int((min_y - self.bbox['min_y']) / self.grid_size))
        end_y = min(self.grids[floor_index].shape[1] - 1, int((max_y - self.bbox['min_y']) / self.grid_size))

        for x in range(start_x, end_x + 1):
            for y in range(start_y, end_y + 1):
                if self.grids[floor_index][x, y] not in ['door', 'wall']:
                    self.grids[floor_index][x, y] = 'stair'

    def get_element_type(self, element: ifcopenshell.entity_instance) -> str:
        if element.is_a() in WALL_TYPES:
            return 'wall'
        elif element.is_a() in DOOR_TYPES:
            return 'door'
        elif element.is_a() in STAIR_TYPES:
            return 'stair'
        elif element.is_a() in FLOOR_TYPES:
            return 'floor'
        else:
            return None

    def mark_cells(self, triangle: List[List[float]], grid: np.ndarray, floor: Dict[str, float], element_type: str) -> None:
        min_x = min(p[0] for p in triangle)
        max_x = max(p[0] for p in triangle)
        min_y = min(p[1] for p in triangle)
        max_y = max(p[1] for p in triangle)
        min_z = min(p[2] for p in triangle)
        max_z = max(p[2] for p in triangle)

        if min_z < floor['elevation'] + floor['height'] and max_z > floor['elevation']:
            start_x = max(0, int((min_x - self.bbox['min_x']) / self.grid_size))
            end_x = min(grid.shape[0] - 1, int((max_x - self.bbox['min_x']) / self.grid_size))
            start_y = max(0, int((min_y - self.bbox['min_y']) / self.grid_size))
            end_y = min(grid.shape[1] - 1, int((max_y - self.bbox['min_y']) / self.grid_size))

            for x in range(start_x, end_x + 1):
                for y in range(start_y, end_y + 1):
                    current = grid[x, y]
                    if element_type == 'door' or (element_type == 'wall' and current != 'door') or (
                            element_type == 'stair' and current not in ['door', 'wall']) or (
                            element_type == 'floor' and current == 'empty'):
                        grid[x, y] = element_type

    def trim_grids(self, padding: int = 1) -> None:
        logger.info("Starting grid trimming process")
        trimmed_grids = []
        min_x_global = float('inf')
        max_x_global = float('-inf')
        min_y_global = float('inf')
        max_y_global = float('-inf')

        all_empty = True

        for i, grid in enumerate(self.grids):
            logger.debug(f"Processing grid {i}, shape: {grid.shape}")
            non_empty = np.argwhere((grid != 'empty') & (grid != 'floor'))
            if len(non_empty) == 0:
                logger.warning(f"Grid {i} is entirely empty or floor, skipping trimming")
                trimmed_grids.append(grid)
                continue
            
            all_empty = False
            min_x, min_y = non_empty.min(axis=0)
            max_x, max_y = non_empty.max(axis=0)
            logger.debug(f"Grid {i} non-empty area: ({min_x}, {min_y}) to ({max_x}, {max_y})")

            min_x_global = min(min_x_global, min_x)
            max_x_global = max(max_x_global, max_x)
            min_y_global = min(min_y_global, min_y)
            max_y_global = max(max_y_global, max_y)


        if all_empty:
            logger.warning("All grids are empty or contain only floor cells. Skipping trimming.")
            self.grids = [grid for grid in self.grids]  # Create a copy of the original grids
            return
        
        logger.info(f"Global non-empty area: ({min_x_global}, {min_y_global}) to ({max_x_global}, {max_y_global})")

        for i, grid in enumerate(self.grids):
            try:
                # Ensure all indices are integers
                start_x = max(0, int(min_x_global - padding))
                end_x = min(grid.shape[0], int(max_x_global + padding + 1))
                start_y = max(0, int(min_y_global - padding))
                end_y = min(grid.shape[1], int(max_y_global + padding + 1))

                logger.debug(f"Trimming grid {i} from ({start_x}, {start_y}) to ({end_x}, {end_y})")

                trimmed = grid[start_x:end_x, start_y:end_y]

                # Add padding if necessary
                padded = np.full((trimmed.shape[0] + 2 * padding, trimmed.shape[1] + 2 * padding), 'empty', dtype=object)
                padded[padding:-padding, padding:-padding] = trimmed

                trimmed_grids.append(padded)
                logger.debug(f"Grid {i} trimmed to shape: {padded.shape}")

            except Exception as e:
                logger.error(f"Error trimming grid {i}: {str(e)}")
                logger.error(f"Grid shape: {grid.shape}")
                logger.error(f"Attempted slice: [{start_x}:{end_x}, {start_y}:{end_y}]")
                # If trimming fails, append the original grid
                trimmed_grids.append(grid)

        self.grids = trimmed_grids

        # Update bounding box
        x_size = self.grids[0].shape[0] * self.grid_size
        y_size = self.grids[0].shape[1] * self.grid_size
        self.bbox['min_x'] -= self.grid_size * padding
        self.bbox['min_y'] -= self.grid_size * padding
        self.bbox['max_x'] = self.bbox['min_x'] + x_size
        self.bbox['max_y'] = self.bbox['min_y'] + y_size

        logger.info("Grid trimming complete")
        logger.info(f"Final grid dimensions: {self.grids[0].shape}")
        logger.info(f"Updated bounding box: {self.bbox}")

def process_ifc_file(file_path: str, grid_size: float = 0.1) -> Dict[str, Any]:
    processor = IFCProcessor(file_path, grid_size)
    return processor.process()